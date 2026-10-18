"""Validate public benchmark data; these checks do not grade model rewrites."""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from runtime.evaluators import scan_style


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def cases():
    return [json.loads(line, object_pairs_hook=unique_object)
            for line in (ROOT / "benchmarks/agent_cases.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()]


class BenchmarkDataTests(unittest.TestCase):
    def test_case_schema_and_unique_ids(self):
        rows = cases()
        scenes = json.loads((ROOT / "references/scenes.json").read_text(encoding="utf-8"))
        legacy_scenes = json.loads((ROOT / "references/legacy-scenes.json").read_text(encoding="utf-8"))
        self.assertFalse(scenes.keys() & legacy_scenes.keys())
        self.assertTrue(rows)
        self.assertEqual(len(rows), len({row["id"] for row in rows}))
        required = {"id", "scene", "source", "must_preserve", "must_not_add"}
        allowed = required | {"style_goals", "deai", "synthetic"}
        for row in rows:
            with self.subTest(case=row["id"]):
                self.assertTrue(required <= row.keys())
                self.assertTrue(row.keys() <= allowed)
                self.assertRegex(row["id"], r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
                self.assertIn(row["scene"], scenes.keys() | legacy_scenes.keys())
                self.assertIsInstance(row["source"], str)
                self.assertTrue(row["source"].strip())
                self.assertLessEqual(len(row["source"]), 16000)
                self.assertIn(row.get("deai", "off"), {"off", "light", "strong"})
                if "synthetic" in row:
                    self.assertIs(type(row["synthetic"]), bool)
                for field in ("must_preserve", "must_not_add", "style_goals"):
                    values = row.get(field, [])
                    self.assertIsInstance(values, list)
                    self.assertTrue(all(isinstance(x, str) and x.strip() for x in values))
                    self.assertEqual(len(values), len(set(values)))
                self.assertTrue(row["must_preserve"])
                self.assertTrue(row["must_not_add"])

    def test_constraints_do_not_request_and_forbid_the_same_item(self):
        for row in cases():
            with self.subTest(case=row["id"]):
                normalize = lambda text: re.sub(r"\s+", "", text).casefold()
                kept = {normalize(x) for x in row["must_preserve"]}
                forbidden = {normalize(x) for x in row["must_not_add"]}
                self.assertFalse(kept & forbidden)
        # This is a structural consistency check; a semantic reviewer still
        # needs to check that each constraint follows from its source.

    def test_same_source_mode_controls_keep_identical_content_constraints(self):
        groups = {}
        for row in cases():
            groups.setdefault(row["source"], []).append(row)
        mode_controls = [group for group in groups.values() if len(group) > 1]
        self.assertTrue(mode_controls, "Need same-source controls for mode comparison")
        for group in mode_controls:
            with self.subTest(ids=[row["id"] for row in group]):
                self.assertEqual({row.get("deai", "off") for row in group}, {"off", "light", "strong"})
                for row in group[1:]:
                    self.assertEqual(row["must_preserve"], group[0]["must_preserve"])
                    self.assertEqual(row["must_not_add"], group[0]["must_not_add"])
                    self.assertEqual(row["scene"], group[0]["scene"])
                self.assertEqual(len(group), len({row["deai"] for row in group}))

    def test_deai_examples_disclose_synthetic_origin(self):
        explicit_modes = [row for row in cases() if "deai" in row]
        self.assertTrue(explicit_modes)
        for row in explicit_modes:
            with self.subTest(case=row["id"]):
                self.assertIs(row.get("synthetic"), True)
                self.assertIn("原创合成", row["source"])
                self.assertTrue(any("原创合成" in item for item in row["must_preserve"]))
                self.assertTrue(row.get("style_goals"))

    def test_plain_information_negative_control_has_no_style_warning(self):
        negative = next(row for row in cases() if row["id"] == "deai-negative-control-001")
        self.assertEqual(negative["deai"], "strong")
        for mode in ("off", "light", "strong"):
            with self.subTest(mode=mode):
                self.assertEqual(scan_style(negative["source"], deai=mode), [])


if __name__ == "__main__":
    unittest.main()
