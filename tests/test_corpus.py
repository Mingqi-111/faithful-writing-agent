"""Research provenance/inventory checks, not authorship or writing-quality tests."""
import json
from pathlib import Path
import unittest
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "evidence/corpus"


def read_rows(name):
    return [json.loads(line) for line in (CORPUS / name).read_text(encoding="utf-8").splitlines() if line.strip()]


class CorpusInventoryTests(unittest.TestCase):
    def test_media_inventory_has_traceable_personal_bylines(self):
        rows = read_rows("media-sources.jsonl")
        self.assertEqual(len(rows), 100)
        for field in ("id", "url", "text_sha256"):
            self.assertEqual(len({r[field] for r in rows}), 100)
        for row in rows:
            with self.subTest(id=row["id"]):
                self.assertTrue(row["title"] and row["byline"] and row["original_analysis"])
                self.assertIn(urlparse(row["url"]).hostname, {"paper.people.com.cn", "www.news.cn", "www.xinhuanet.com"})
                self.assertRegex(row["published"], r"^20\d\d-\d\d-\d\d$")
                self.assertEqual(row["evidence_of_byline"]["role"], "正文作者/文字记者")
                self.assertTrue(row["evidence_of_byline"]["verified_visible_substring"])
                self.assertEqual(row["verification"]["ai_use_status"], "unknown")
                self.assertFalse(row["verification"]["human_manual_review"])
                self.assertFalse(row["source_body_in_public_manifest"])
                self.assertRegex(row["text_sha256"], r"^[a-f0-9]{64}$")

    def test_media_statistics_disclose_actual_review_scope(self):
        rows = read_rows("media-sources.jsonl")
        stats = json.loads((CORPUS / "media-statistics.json").read_text())
        self.assertEqual(stats["selected_articles"], len(rows))
        self.assertEqual(sum(stats["counts_by_genre"].values()), len(rows))
        self.assertEqual(stats["review"]["human_manual_review"], 0)
        self.assertEqual(stats["review"]["model_full_text_read"], len(stats["review"]["full_text_ids"]))
        self.assertTrue(set(stats["review"]["full_text_ids"]) <= {r["id"] for r in rows})
        self.assertLess(stats["review"]["model_full_text_read"], len(rows))

    def test_problem_and_control_selection_preserves_all_reviewed_records(self):
        all_rows = read_rows("ai/all_reviewed_manifest.jsonl")
        problems = read_rows("ai/problem_manifest.jsonl")
        controls = read_rows("ai/control_manifest.jsonl")
        self.assertEqual((len(all_rows), len(problems), len(controls)), (85, 50, 7))
        by_id = {r["id"]: r for r in all_rows}
        self.assertEqual(len(by_id), len(all_rows))
        self.assertFalse({r["id"] for r in problems} & {r["id"] for r in controls})
        for subset, verdict in ((problems, "obvious_editable_pattern"), (controls, "no_obvious_template_problem")):
            for row in subset:
                self.assertEqual(row, by_id[row["id"]])
                self.assertEqual(row["review"]["verdict"], verdict)

    def test_ai_provenance_and_annotations_are_not_claimed_as_human_gold(self):
        rows = read_rows("ai/all_reviewed_manifest.jsonl")
        self.assertGreaterEqual(len({r["model"] for r in rows}), 5)
        self.assertEqual(len({r["source_text_sha256"] for r in rows}), len(rows))
        self.assertEqual(len({(r["domain"], r["original_id"]) for r in rows}), len(rows))
        for row in rows:
            self.assertRegex(row["commit"], r"^[a-f0-9]{40}$")
            for key in ("source_file_sha256", "source_text_sha256"):
                self.assertRegex(row[key], r"^[a-f0-9]{64}$")
            self.assertIn("/blob/" + row["commit"] + "/", row["source_url"])
            self.assertGreaterEqual(row["source_csv_record_1based_including_header"], 2)
            self.assertEqual(row["publisher_label"], "0")
            self.assertEqual(row["publisher_attribution"], row["model"])
            self.assertEqual(row["generation_provenance"], "publisher_labeled_ai_not_independently_verified")
            self.assertEqual(row["review"]["reviewer_kind"], "model_agent")
            self.assertFalse(row["review"]["human_reviewed"])
            self.assertFalse(row["review"]["ai_detection_claim"])
            self.assertEqual(row["review"]["read_scope"], "full_text_and_generation_prompt")

    def test_rules_map_to_existing_sources_and_original_benchmark_cases(self):
        sources = {r["id"] for name in ("media-sources.jsonl", "ai/all_reviewed_manifest.jsonl") for r in read_rows(name)}
        cases = {r["id"]: r for r in [json.loads(l) for l in (ROOT / "benchmarks/agent_cases.jsonl").read_text().splitlines()]}
        mapping = json.loads((CORPUS / "rule-map.json").read_text())
        self.assertEqual(len(mapping), 9)
        self.assertEqual(len({r["case_id"] for r in mapping}), len(mapping))
        for row in mapping:
            self.assertIn(row["case_id"], cases)
            self.assertIs(cases[row["case_id"]]["synthetic"], True)
            self.assertTrue(set(row["source_ids"]) <= sources)
            self.assertTrue(row["source_ids"] or row["basis"] == "out_of_domain_boundary")
            self.assertTrue(row["reason"])

    def test_public_manifests_exclude_article_bodies_and_private_paths(self):
        forbidden = {"private_text", "private_source_record", "body_text", "paragraphs", "prompt", "html", "full_text"}
        def visit(value):
            if isinstance(value, dict):
                self.assertFalse(forbidden & value.keys())
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)
            elif isinstance(value, str):
                self.assertNotIn("/Users/", value)
                self.assertNotIn("scratch-workspaces/", value)
        for name in ("media-sources.jsonl", "ai/problem_manifest.jsonl", "ai/control_manifest.jsonl", "ai/all_reviewed_manifest.jsonl"):
            visit(read_rows(name))


if __name__ == "__main__":
    unittest.main()
