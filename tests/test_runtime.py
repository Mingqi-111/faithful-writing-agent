"""Runtime contract tests with simulated host submissions, not model-quality scores."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from runtime.benchmark import Benchmark, offline
from runtime.engine import Engine, GOOD, fingerprint
from runtime.learning import Learning
from runtime.store import Store


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "state")
        self.engine, self.learning, self.bench = Engine(self.store), Learning(self.store), Benchmark(self.store)

    def tearDown(self):
        self.store.finish()
        self.temp.cleanup()

    def review_value(self, run_id, *, mode="independent", passed=True):
        task = self.engine.show(run_id)["task"]
        return {"run_id": run_id, "draft_sha256": task["draft_sha256"],
                "fidelity_pass": passed, "scene_pass": True, "needs_revision": not passed,
                "naturalness": 4, "issues": [], "review_mode": mode, "reviewer": "test-context"}

    def complete(self, source, output=None, mode="independent", scene="general", host="test-host"):
        run = self.engine.start(source, scene, host=host)
        self.engine.draft(run["id"], source if output is None else output)
        return self.engine.review(run["id"], self.review_value(run["id"], mode=mode))

    def feedbacks(self, count=6, start=0):
        rows = []
        for i in range(start, start + count):
            source = f"项目{i}的方案还在讨论，暂时没有确定。"
            run = self.complete(source)
            rows.append(self.engine.feedback(run["id"], f"项目{i}还在讨论方案，目前没有定论。", "edited"))
        return rows

    def candidate(self, learning_mode="independent", value="neutral"):
        batch = self.learning.learn("local", "general", learning_mode)
        return self.learning.propose("local", "general", {"batch_id": batch["batch_id"], "preferences": [
            {"key": "tone", "value": value, "evidence_ids": [row["id"] for row in batch["task"]["training_feedback"][:3]],
             "reason": "测试仅模拟宿主已提取的三条证据。"}]})

    def prepare_completed(self, candidate, *, mode="independent", identical=False):
        prepared = self.bench.prepare(candidate_id=candidate["id"], host="test-host")
        bench = self.store.get(prepared["id"], "benchmark")
        for case in bench["cases"]:
            for label in ("baseline", "candidate"):
                run_id = case[f"{label}_run"]
                source = self.store.get(run_id, "run")["source"]
                # Simulated outputs differ by punctuation; this fixture exercises
                # gate mechanics and makes no claim that a real judge would prefer one.
                output = source if label == "baseline" or identical else source.replace("。", "；", 1)
                self.engine.draft(run_id, output)
                self.engine.review(run_id, self.review_value(run_id, mode=mode))
        report = self.bench.report(prepared["id"])
        return bench, report

    def compare_value(self, bench, *, mode="independent", winner="candidate"):
        return {"benchmark_id": bench["id"], "comparisons": [
            {"case_id": case["id"], "a_pass": True, "b_pass": True,
             "winner": "tie" if winner == "tie" else case["candidate_side"] if winner == "candidate" else
                       "B" if case["candidate_side"] == "A" else "A",
             "reason": "模拟比较结果，仅用于检查门控。", "review_mode": mode, "reviewer": "test-blind-context"}
            for case in bench["cases"]]}

    def passed_candidate(self, value="neutral"):
        candidate = self.candidate(value=value)
        bench, _ = self.prepare_completed(candidate)
        report = self.bench.submit_comparisons(bench["id"], self.compare_value(bench))
        self.assertTrue(report["passed"])
        return candidate

    def test_ordinary_rewrite_needs_both_draft_and_review(self):
        run = self.engine.start("方案可能有帮助，但尚未验证。")
        self.assertEqual(run["status"], "awaiting_draft")
        draft = self.engine.draft(run["id"], "这份方案可能有用，目前还没有验证。")
        self.assertEqual(draft["status"], "awaiting_review")
        self.assertIsNone(draft["output"])
        result = self.engine.review(run["id"], self.review_value(run["id"]))
        self.assertIn(result["status"], GOOD)

    def test_semantic_failure_is_not_overridden_by_clean_static_check(self):
        run = self.engine.start("这项调整可能有效，但尚未验证。")
        self.engine.draft(run["id"], "这项调整一定有效，已经验证。")
        result = self.engine.review(run["id"], self.review_value(run["id"], passed=False))
        self.assertEqual(result["status"], "needs_revision")
        self.assertIsNone(result["output"])

    def test_static_hard_error_cannot_be_overridden_and_three_rounds_fallback(self):
        run = self.engine.start("价格是100元。")
        for attempt in range(1, 4):
            self.engine.draft(run["id"], "价格是200元。")
            result = self.engine.review(run["id"], self.review_value(run["id"]))
            self.assertEqual(result["attempts"], attempt)
        self.assertEqual(result["status"], "fallback")
        self.assertEqual(result["output"], "价格是100元。")
        with self.assertRaises(ValueError):
            self.engine.draft(run["id"], "价格是100元。")

    def test_review_cannot_skip_draft(self):
        run = self.engine.start("保留这段。")
        with self.assertRaises(ValueError):
            self.engine.review(run["id"], {"fidelity_pass": True})
        self.assertEqual(self.engine.show(run["id"])["status"], "awaiting_draft")

    def test_empty_draft_does_not_consume_attempt(self):
        run = self.engine.start("保留这段。")
        with self.assertRaises(ValueError):
            self.engine.draft(run["id"], " \n")
        self.assertEqual(self.engine.show(run["id"])["attempts"], 0)

    def test_completed_run_is_immutable(self):
        run = self.complete("方案还在讨论。")
        with self.assertRaises(ValueError):
            self.engine.draft(run["id"], "方案已经确定。")
        self.assertEqual(self.engine.show(run["id"])["output"], run["output"])

    def test_review_bound_to_current_draft_and_run(self):
        run = self.engine.start("方案还在讨论。")
        self.engine.draft(run["id"], "方案目前仍在讨论。")
        value = self.review_value(run["id"])
        for field in ("run_id", "draft_sha256"):
            bad = dict(value, **{field: "wrong"})
            with self.assertRaises(ValueError):
                self.engine.review(run["id"], bad)
        self.assertEqual(self.engine.show(run["id"])["status"], "awaiting_review")

    def test_strict_review_schema_rejects_missing_extra_and_wrong_types(self):
        run = self.engine.start("方案还在讨论。")
        self.engine.draft(run["id"], "方案目前仍在讨论。")
        base = self.review_value(run["id"])
        cases = [dict(base, extra=True), dict(base, fidelity_pass="true"), dict(base, naturalness=True),
                 dict(base, naturalness=6), dict(base, reviewer=""), dict(base, review_mode=[])]
        missing = dict(base)
        del missing["issues"]
        cases.append(missing)
        for value in cases:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.engine.review(run["id"], value)

    def test_self_review_label_is_retained(self):
        run = self.complete("目前还没有定论。", mode="self_review")
        self.assertEqual(run["review_mode"], "self_review")
        self.assertIn("不证明", run["review_claim"])

    def test_oversized_input_and_unknown_scene_rejected(self):
        with self.assertRaises(ValueError):
            self.engine.start("文" * 16001)
        with self.assertRaises(ValueError):
            self.engine.start("文章", "unknown-scene")

    def test_user_isolation_on_read_and_feedback(self):
        run = self.complete("这段还在讨论。")
        with self.assertRaises(ValueError):
            self.engine.show(run["id"], "other")
        with self.assertRaises(ValueError):
            self.engine.feedback(run["id"], run["output"], "accepted", user_id="other")
        self.assertEqual(self.learning.profile("other", "general")["feedback_count"], 0)

    def test_feedback_deduplicated_and_rating_consistent(self):
        run = self.complete("目前没有定论。")
        with self.assertRaises(ValueError):
            self.engine.feedback(run["id"], "已经确定。", "accepted")
        with self.assertRaises(ValueError):
            self.engine.feedback(run["id"], run["output"], "edited")
        self.engine.feedback(run["id"], run["output"], "accepted")
        with self.assertRaises(ValueError):
            self.engine.feedback(run["id"], run["output"], "accepted")

    def test_rejected_and_duplicate_sources_do_not_satisfy_learning_gate(self):
        for i in range(7):
            run = self.complete("同一篇原文。")
            self.engine.feedback(run["id"], run["output"], "accepted" if i < 6 else "rejected")
        self.assertEqual(self.learning.profile("local", "general")["feedback_count"], 1)
        with self.assertRaises(ValueError):
            self.learning.learn("local", "general")

    def test_scene_feedback_isolated(self):
        self.feedbacks()
        with self.assertRaises(ValueError):
            self.learning.learn("local", "douyin-tech")

    def test_learning_hides_last_three_final_texts_and_freezes_split(self):
        self.feedbacks()
        response = self.learning.learn("local", "general")
        batch = self.store.get(response["batch_id"], "batch")
        self.assertEqual(len(response["task"]["training_feedback"]), 3)
        serialized = json.dumps(response, ensure_ascii=False)
        for i in range(3, 6):
            self.assertNotIn(f"项目{i}还在讨论方案", serialized)
        self.feedbacks(1, start=6)
        self.assertEqual(batch["train_ids"], self.store.get(response["batch_id"], "batch")["train_ids"])
        self.assertEqual(response["learning_mode"], "same_context")

    def test_proposal_rejects_unsupported_values_and_holdout_evidence(self):
        self.feedbacks()
        batch = self.learning.learn("local", "general")
        stored = self.store.get(batch["batch_id"], "batch")
        pref = {"key": "tone", "value": "neutral", "evidence_ids": stored["train_ids"], "reason": "重复编辑证据"}
        for change in ({"key": "facts"}, {"value": "invent"}, {"evidence_ids": stored["holdout_ids"]},
                       {"evidence_ids": [stored["train_ids"][0]] * 3}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.learning.propose("local", "general", {"batch_id": batch["batch_id"], "preferences": [dict(pref, **change)]})

    def test_new_candidate_cannot_activate_without_full_report(self):
        self.feedbacks()
        candidate = self.candidate()
        with self.assertRaises(ValueError):
            self.learning.activate(candidate["id"], "local", True)
        self.assertIsNone(self.store.active("local", "general"))

    def test_holdout_reuse_blocked_until_three_fresh_feedbacks(self):
        self.feedbacks()
        self.candidate()
        self.feedbacks(1, start=6)
        with self.assertRaisesRegex(ValueError, "2 篇"):
            self.learning.learn("local", "general")
        self.feedbacks(2, start=7)
        batch = self.learning.learn("local", "general")
        self.assertEqual(batch["holdout_count"], 3)

    def test_old_batch_cannot_reserve_same_holdout_twice(self):
        self.feedbacks()
        first = self.learning.learn("local", "general")
        self.candidate()
        pref = {"key": "tone", "value": "formal", "evidence_ids": [r["id"] for r in first["task"]["training_feedback"]], "reason": "理由"}
        with self.assertRaises(ValueError):
            self.learning.propose("local", "general", {"batch_id": first["batch_id"], "preferences": [pref]})

    def test_personal_benchmark_cannot_be_shortened_or_restarted(self):
        self.feedbacks()
        candidate = self.candidate()
        with self.assertRaises(ValueError):
            self.bench.prepare(candidate_id=candidate["id"], limit=1)
        prepared = self.bench.prepare(candidate_id=candidate["id"])
        self.assertEqual(prepared["total_cases"], 5)
        self.assertEqual(prepared["total_runs"], 10)
        with self.assertRaises(ValueError):
            self.bench.prepare(candidate_id=candidate["id"])

    def test_incomplete_benchmark_cannot_pass_or_accept_comparisons(self):
        self.feedbacks()
        candidate = self.candidate()
        prepared = self.bench.prepare(candidate_id=candidate["id"])
        report = self.bench.report(prepared["id"])
        self.assertFalse(report["passed"])
        self.assertEqual(report["completed_runs"], 0)
        with self.assertRaises(ValueError):
            self.bench.submit_comparisons(prepared["id"], {"benchmark_id": prepared["id"], "comparisons": []})
        with self.assertRaises(ValueError):
            self.learning.activate(candidate["id"], "local", True)

    def test_benchmark_runs_cannot_become_user_feedback(self):
        prepared = self.bench.prepare(limit=1)
        run_id = prepared["tasks"][0]["run_id"]
        source = self.engine.show(run_id)["source"]
        self.engine.draft(run_id, source)
        self.engine.review(run_id, self.review_value(run_id))
        with self.assertRaises(ValueError):
            self.engine.feedback(run_id, source, "accepted")

    def test_comparison_packets_hide_identities_and_reference_is_withheld_until_then(self):
        self.feedbacks()
        candidate = self.candidate()
        bench, report = self.prepare_completed(candidate)
        self.assertEqual(report["status"], "awaiting_comparison")
        for task in report["tasks"]:
            self.assertNotIn("candidate_side", task)
            self.assertNotIn("baseline_run", task)
            self.assertNotIn("candidate_run", task)
        held = [r for r in report["tasks"] if r["case_id"].startswith("holdout")]
        self.assertTrue(all(r["reference"] for r in held))

    def test_missing_comparison_cannot_pass(self):
        self.feedbacks()
        candidate = self.candidate()
        bench, _ = self.prepare_completed(candidate)
        value = self.compare_value(bench)
        value["comparisons"].pop()
        with self.assertRaises(ValueError):
            self.bench.submit_comparisons(bench["id"], value)

    def test_duplicate_and_unknown_comparison_cases_rejected(self):
        self.feedbacks()
        candidate = self.candidate()
        bench, _ = self.prepare_completed(candidate)
        for replacement in (bench["cases"][0]["id"], "unknown-case"):
            value = self.compare_value(bench)
            value["comparisons"][1]["case_id"] = replacement
            with self.subTest(replacement=replacement), self.assertRaises(ValueError):
                self.bench.submit_comparisons(bench["id"], value)

    def test_identical_outputs_force_tie_and_cannot_show_improvement(self):
        self.feedbacks()
        candidate = self.candidate()
        bench, _ = self.prepare_completed(candidate, identical=True)
        report = self.bench.submit_comparisons(bench["id"], self.compare_value(bench))
        self.assertFalse(report["passed"])
        self.assertEqual(report["wins"], 0)
        with self.assertRaises(ValueError):
            self.learning.activate(candidate["id"], "local", True)

    def test_one_comparison_content_failure_blocks_activation(self):
        self.feedbacks()
        candidate = self.candidate()
        bench, _ = self.prepare_completed(candidate)
        value = self.compare_value(bench)
        value["comparisons"][0]["a_pass"] = False
        report = self.bench.submit_comparisons(bench["id"], value)
        self.assertFalse(report["passed"])
        with self.assertRaises(ValueError):
            self.learning.activate(candidate["id"], "local", True)

    def test_any_candidate_loss_blocks_activation(self):
        self.feedbacks()
        candidate = self.candidate()
        bench, _ = self.prepare_completed(candidate)
        value = self.compare_value(bench)
        value["comparisons"][0]["winner"] = "A" if bench["cases"][0]["candidate_side"] == "B" else "B"
        report = self.bench.submit_comparisons(bench["id"], value)
        self.assertFalse(report["passed"])
        self.assertEqual(report["losses"], 1)

    def test_self_review_requires_explicit_override(self):
        self.feedbacks()
        candidate = self.candidate()
        bench, _ = self.prepare_completed(candidate, mode="self_review")
        report = self.bench.submit_comparisons(bench["id"], self.compare_value(bench))
        self.assertFalse(report["passed"])
        self.assertTrue(report["eligible_with_self_review"])
        with self.assertRaises(ValueError):
            self.learning.activate(candidate["id"], "local")
        activation = self.learning.activate(candidate["id"], "local", True)
        self.assertTrue(activation["self_review_override"])

    def test_same_context_learning_downgrades_even_independent_comparisons(self):
        self.feedbacks()
        candidate = self.candidate(learning_mode="same_context")
        bench, _ = self.prepare_completed(candidate)
        report = self.bench.submit_comparisons(bench["id"], self.compare_value(bench))
        self.assertFalse(report["passed"])
        self.assertTrue(report["eligible_with_self_review"])
        self.assertEqual(report["learning_mode"], "same_context")

    def test_successful_activation_and_host_mismatch_suspends_preferences(self):
        self.feedbacks()
        candidate = self.passed_candidate()
        self.learning.activate(candidate["id"], "local")
        same = self.engine.start("方案还在讨论。", host="test-host")
        other = self.engine.start("方案还在讨论。", host="different-host")
        self.assertTrue(same["preferences"])
        self.assertEqual(other["preferences"], [])
        self.assertIsNotNone(other["profile_warning"])

    def test_equivalent_preference_candidate_rejected(self):
        self.feedbacks()
        candidate = self.passed_candidate()
        self.learning.activate(candidate["id"], "local")
        self.feedbacks(3, start=6)
        with self.assertRaisesRegex(ValueError, "相同"):
            self.candidate()

    def test_rollback_multiple_versions_to_initial_profile(self):
        self.feedbacks()
        first = self.passed_candidate()
        self.learning.activate(first["id"], "local")
        self.feedbacks(3, start=6)
        second = self.passed_candidate(value="formal")
        self.learning.activate(second["id"], "local")
        result = self.learning.rollback("local", "general")
        self.assertEqual(result["active"]["id"], first["id"])
        self.assertIsNone(self.learning.rollback("local", "general")["active"])
        with self.assertRaises(ValueError):
            self.learning.rollback("local", "general")

    def test_changed_version_blocks_report_and_activation(self):
        self.feedbacks()
        candidate = self.passed_candidate()
        with patch("runtime.learning.fingerprint", return_value="changed"):
            with self.assertRaises(ValueError):
                self.learning.activate(candidate["id"], "local")

    def test_changing_active_base_invalidates_other_previously_passed_candidate(self):
        self.feedbacks()
        first = self.passed_candidate()
        self.feedbacks(3, start=6)
        second = self.passed_candidate(value="formal")
        self.learning.activate(first["id"], "local")
        with self.assertRaises(ValueError):
            self.learning.activate(second["id"], "local")
        self.assertEqual(self.store.active("local", "general")["id"], first["id"])

    def test_rule_reference_changes_alter_fingerprint(self):
        actual = fingerprint()
        target = ROOT / "references/review.md"
        original = Path.read_bytes
        def changed(path):
            return original(path) + b"changed" if path == target else original(path)
        with patch.object(Path, "read_bytes", changed):
            self.assertNotEqual(fingerprint(), actual)

    def test_offline_benchmark_is_checkers_only_and_all_cases_pass(self):
        report = offline()
        self.assertEqual(report["mode"], "offline-checker-regression")
        self.assertEqual(report["total"], 40)
        self.assertEqual(report["failed"], 0)
        self.assertEqual(sum(r["semantic_review_required"] for r in report["details"]), 4)

    def test_cli_bad_json_is_atomic_and_state_path_is_portable(self):
        directory = Path(self.temp.name) / "cli-state"
        source = Path(self.temp.name) / "original.txt"
        source.write_text("原文保持不变。", encoding="utf-8")
        cmd = [sys.executable, str(ROOT / "scripts/agent.py"), "--data-dir", str(directory)]
        created = subprocess.run(cmd + ["start", "--text-file", str(source)], capture_output=True, text=True, check=True)
        result = json.loads(created.stdout)
        self.assertEqual(result["state_path"], str(directory.resolve() / "state.sqlite3"))
        bad = Path(self.temp.name) / "bad.json"
        bad.write_text('{"fidelity_pass":true,"fidelity_pass":false}', encoding="utf-8")
        rejected = subprocess.run(cmd + ["review", "--run", result["id"], "--json-file", str(bad)], capture_output=True, text=True)
        self.assertEqual(rejected.returncode, 2)
        self.assertFalse(json.loads(rejected.stdout)["changed"])
        inspected = subprocess.run(cmd + ["show", "--run", result["id"]], capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(inspected.stdout)["status"], "awaiting_draft")
        self.assertFalse((directory / "state.sqlite3-wal").exists())

    def test_concurrent_feedback_submissions_are_serialized_and_deduplicated(self):
        directory = Path(self.temp.name) / "concurrent"
        with tempfile.TemporaryDirectory() as working:
            source_file = Path(working) / "source.txt"
            source_file.write_text("原文保持不变。", encoding="utf-8")
            cmd = [sys.executable, str(ROOT / "scripts/agent.py"), "--data-dir", str(directory)]
            def invoke(args):
                return subprocess.run(cmd + args, capture_output=True, text=True)
            started = json.loads(invoke(["start", "--text-file", str(source_file)]).stdout)
            drafted = json.loads(invoke(["draft", "--run", started["id"], "--text-file", str(source_file)]).stdout)
            review = {"run_id": started["id"], "draft_sha256": drafted["task"]["draft_sha256"],
                      "fidelity_pass": True, "scene_pass": True, "needs_revision": False, "naturalness": 4,
                      "issues": [], "review_mode": "self_review", "reviewer": "test-context"}
            review_file = Path(working) / "review.json"
            review_file.write_text(json.dumps(review), encoding="utf-8")
            self.assertEqual(invoke(["review", "--run", started["id"], "--json-file", str(review_file)]).returncode, 0)
            args = ["feedback", "--run", started["id"], "--final-file", str(source_file), "--rating", "accepted"]
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(invoke, [args, args]))
            self.assertEqual(sorted(result.returncode for result in results), [0, 2])
            profile = json.loads(invoke(["profile"]).stdout)
            self.assertEqual(profile["feedback_count"], 1)


if __name__ == "__main__":
    unittest.main()
