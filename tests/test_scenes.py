"""Current-scene routing and legacy data compatibility, without alias migration."""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import agent
from runtime.benchmark import Benchmark, read_cases
from runtime.engine import Engine, LEGACY_SCENES, SCENES, fingerprint, scene_config
from runtime.learning import Learning
from runtime.store import Store


class SceneTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "state")
        self.engine, self.learning = Engine(self.store), Learning(self.store)

    def tearDown(self):
        self.store.finish()
        self.temp.cleanup()

    def complete(self, scene, index=0):
        run = self.engine.start(f"项目{index}还在讨论，尚未确定。", scene, host="test-host")
        task = self.engine.draft(run["id"], run["source"])["task"]
        return self.engine.review(run["id"], {
            "run_id": run["id"], "draft_sha256": task["draft_sha256"], "fidelity_pass": True,
            "scene_pass": True, "needs_revision": False, "naturalness": 4, "issues": [],
            "review_mode": "independent", "reviewer": "simulated-test-reviewer"})

    def test_exact_current_categories_and_separate_legacy_resources(self):
        expected = {
            "general": "通用文章", "fanqie-fiction": "番茄小说改写", "xiaohongshu": "小红书图文文案",
            "douyin-copy": "抖音图文文案", "xiaohongshu-video": "小红书视频口播",
            "douyin-video": "抖音视频口播", "wechat": "微信公众号文章", "speech": "演讲稿",
        }
        current = json.loads((ROOT / "references/scenes.json").read_text(encoding="utf-8"))
        legacy = json.loads((ROOT / "references/legacy-scenes.json").read_text(encoding="utf-8"))
        self.assertEqual(SCENES, tuple(expected))
        self.assertEqual(set(current), set(expected))
        self.assertEqual(set(LEGACY_SCENES), {"douyin-tech", "customer-service"})
        self.assertEqual(set(legacy), set(LEGACY_SCENES))
        self.assertFalse(current.keys() & legacy.keys())
        for scene, name in expected.items():
            with self.subTest(scene=scene):
                self.assertEqual(scene_config(scene)["name"], name)
        for scene in LEGACY_SCENES:
            with self.subTest(legacy_scene=scene):
                self.assertEqual(scene_config(scene)["instructions"], legacy[scene]["instructions"])
                for mode in ("light", "strong"):
                    self.assertEqual(scene_config(scene, mode)["deai_instructions"], legacy[scene]["deai_instructions"][mode])

    def test_cli_start_accepts_current_and_legacy_ids_without_remapping(self):
        source = Path(self.temp.name) / "source.txt"
        source.write_text("保留原来的判断。", encoding="utf-8")
        for scene in SCENES + LEGACY_SCENES:
            with self.subTest(scene=scene), redirect_stdout(io.StringIO()) as output:
                code = agent.main(["start", "--scene", scene, "--text-file", str(source),
                                   "--data-dir", str(Path(self.temp.name) / "cli")])
                result = json.loads(output.getvalue())
                self.assertEqual(code, 0, result)
                self.assertEqual(result["scene"], scene)
                self.assertEqual(result["task"]["scene"], scene_config(scene))

    def test_cli_scene_commands_share_compatibility_validation(self):
        cli = agent.parser()
        for command in ("profile", "learn", "propose", "rollback"):
            arguments = [command] + (["--json-file", "proposal.json"] if command == "propose" else [])
            for scene in SCENES + LEGACY_SCENES:
                with self.subTest(command=command, scene=scene):
                    self.assertEqual(cli.parse_args(arguments + ["--scene", scene]).scene, scene)
            with self.subTest(command=command), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                cli.parse_args(arguments + ["--scene", "unknown-scene"])
            self.assertEqual(error.exception.code, 2)

    def test_cli_help_displays_only_eight_current_scene_ids(self):
        with redirect_stdout(io.StringIO()) as output, self.assertRaises(SystemExit) as error:
            agent.parser().parse_args(["start", "--help"])
        self.assertEqual(error.exception.code, 0)
        help_text = "".join(output.getvalue().split())
        for scene in SCENES:
            self.assertIn(scene, help_text)
        for scene in LEGACY_SCENES:
            self.assertNotIn(scene, help_text)

    def test_unknown_scene_has_no_fallback_or_saved_run(self):
        for scene in ("unknown-scene", "douyin", "customer", "", None):
            with self.subTest(scene=scene):
                with self.assertRaisesRegex(ValueError, "未知场景"):
                    scene_config(scene)
                with self.assertRaisesRegex(ValueError, "未知场景"):
                    self.engine.start("保留原来的判断。", scene)
        self.assertEqual(self.store.list("run", "local"), [])

    def test_missing_legacy_resource_does_not_use_current_scene_rules(self):
        original = Path.is_file
        def without_legacy(path):
            return False if path == ROOT / "references/legacy-scenes.json" else original(path)
        with patch.object(Path, "is_file", without_legacy):
            self.assertEqual(scene_config("general")["name"], "通用文章")
            with self.assertRaisesRegex(ValueError, "缺少 references/legacy-scenes.json"):
                scene_config("customer-service")
            with redirect_stdout(io.StringIO()) as output:
                self.assertEqual(agent.main(["doctor"]), 0)
            self.assertFalse(json.loads(output.getvalue())["resources_present"])

    def test_historical_pending_runs_remain_readable_but_cannot_resume_old_rules(self):
        for scene in LEGACY_SCENES:
            with self.subTest(scene=scene):
                run = self.engine.start("原有处理条件不变。", scene)
                stored = self.store.get(run["id"], "run")
                stored["fingerprint"] = "historical-release"
                del stored["deai"]
                self.store.update(stored, "run")
                shown = self.engine.show(run["id"])
                self.assertEqual(shown["scene"], scene)
                self.assertEqual(shown["deai"], "off")
                self.assertEqual(shown["task"]["scene"], scene_config(scene))
                with self.assertRaisesRegex(ValueError, "规则或程序版本已改变"):
                    self.engine.draft(run["id"], run["source"])

    def test_historical_completed_feedback_and_learning_stay_in_legacy_scope(self):
        for scene in LEGACY_SCENES:
            feedback_ids = set()
            for index in range(6):
                run = self.complete(scene, index)
                stored = self.store.get(run["id"], "run")
                stored["fingerprint"] = "historical-release"
                del stored["deai"]
                self.store.update(stored, "run")
                self.assertEqual(self.engine.show(run["id"])["output"], run["output"])
                feedback = self.engine.feedback(run["id"], run["output"], "accepted")
                self.assertEqual(self.store.get(feedback["id"], "feedback")["scene"], scene)
                feedback_ids.add(feedback["id"])
            self.assertEqual(self.learning.profile("local", scene)["feedback_count"], 6)
            batch = self.learning.learn("local", scene)
            training_ids = [row["id"] for row in batch["task"]["training_feedback"]]
            self.assertTrue(set(training_ids) <= feedback_ids)
            proposal = {"batch_id": batch["batch_id"], "preferences": [{"key": "tone", "value": "neutral",
                        "evidence_ids": training_ids, "reason": "模拟同一历史场景的三条反馈。"}]}
            for current_scene in SCENES:
                with self.subTest(legacy=scene, current=current_scene):
                    self.assertEqual(self.learning.profile("local", current_scene)["feedback_count"], 0)
                    with self.assertRaisesRegex(ValueError, "当前 0 篇"):
                        self.learning.learn("local", current_scene)
                    with self.assertRaisesRegex(ValueError, "学习批次场景不符"):
                        self.learning.propose("local", current_scene, proposal)
            candidate = self.learning.propose("local", scene, proposal)
            self.assertEqual(candidate["scene"], scene)

    def test_legacy_profiles_keep_scene_host_and_fingerprint_gates(self):
        current = fingerprint()
        for scene in LEGACY_SCENES:
            prefs = [{"key": "tone", "value": "formal", "evidence_ids": [], "reason": "模拟已验证画像。"}]
            profile = self.store.save("candidate", "local", scene, {
                "preferences": prefs, "fingerprint": current, "report": {"host": "test-host", "fingerprint": current}})
            self.store.set_profile("local", scene, profile["id"], [])
            reused = self.engine.start("保留原来的判断。", scene, host="test-host")
            self.assertEqual(reused["profile_id"], profile["id"])
            self.assertEqual(reused["preferences"], prefs)
            for target_scene in SCENES:
                run = self.engine.start("保留原来的判断。", target_scene, host="test-host")
                self.assertEqual(run["preferences"], [])
                self.assertIsNone(run["profile_id"])
            for profile_fp, report_fp, host in ((current, current, "other-host"),
                                                ("old-release", current, "test-host"),
                                                (current, "old-release", "test-host")):
                with self.subTest(scene=scene, profile_fp=profile_fp, report_fp=report_fp, host=host):
                    profile["fingerprint"] = profile_fp
                    profile["report"]["fingerprint"] = report_fp
                    self.store.update(profile, "candidate")
                    run = self.engine.start("保留原来的判断。", scene, host=host)
                    self.assertEqual(run["preferences"], [])
                    self.assertIsNone(run["profile_id"])
                    self.assertIsNotNone(run["profile_warning"])

    def test_legacy_benchmark_cases_still_prepare_with_original_ids(self):
        cases = [case for case in read_cases("agent_cases.jsonl") if case["scene"] in LEGACY_SCENES]
        self.assertEqual({case["scene"] for case in cases}, set(LEGACY_SCENES))
        prepared = Benchmark(self.store).prepare(case_ids=[case["id"] for case in cases])
        actual = {task["case_id"]: self.store.get(task["run_id"], "run")["scene"] for task in prepared["tasks"]}
        self.assertEqual(actual, {case["id"]: case["scene"] for case in cases})

    def test_legacy_config_changes_are_included_in_fingerprint(self):
        original = Path.read_bytes
        actual = fingerprint()
        def changed_legacy(path):
            content = original(path)
            return content + b"\n" if path == ROOT / "references/legacy-scenes.json" else content
        with patch.object(Path, "read_bytes", changed_legacy):
            self.assertNotEqual(fingerprint(), actual)


if __name__ == "__main__":
    unittest.main()
