"""v0.3 permission/state contracts; simulated reviews do not rate model quality."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from runtime import VERSION
from runtime.benchmark import Benchmark, read_cases
from runtime.engine import Engine, fingerprint, review_schema, scene_config
from runtime.evaluators import scan_style
from runtime.learning import Learning
from runtime.store import Store


class DeaiRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "state")
        self.engine, self.learning, self.bench = Engine(self.store), Learning(self.store), Benchmark(self.store)

    def tearDown(self):
        self.store.finish()
        self.temp.cleanup()

    def verdict(self, run_id):
        task = self.engine.show(run_id)["task"]
        value = {"run_id": run_id, "draft_sha256": task["draft_sha256"], "fidelity_pass": True,
                 "scene_pass": True, "needs_revision": False, "naturalness": 4,
                 "issues": [], "review_mode": "independent", "reviewer": "test-context"}
        if task["deai"] != "off":
            value["template_check"] = {"added_patterns": [], "remaining_patterns": [], "flattened_colloquial": []}
        return value

    def complete(self, source, mode="off", output=None):
        run = self.engine.start(source, deai=mode)
        self.engine.draft(run["id"], source if output is None else output)
        return self.engine.review(run["id"], self.verdict(run["id"]))

    def candidate(self, modes=("light", "strong", "off", "strong", "light", "off"), preferences=None):
        # Last three deliberately have different permissions; validation must
        # reproduce each one on both arms rather than using the newest mode.
        for i, mode in enumerate(modes):
            run = self.complete(f"项目{i}仍在讨论。", mode)
            self.engine.feedback(run["id"], run["output"], "accepted")
        batch = self.learning.learn("local", "general", "independent")
        preferences = preferences or [("intensity", "soften")]
        candidate = self.learning.propose("local", "general", {"batch_id": batch["batch_id"], "preferences": [
            {"key": key, "value": value, "evidence_ids": [r["id"] for r in batch["task"]["training_feedback"]],
             "reason": "仅模拟三条独立编辑证据，不宣称真实用户收益。"} for key, value in preferences]})
        return batch, candidate

    def complete_personal(self, prepared, wins):
        bench = self.store.get(prepared["id"], "benchmark")
        for case in bench["cases"]:
            for arm in ("baseline", "candidate"):
                run_id = case[f"{arm}_run"]
                source = self.store.get(run_id, "run")["source"]
                output = source.replace("。", "；", 1) if arm == "candidate" and case["id"] in wins else source
                self.engine.draft(run_id, output)
                self.engine.review(run_id, self.verdict(run_id))
        self.bench.report(bench["id"])
        return self.bench.submit_comparisons(bench["id"], {"benchmark_id": bench["id"], "comparisons": [
            {"case_id": case["id"], "a_pass": True, "b_pass": True,
             "winner": case["candidate_side"] if case["id"] in wins else "tie", "reason": "仅模拟判定以测试门控",
             "review_mode": "independent", "reviewer": "test-context"} for case in bench["cases"]]})

    def test_isolated_python_starts_from_unrelated_working_directory(self):
        result = subprocess.run([sys.executable, "-I", str(ROOT / "scripts/agent.py"), "doctor"],
                                cwd=self.temp.name, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["version"], VERSION)
        self.assertTrue(data["resources_present"])
        self.assertFalse((Path(self.temp.name) / ".faithful-writing-agent").exists())

    def test_default_and_explicit_off_keep_legacy_review_and_style(self):
        source = "首先，我们必须赋能生态。不是甲，而是乙。"
        expected_keys = {"run_id", "draft_sha256", "fidelity_pass", "scene_pass", "needs_revision",
                         "naturalness", "issues", "review_mode", "reviewer"}
        for kwargs in ({}, {"deai": "off"}):
            run = self.engine.start(source, **kwargs)
            drafted = self.engine.draft(run["id"], source)
            self.assertEqual(drafted["deai"], "off")
            self.assertEqual(set(drafted["task"]["schema"]["required"]), expected_keys)
            self.assertEqual(drafted["task"]["style_hints"], scan_style(source))
            self.assertNotIn("comparison_hints", drafted["task"])
            self.assertNotIn("deai_instructions", drafted["task"]["scene"])
            bad = self.verdict(run["id"])
            bad["template_check"] = {"added_patterns": [], "remaining_patterns": [], "flattened_colloquial": []}
            with self.assertRaises(ValueError):
                self.engine.review(run["id"], bad)
            self.assertEqual(self.engine.review(run["id"], self.verdict(run["id"]))["status"], "unchanged")

    def test_legacy_run_without_mode_defaults_off_but_version_gate_still_applies(self):
        run = self.engine.start("方案仍在讨论。")
        stored = self.store.get(run["id"], "run")
        del stored["deai"]
        self.store.update(stored, "run")
        self.assertEqual(self.engine.show(run["id"])["task"]["deai"], "off")
        self.engine.draft(run["id"], stored["source"])
        with patch("runtime.engine.fingerprint", return_value="new-version"):
            with self.assertRaisesRegex(ValueError, "规则或程序版本"):
                self.engine.review(run["id"], self.verdict(run["id"]))

    def test_new_preferences_never_turn_on_or_escalate_mode(self):
        prefs = [{"key": "intensity", "value": "soften"}, {"key": "rhetoric", "value": "reduce"},
                 {"key": "address", "value": "minimal"}, {"key": "tone", "value": "neutral"}]
        for mode in ("off", "light", "strong"):
            run = self.engine.start("我强烈反对这个方案。", preferences=prefs, deai=mode)
            self.assertEqual(run["deai"], mode)
            self.assertEqual(run["task"]["deai"], mode)
            self.assertEqual(len(run["preferences"]), 1 if mode == "off" else 4)
            if mode == "light":
                instructions = run["task"]["instructions"]
                self.assertIn("不改论述结构", instructions)
                self.assertIn("不软化绝对化断言", instructions)
                self.assertIn("仅去重复程度词", instructions)
            if mode == "strong":
                self.assertIn("全称量化", run["task"]["instructions"])
        self.assertEqual(len(prefs), 4, "Filtering must not mutate the saved profile")

    def test_invalid_mode_rejected_without_creating_run(self):
        for mode in ("medium", "LIGHT", "", None, True, []):
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                self.engine.start("文章。", deai=mode)
        self.assertEqual(self.store.list("run", "local"), [])

    def test_scene_only_exposes_current_mode_instructions(self):
        fake = {"general": {"name": "常规", "instructions": ["原规则"],
                            "deai_instructions": {"light": "轻度", "strong": "强度"}}}
        with patch.object(Path, "read_text", return_value=json.dumps(fake)):
            self.assertNotIn("deai_instructions", scene_config("general"))
            self.assertEqual(scene_config("general", "light")["deai_instructions"], "轻度")
            self.assertEqual(scene_config("general", "strong")["deai_instructions"], "强度")

    def test_enabled_mode_requires_strict_template_check(self):
        run = self.engine.start("方案仍在讨论。", deai="light")
        self.engine.draft(run["id"], run["source"])
        good = self.verdict(run["id"])
        bad_values = []
        missing = copy.deepcopy(good)
        del missing["template_check"]
        bad_values.append(missing)
        for value in ([], {}, {"added_patterns": [], "remaining_patterns": [], "flattened_colloquial": [], "extra": []}):
            bad_values.append(dict(good, template_check=value))
        for value in ("none", [1], [False], [None], [" "], ["x"] * 51):
            check = copy.deepcopy(good["template_check"])
            check["added_patterns"] = value
            bad_values.append(dict(good, template_check=check))
        for value in bad_values:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.engine.review(run["id"], value)
        self.assertEqual(self.engine.show(run["id"])["status"], "awaiting_review")
        self.assertEqual(self.engine.review(run["id"], good)["status"], "unchanged")

    def test_comparison_hints_and_review_findings_are_preserved_without_hard_failure(self):
        source = "这项功能让它封神。"
        candidate = "功能：这项功能让它很出色。"
        run = self.engine.start(source, deai="light")
        drafted = self.engine.draft(run["id"], candidate)
        task = drafted["task"]
        self.assertIn("source_style_hints", task)
        codes = {row["code"] for row in task["comparison_hints"]}
        self.assertTrue({"ADDED_TEMPLATE", "COLLOQUIAL_FLATTENED"} <= codes)
        self.assertTrue(all(row["severity"] == "warning" for row in task["comparison_hints"]))
        verdict = self.verdict(run["id"])
        verdict["template_check"] = {"added_patterns": ["改稿新增‘功能：’冒号结构"],
                                     "remaining_patterns": [], "flattened_colloquial": ["封神→很出色"]}
        result = self.engine.review(run["id"], verdict)
        self.assertEqual(result["status"], "passed_with_warnings")
        self.assertEqual(result["template_check"], verdict["template_check"])
        self.assertEqual(self.store.get(run["id"], "run")["reviews"][-1]["template_check"], verdict["template_check"])

    def test_feedback_and_learning_keep_each_mode(self):
        batch, candidate = self.candidate()
        self.assertEqual([row["deai"] for row in batch["task"]["training_feedback"]], ["light", "strong", "off"])
        self.assertEqual(batch["task"]["allowed_values"]["intensity"], ["preserve", "soften"])
        self.assertEqual(batch["task"]["allowed_values"]["rhetoric"], ["preserve", "reduce"])
        self.assertEqual(batch["task"]["allowed_values"]["address"], ["preserve", "minimal"])
        self.assertEqual(candidate["preferences"][0]["key"], "intensity")

    def test_legacy_feedback_defaults_off_in_training_and_holdout(self):
        for i in range(6):
            run = self.complete(f"方案{i}仍在讨论。")
            feedback = self.engine.feedback(run["id"], run["output"], "accepted")
            saved = self.store.get(feedback["id"], "feedback")
            del saved["deai"]
            self.store.update(saved, "feedback")
        batch = self.learning.learn("local", "general")
        self.assertTrue(all(row["deai"] == "off" for row in batch["task"]["training_feedback"]))
        candidate = self.learning.propose("local", "general", {"batch_id": batch["batch_id"], "preferences": [
            {"key": "tone", "value": "neutral", "reason": "模拟证据", "evidence_ids": [r["id"] for r in batch["task"]["training_feedback"]]}]})
        prepared = self.bench.prepare(candidate_id=candidate["id"])
        self.assertTrue(all(task["task"]["deai"] == "off" for task in prepared["tasks"] if task["case_id"].startswith("holdout")))

    def test_personalization_preserves_holdout_mode_on_both_arms_and_core_mode(self):
        _, candidate = self.candidate()
        fixed = [{"id": "core-light", "scene": "general", "source": "第一个核心案例。", "deai": "light"},
                 {"id": "core-strong", "scene": "general", "source": "第二个核心案例。", "deai": "strong"}]
        with patch("runtime.benchmark.read_cases", return_value=fixed):
            prepared = self.bench.prepare(candidate_id=candidate["id"])
        self.assertEqual(prepared["total_runs"], 10)
        expected = {"holdout-1": "strong", "holdout-2": "light", "holdout-3": "off", "core-light": "light", "core-strong": "strong"}
        for task in prepared["tasks"]:
            self.assertEqual(task["task"]["deai"], expected[task["case_id"]])
            run = self.store.get(task["run_id"], "run")
            self.assertEqual(run["deai"], expected[task["case_id"]])
            self.engine.draft(run["id"], run["source"])
            self.engine.review(run["id"], self.verdict(run["id"]))
        report = self.bench.report(prepared["id"])
        self.assertEqual({row["case_id"]: row["deai"] for row in report["tasks"]}, expected)
        submitted = self.bench.submit_comparisons(prepared["id"], {"benchmark_id": prepared["id"], "comparisons": [
            {"case_id": row["case_id"], "a_pass": True, "b_pass": True, "winner": "tie", "reason": "两稿相同",
             "review_mode": "independent", "reviewer": "test-context"} for row in report["tasks"]]})
        self.assertFalse(submitted["passed"])
        for detail in submitted["details"]:
            self.assertEqual(detail["deai"], expected[detail["case_id"]])
            if detail["deai"] != "off":
                self.assertIsInstance(detail["candidate_template_check"], dict)
                self.assertIsInstance(detail["baseline_template_check"], dict)

    def test_public_case_selection_is_exact_and_never_cuts_personal_gate(self):
        cases = read_cases("agent_cases.jsonl")
        selected = [cases[-1]["id"], cases[0]["id"]]
        prepared = self.bench.prepare(case_ids=selected)
        self.assertEqual({task["case_id"] for task in prepared["tasks"]}, set(selected))
        self.assertEqual(prepared["total_cases"], 2)
        for kwargs in ({"case_ids": ["missing"]}, {"case_ids": [selected[0]] * 2}, {"case_ids": []},
                       {"case_ids": "not-a-list"}, {"case_ids": selected, "limit": 1},
                       {"case_ids": selected, "candidate_id": "anything"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.bench.prepare(**kwargs)

    def test_public_report_retains_mode_and_template_check(self):
        cases = [{"id": "mode-check", "scene": "general", "source": "信息保持原样。", "deai": "light"}]
        with patch("runtime.benchmark.read_cases", return_value=cases):
            prepared = self.bench.prepare(case_ids=["mode-check"])
        run_id = prepared["tasks"][0]["run_id"]
        self.engine.draft(run_id, cases[0]["source"])
        verdict = self.verdict(run_id)
        self.engine.review(run_id, verdict)
        report = self.bench.report(prepared["id"])
        self.assertTrue(report["passed"])
        self.assertEqual(report["details"][0]["deai"], "light")
        self.assertEqual(report["details"][0]["template_check"], verdict["template_check"])

    def test_all_off_cannot_validate_new_deai_preferences(self):
        _, candidate = self.candidate(modes=("off",) * 6,
                                      preferences=[("intensity", "soften"), ("rhetoric", "reduce"), ("address", "minimal")])
        with self.assertRaisesRegex(ValueError, "address, intensity, rhetoric"):
            self.bench.prepare(candidate_id=candidate["id"])
        self.assertEqual(self.store.list("benchmark", "local"), [])
        self.assertEqual(self.store.get(candidate["id"], "candidate")["status"], "pending")
        self.assertEqual(len(self.store.list("run", "local")), 6, "Rejected coverage cannot create partial runs")
        with self.assertRaises(ValueError):
            self.learning.activate(candidate["id"], "local", True)

    def test_mixed_candidate_cannot_hide_uncovered_key_behind_ordinary_style(self):
        _, candidate = self.candidate(modes=("off",) * 6, preferences=[("tone", "neutral"), ("address", "minimal")])
        with self.assertRaisesRegex(ValueError, "address"):
            self.bench.prepare(candidate_id=candidate["id"])

    def test_changed_and_removed_deai_preferences_need_enabled_coverage(self):
        active = self.store.save("candidate", "local", "general", {
            "preferences": [{"key": "tone", "value": "formal"}, {"key": "address", "value": "minimal"}],
            "holdout_ids": [], "dataset_ids": [], "fingerprint": fingerprint(),
            "report": {"host": "unknown", "fingerprint": fingerprint()}})
        self.store.set_profile("local", "general", active["id"], [])
        _, candidate = self.candidate(modes=("off",) * 6, preferences=[("tone", "neutral"), ("address", "preserve")])
        with self.assertRaisesRegex(ValueError, "address"):
            self.bench.prepare(candidate_id=candidate["id"])
        # The same untested deletion must not become a shortcut around coverage.
        stored = self.store.get(candidate["id"], "candidate")
        stored["preferences"] = [stored["preferences"][0]]
        self.store.update(stored, "candidate")
        with self.assertRaisesRegex(ValueError, "address"):
            self.bench.prepare(candidate_id=candidate["id"])

    def test_light_coverage_allows_validation_without_upgrading_off_cases(self):
        _, candidate = self.candidate(modes=("light", "light", "light", "light", "off", "off"),
                                      preferences=[("intensity", "soften"), ("rhetoric", "reduce"), ("address", "minimal")])
        prepared = self.bench.prepare(candidate_id=candidate["id"])
        report = self.complete_personal(prepared, {"holdout-1"})
        self.assertTrue(report["passed"])
        self.assertTrue(report["coverage_complete"])
        for key in ("intensity", "rhetoric", "address"):
            self.assertEqual(report["preference_coverage"][key], ["holdout-1"])
        self.assertEqual([row["deai"] for row in report["details"][:3]], ["light", "off", "off"])
        self.assertTrue(self.learning.activate(candidate["id"], "local")["changed"])

    def test_same_host_unchanged_deai_preference_keeps_existing_validation(self):
        active = self.store.save("candidate", "local", "general", {
            "preferences": [{"key": "tone", "value": "formal"}, {"key": "address", "value": "minimal"}],
            "holdout_ids": [], "dataset_ids": [], "fingerprint": fingerprint(),
            "report": {"host": "unknown", "fingerprint": fingerprint()}})
        self.store.set_profile("local", "general", active["id"], [])
        _, candidate = self.candidate(modes=("off",) * 6,
                                      preferences=[("tone", "neutral"), ("address", "minimal")])
        report = self.complete_personal(self.bench.prepare(candidate_id=candidate["id"]), {"holdout-1"})
        self.assertTrue(report["passed"])
        self.assertEqual(report["changed_preference_keys"], ["tone"])
        self.assertTrue(self.learning.activate(candidate["id"], "local")["changed"])

    def test_new_host_cannot_retain_deai_preference_without_enabled_coverage(self):
        active = self.store.save("candidate", "local", "general", {
            "preferences": [{"key": "tone", "value": "formal"}, {"key": "address", "value": "minimal"}],
            "holdout_ids": [], "dataset_ids": [], "fingerprint": fingerprint(),
            "report": {"host": "old-host", "fingerprint": fingerprint()}})
        self.store.set_profile("local", "general", active["id"], [])
        _, candidate = self.candidate(modes=("off",) * 6,
                                      preferences=[("tone", "neutral"), ("address", "minimal")])
        previous_runs = len(self.store.list("run", "local"))
        with self.assertRaisesRegex(ValueError, "address"):
            self.bench.prepare(candidate_id=candidate["id"], host="new-host")
        self.assertEqual(self.store.list("benchmark", "local"), [])
        self.assertEqual(len(self.store.list("run", "local")), previous_runs)
        self.assertEqual(self.store.get(candidate["id"], "candidate")["status"], "pending")

    def test_new_host_validates_retained_preferences_against_generic_baseline(self):
        active = self.store.save("candidate", "local", "general", {
            "preferences": [{"key": "tone", "value": "formal"}, {"key": "address", "value": "minimal"}],
            "holdout_ids": [], "dataset_ids": [], "fingerprint": fingerprint(),
            "report": {"host": "old-host", "fingerprint": fingerprint()}})
        self.store.set_profile("local", "general", active["id"], [])
        _, candidate = self.candidate(modes=("light", "light", "light", "light", "off", "off"),
                                      preferences=[("tone", "neutral"), ("address", "minimal")])
        prepared = self.bench.prepare(candidate_id=candidate["id"], host="new-host")
        bench = self.store.get(prepared["id"], "benchmark")
        self.assertTrue(all(self.store.get(case["baseline_run"], "run")["preferences"] == []
                            for case in bench["cases"]))
        report = self.complete_personal(prepared, {"holdout-1"})
        self.assertTrue(report["passed"])
        self.assertEqual(report["changed_preference_keys"], ["address", "tone"])
        self.assertEqual(report["preference_coverage"]["address"], ["holdout-1"])
        self.assertTrue(self.learning.activate(candidate["id"], "local")["changed"])

    def test_new_host_can_drop_inactive_old_host_preference(self):
        active = self.store.save("candidate", "local", "general", {
            "preferences": [{"key": "tone", "value": "formal"}, {"key": "address", "value": "minimal"}],
            "holdout_ids": [], "dataset_ids": [], "fingerprint": fingerprint(),
            "report": {"host": "old-host", "fingerprint": fingerprint()}})
        self.store.set_profile("local", "general", active["id"], [])
        _, candidate = self.candidate(modes=("off",) * 6, preferences=[("tone", "neutral")])
        prepared = self.bench.prepare(candidate_id=candidate["id"], host="new-host")
        report = self.complete_personal(prepared, {"holdout-1"})
        self.assertTrue(report["passed"])
        self.assertEqual(report["changed_preference_keys"], ["tone"])
        self.assertTrue(self.learning.activate(candidate["id"], "local")["changed"])

    def test_strong_coverage_can_validate_new_preference(self):
        _, candidate = self.candidate(modes=("strong",) * 6, preferences=[("rhetoric", "reduce")])
        prepared = self.bench.prepare(candidate_id=candidate["id"])
        report = self.complete_personal(prepared, {"holdout-2"})
        self.assertTrue(report["passed"])
        self.assertEqual(report["preference_coverage"]["rhetoric"], ["holdout-1", "holdout-2", "holdout-3"])
        self.assertTrue(self.learning.activate(candidate["id"], "local")["changed"])

    def test_stale_candidate_or_report_fingerprint_suspends_active_preferences(self):
        current = fingerprint()
        for candidate_fp, report_fp in (("previous-rules", current), (current, "previous-rules"),
                                        (current, None)):
            with self.subTest(candidate_fp=candidate_fp, report_fp=report_fp):
                active = self.store.save("candidate", "local", "general", {
                    "preferences": [{"key": "tone", "value": "formal"},
                                    {"key": "address", "value": "minimal"}],
                    "fingerprint": candidate_fp,
                    "report": {"host": "unknown", "fingerprint": report_fp}})
                self.store.set_profile("local", "general", active["id"], [])
                run = self.engine.start("方案仍在讨论。", deai="light")
                self.assertEqual(run["preferences"], [])
                self.assertIsNone(run["profile_id"])
                self.assertIn("规则版本", run["profile_warning"])
                self.assertEqual(self.store.active("local", "general"), active)

    def test_rule_upgrade_cannot_retain_uncovered_same_value_deai_preference(self):
        active = self.store.save("candidate", "local", "general", {
            "preferences": [{"key": "tone", "value": "formal"}, {"key": "address", "value": "minimal"}],
            "holdout_ids": [], "dataset_ids": [], "fingerprint": "previous-rules",
            "report": {"host": "unknown", "fingerprint": "previous-rules"}})
        self.store.set_profile("local", "general", active["id"], [])
        _, candidate = self.candidate(modes=("off",) * 6,
                                      preferences=[("tone", "formal"), ("address", "minimal")])
        previous_runs = len(self.store.list("run", "local"))
        with self.assertRaisesRegex(ValueError, "address"):
            self.bench.prepare(candidate_id=candidate["id"])
        self.assertEqual(self.store.list("benchmark", "local"), [])
        self.assertEqual(len(self.store.list("run", "local")), previous_runs)
        self.assertEqual(self.store.get(candidate["id"], "candidate")["status"], "pending")

    def test_rule_upgrade_revalidates_same_values_against_generic_baseline(self):
        active = self.store.save("candidate", "local", "general", {
            "preferences": [{"key": "tone", "value": "formal"}, {"key": "address", "value": "minimal"}],
            "holdout_ids": [], "dataset_ids": [], "fingerprint": "previous-rules",
            "report": {"host": "unknown", "fingerprint": "previous-rules"}})
        self.store.set_profile("local", "general", active["id"], [])
        _, candidate = self.candidate(modes=("light",) * 6,
                                      preferences=[("tone", "formal"), ("address", "minimal")])
        prepared = self.bench.prepare(candidate_id=candidate["id"])
        bench = self.store.get(prepared["id"], "benchmark")
        self.assertTrue(all(self.store.get(case["baseline_run"], "run")["preferences"] == []
                            for case in bench["cases"]))
        report = self.complete_personal(prepared, {"holdout-1"})
        self.assertTrue(report["passed"])
        self.assertEqual(report["changed_preference_keys"], ["address", "tone"])
        self.assertEqual(report["preference_coverage"]["address"], ["holdout-1", "holdout-2", "holdout-3"])
        self.assertTrue(self.learning.activate(candidate["id"], "local")["changed"])
        resumed = self.engine.start("新方案仍在讨论。", deai="light")
        self.assertEqual(resumed["preferences"], candidate["preferences"])
        self.assertIsNone(resumed["profile_warning"])

    def test_random_difference_with_identical_effective_preferences_never_counts_as_gain(self):
        _, candidate = self.candidate(modes=("light", "light", "light", "light", "off", "off"),
                                      preferences=[("address", "minimal")])
        prepared = self.bench.prepare(candidate_id=candidate["id"])
        report = self.complete_personal(prepared, {"holdout-2"})
        self.assertTrue(report["coverage_complete"])
        self.assertFalse(report["passed"])
        self.assertFalse(report["eligible_with_self_review"])
        self.assertEqual(report["wins"], 0)
        detail = next(row for row in report["details"] if row["case_id"] == "holdout-2")
        self.assertFalse(detail["identical_outputs"])
        self.assertTrue(detail["identical_effective_preferences"])
        self.assertEqual(detail["winner"], "tie")
        with self.assertRaises(ValueError):
            self.learning.activate(candidate["id"], "local", True)

    def test_ordinary_preference_still_validates_in_off_mode(self):
        _, candidate = self.candidate(modes=("off",) * 6, preferences=[("tone", "neutral")])
        report = self.complete_personal(self.bench.prepare(candidate_id=candidate["id"]), {"holdout-1"})
        self.assertTrue(report["passed"])
        self.assertTrue(report["preference_coverage"]["tone"])
        self.assertTrue(self.learning.activate(candidate["id"], "local")["changed"])

    def test_activation_cannot_bypass_missing_coverage_even_with_override(self):
        _, candidate = self.candidate(modes=("off",) * 6, preferences=[("tone", "neutral")])
        self.complete_personal(self.bench.prepare(candidate_id=candidate["id"]), {"holdout-1"})
        stored = self.store.get(candidate["id"], "candidate")
        stored["report"]["preference_coverage"]["tone"] = []
        self.store.update(stored, "candidate")
        with self.assertRaisesRegex(ValueError, "验证覆盖"):
            self.learning.activate(candidate["id"], "local", True)

    def test_cli_rejects_invalid_mode_and_incompatible_case_flags(self):
        source = Path(self.temp.name) / "source.txt"
        source.write_text("方案仍在讨论。", encoding="utf-8")
        cmd = [sys.executable, "-I", str(ROOT / "scripts/agent.py"), "--data-dir", str(Path(self.temp.name) / "cli")]
        arguments = [
            ["start", "--text-file", str(source), "--deai", "medium"],
            ["benchmark", "--mode", "offline", "--case", "anything"],
            ["benchmark", "--mode", "report", "--id", "anything", "--case", "anything"],
            ["benchmark", "--mode", "prepare", "--case", "anything", "--limit", "1"],
        ]
        for args in arguments:
            result = subprocess.run(cmd + args, capture_output=True, text=True, cwd=self.temp.name)
            self.assertEqual(result.returncode, 2, result.stdout)
        result = subprocess.run(cmd + ["start", "--text-file", str(source), "--deai", "light"],
                                capture_output=True, text=True, cwd=self.temp.name)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["task"]["deai"], "light")


if __name__ == "__main__":
    unittest.main()
