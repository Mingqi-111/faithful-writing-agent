"""Surface-form regression tests using original synthetic prose, not user drafts."""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from runtime.evaluators import compare_style, scan_style, style_counts


class StyleCheckTests(unittest.TestCase):
    def test_three_contrast_forms_are_detected_without_nested_double_counting(self):
        text = ("真正重要的根本不是排场，是内容。"
                "这次不是因为换了封面，而是资料终于齐全了。"
                "需要的不是热闹，是清楚的说明。")
        stats = style_counts(text)
        self.assertEqual(stats["counts"]["revelatory_contrast"], 3)
        warning = next(item for item in scan_style(text, "light") if item["code"] == "REPEATED_CONTRAST")
        self.assertEqual(warning["counts"]["revelatory_contrast"], 3)
        self.assertEqual(len(warning["evidence"]), 3)

    def test_two_contrasts_in_one_sentence_are_separate(self):
        text = "不是清单，是材料，不是承诺，而是进度。"
        self.assertEqual(style_counts(text)["counts"]["revelatory_contrast"], 2)

    def test_single_nested_contrast_is_one_candidate(self):
        text = "真正需要解释的根本不是名词，是费用。"
        self.assertEqual(style_counts(text)["counts"]["revelatory_contrast"], 1)
        self.assertNotIn("REPEATED_CONTRAST", {item["code"] for item in scan_style(text, "strong")})

    def test_intensifier_density_and_template_interaction_have_evidence(self):
        text = "我想跟你说，这个变化真的非常彻底。你应该还记得，今天我们来聊一下资料。"
        issues = {item["code"]: item for item in scan_style(text, "light")}
        self.assertIn("INTENSIFIER_DENSITY", issues)
        self.assertEqual(issues["TEMPLATE_ADDRESS"]["counts"]["template_address"], 3)
        self.assertIn("非常", issues["INTENSIFIER_DENSITY"]["evidence"])
        self.assertTrue(all(item["severity"] == "warning" for item in issues.values()))

    def test_density_uses_prose_characters_and_requires_two_hits(self):
        at_threshold = "真的非常" + "甲" * 96
        below_threshold = at_threshold + "甲"
        self.assertEqual(style_counts(at_threshold)["intensifiers_per_100"], 2)
        self.assertIn("INTENSIFIER_DENSITY", {i["code"] for i in scan_style(at_threshold, "light")})
        self.assertNotIn("INTENSIFIER_DENSITY", {i["code"] for i in scan_style(below_threshold, "light")})
        self.assertEqual(scan_style("可以直接接线。", "light"), [])

    def test_concrete_vehicle_limitations_do_not_trigger_style_warnings(self):
        # Original synthetic counterpart to the user's concrete vehicle example.
        text = ("车辆功能：定位服务可以查看停车位置，电子围栏会在车辆离开设定区域时提醒。"
                "部分配置支持远程设防。电池页面显示电量与健康状态，供日常检查使用。"
                "不过，续航估算会受气温、载重和道路状况影响，不能完全视为固定值。"
                "购买前可确认这些功能是否需要另行付费。")
        self.assertEqual(scan_style(text, "light"), [])
        self.assertEqual(scan_style(text, "strong"), [])
        self.assertEqual(compare_style(text, text), [])

    def test_factual_exclusions_are_review_candidates_never_hard_errors(self):
        text = "故障不是供电中断，而是连接松动。告警不是温度过高，是传感器接触不良。"
        issues = scan_style(text, "strong")
        self.assertIn("REPEATED_CONTRAST", {item["code"] for item in issues})
        self.assertTrue(all(item["severity"] == "warning" for item in issues))
        self.assertIn("真实排除项", issues[0]["message"])
        # Style checks make no edit and do not classify the exclusion as false.
        self.assertEqual(compare_style(text, text), [])

    def test_growth_reports_each_pattern_category(self):
        source = "预算已经核对。材料已经收到。"
        candidate = "毕竟，结果是：预算既核对过又复查过；不是猜测，是记录。材料齐全，也已经归档。"
        issues = [item for item in compare_style(source, candidate) if item["code"] == "ADDED_TEMPLATE"]
        self.assertEqual({item["category"] for item in issues},
                         {"colon", "semicolon", "symmetric_parallel", "sentence_connector", "revelatory_contrast"})
        self.assertTrue(all(item["severity"] == "warning" for item in issues))
        self.assertTrue(all(item["counts"]["candidate"] > item["counts"]["source"] for item in issues))
        self.assertTrue(all(item["evidence"]["candidate"] for item in issues))

    def test_unchanged_and_reduced_patterns_are_not_added(self):
        source = "毕竟，结果是：材料齐全，也已经确认；不是推测，是记录。"
        self.assertEqual(compare_style(source, source), [])
        self.assertEqual(compare_style(source, "材料齐全，已经确认。"), [])

    def test_colloquial_loss_is_a_warning_with_specific_terms(self):
        issues = compare_style("先算明白这笔账，别急着把工具封神，也别把余地吃掉。",
                               "先核算成本，不要认为工具无所不能，也不要消耗剩余空间。")
        flattened = next(item for item in issues if item["code"] == "COLLOQUIAL_FLATTENED")
        self.assertEqual(set(flattened["evidence"]), {"算明白", "封神", "吃掉"})
        self.assertEqual(flattened["severity"], "warning")
        self.assertEqual(compare_style("别把它封神。", "先别把它封神。"), [])

    def test_urls_and_code_do_not_create_template_counts(self):
        source = "可查看示例。"
        opaque = ('示例 https://example.test:8443/a?q=x:y 和 https://other.test/a:b 。\n'
                  '`不是甲，是乙；既甲又乙：我想跟你说真的非常。`\n'
                  '```python\nif ready:\n    payload = {"x": "真的非常"}; print("毕竟，封神")\n```')
        stats = style_counts(opaque)
        self.assertEqual(stats["counts"]["colon"], 0)
        self.assertEqual(stats["counts"]["semicolon"], 0)
        self.assertEqual(stats["counts"]["revelatory_contrast"], 0)
        self.assertEqual(scan_style(opaque, "light"), [])
        self.assertEqual(compare_style(source, source + "\n" + opaque), [])

    def test_preserved_direct_quotes_are_not_editing_targets(self):
        quote = '负责人说：“真的非常彻底，不是甲，是乙，不是丙，是丁。我想跟你说，你会发现。”'
        self.assertEqual(scan_style(quote, "light"), [])
        self.assertEqual(style_counts(quote)["counts"]["revelatory_contrast"], 0)
        self.assertEqual(compare_style(quote, quote), [])

    def test_sentence_initial_can_is_not_misread_as_transition(self):
        self.assertEqual(style_counts("可以查到记录。可能尚未更新。可选项目已列出。")["counts"]["sentence_connector"], 0)
        self.assertEqual(style_counts("毕竟有记录。可目前没有收到。而问题还在。此外，材料缺页。")["counts"]["sentence_connector"], 4)

    def test_clock_and_ratio_colons_are_not_prose_templates(self):
        self.assertEqual(style_counts("时间为 14:30，比例为 2：1。")["counts"]["colon"], 0)
        self.assertEqual(style_counts("时间：下午，比例:待定。")["counts"]["colon"], 2)

    def test_default_and_explicit_off_preserve_old_output(self):
        text = "不是宣传，是材料。根本不是猜测。真的非常彻底。我想跟你说，你会发现。"
        self.assertEqual(scan_style(text), [])
        self.assertEqual(scan_style(text, "off"), [])
        old_text = "不是宣传而是材料。不是猜测而是记录。"
        expected = [{"code": "REPEATED_CONTRAST", "severity": "warning",
                     "source": "不是宣传而是材料\n不是猜测而是记录", "candidate": "",
                     "message": "多次使用否定后转折，检查每组对比是否有事实依据；有实际排除逻辑时应保留。"}]
        self.assertEqual(scan_style(old_text), expected)
        self.assertEqual(scan_style(old_text, "off"), expected)

    def test_legacy_opening_address_ending_and_real_exclusion_keep_their_codes(self):
        cases = [
            ("在当今快速发展的时代，信息越来越多。", ["GENERIC_OPENING"]),
            ("家人们，资料已经备齐。姐妹们，可以查看。", ["REPEATED_ADDRESS"]),
            ("材料已完成，让我们携手开创新局面。", ["GENERIC_ENDING"]),
            ("不是网络问题，不是账号问题，也不是服务器故障，而是本机磁盘已满。", []),
        ]
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual([item["code"] for item in scan_style(text)], expected)
                self.assertEqual([item["code"] for item in scan_style(text, "off")], expected)

    def test_invalid_mode_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "deai"):
            scan_style("记录已收到。", "unknown")


if __name__ == "__main__":
    unittest.main()
