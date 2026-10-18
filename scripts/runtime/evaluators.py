"""Conservative local checks, not an authorship detector or semantic proof.

Hard checks cover selected protected surface forms. A clean result does NOT
prove preservation of meaning: negation, causal claims, certainty, deadlines,
speaker identity and associations between numbers require an independent judge.
Style findings are review candidates, never facts about who wrote a text.
"""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation


def _issue(code: str, severity: str, source: str, candidate: str, message: str) -> dict:
    return {"code": code, "severity": severity, "source": source,
            "candidate": candidate, "message": message}


_URL = re.compile(r'https?://[^\s<>"“”「」『』]+')
_CODE = re.compile(r"```[^\n]*\n([\s\S]*?)```|`([^`\n]+)`")
_QUOTES = re.compile(r'“([^”\n]*)”|「([^」\n]*)」|『([^』\n]*)』|"([^"\n]*)"')
_SPEECH = re.compile(r"(?:说|表示|写道|强调|回答|指出|声称|宣称|回复|承诺|原话|原文|声明|记载)[^。！？\n]{0,12}[：:]?\s*$")

# Unit names stay explicit: '%' and '个百分点' are deliberately distinct.
# Calendar years/months and the ambiguous '分' are not treated as fixed durations.
_UNITS = {
    "个百分点": ("percentage_point", "1"), "%": ("percent", "1"),
    "元": ("yuan", "1"), "人民币": ("yuan", "1"),
    "美元": ("usd", "1"), "美金": ("usd", "1"),
    "欧元": ("eur", "1"), "澳元": ("aud", "1"),
    "毫秒": ("second", ".001"), "秒": ("second", "1"),
    "分钟": ("second", "60"), "小时": ("second", "3600"),
    "天": ("second", "86400"), "周": ("second", "604800"),
    "毫米": ("meter", ".001"), "厘米": ("meter", ".01"),
    "米": ("meter", "1"), "千米": ("meter", "1000"),
    "公里": ("meter", "1000"), "克": ("gram", "1"),
    "千克": ("gram", "1000"), "公斤": ("gram", "1000"),
    "吨": ("gram", "1000000"), "倍": ("times", "1"),
    **{u: (u, "1") for u in ("人", "次", "项", "件", "个", "条", "页", "位", "款", "台", "家", "年", "月", "日", "分", "岁")},
}
_UNIT_PATTERN = "|".join(re.escape(u) for u in sorted(_UNITS, key=len, reverse=True))
_ARABIC = r"[+-]?(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
_CHINESE = r"[零〇一二两三四五六七八九十百千万亿]+(?:点[零〇一二两三四五六七八九]+)?"
_QUANTITY = re.compile(
    rf"(?<![A-Za-z0-9_.])(?P<num>{_ARABIC})(?P<scale>[万亿])?\s*(?P<unit>{_UNIT_PATTERN})?"
    rf"|(?P<cn>{_CHINESE})\s*(?P<cunit>{_UNIT_PATTERN})"
)
_PERCENT_WORDS = re.compile(rf"百分之\s*(?P<num>{_ARABIC}|{_CHINESE})")
_RANGE = re.compile(rf"^\s*(?:至|到|—|–|~|～|-)\s*(?:{_ARABIC}|{_CHINESE})(?P<scale>[万亿])?\s*(?P<unit>{_UNIT_PATTERN})")
_DIGITS = {c: n for n, chars in enumerate(("零〇", "一", "二两", "三", "四", "五", "六", "七", "八", "九")) for c in chars}


def _chinese_integer(value: str) -> Decimal:
    for unit, multiplier in (("亿", 100000000), ("万", 10000)):
        if unit in value:
            left, right = value.split(unit, 1)
            return (_chinese_integer(left) if left else Decimal(1)) * multiplier + (_chinese_integer(right) if right else Decimal(0))
    if not any(c in value for c in "十百千"):
        return Decimal("".join(str(_DIGITS[c]) for c in value))
    total = current = 0
    for char in value:
        if char in _DIGITS:
            current = _DIGITS[char]
        else:
            total += (current or 1) * {"十": 10, "百": 100, "千": 1000}[char]
            current = 0
    return Decimal(total + current)


def _number(value: str) -> Decimal:
    try:
        return Decimal(value.replace(",", ""))
    except InvalidOperation:
        left, separator, right = value.partition("点")
        result = _chinese_integer(left)
        return result + (Decimal("0." + "".join(str(_DIGITS[c]) for c in right)) if separator else 0)


def _without_opaque(text: str) -> str:
    """URLs/code are protected separately, not parsed as ordinary prose numbers."""
    return _URL.sub(" ", _CODE.sub(" ", text))


def _quantities(text: str) -> dict[tuple[Decimal, str], str]:
    text = unicodedata.normalize("NFKC", _without_opaque(text)).replace("−", "-")
    result = {}
    spans = []
    for match in _PERCENT_WORDS.finditer(text):
        result[(_number(match["num"]), "percent")] = match[0]
        spans.append(match.span())
    for match in _QUANTITY.finditer(text):
        if any(a <= match.start() < b for a, b in spans):
            continue
        # Avoid interpreting 十分重要 / 一分为二 as minute counts.
        if match["cn"] and match["cunit"] == "分":
            continue
        value = _number(match["num"] or match["cn"])
        unit = match["unit"] or match["cunit"]
        scale = match["scale"]
        if not unit:
            # In 10–20%, the right-hand unit applies to both endpoints.
            following = _RANGE.match(text[match.end():])
            if following:
                unit, scale = following["unit"], scale or following["scale"]
        if scale:
            value *= {"万": 10000, "亿": 100000000}[scale]
        canonical, multiplier = _UNITS.get(unit, ("number", "1"))
        result[(value * Decimal(multiplier), canonical)] = match[0].strip()
    return result


def _urls(text: str) -> set[str]:
    urls = set()
    for match in _URL.finditer(text):
        url = match[0].rstrip(".,;:!?，。；：！？、")
        for opening, closing in (("(", ")"), ("（", "）"), ("[", "]")):
            while url.endswith(closing) and url.count(closing) > url.count(opening):
                url = url[:-1]
        urls.add(url)
    return urls


def _codes(text: str) -> set[str]:
    return {(match[1] if match[1] is not None else match[2]).rstrip("\n") for match in _CODE.finditer(text)}


def _quotes(text: str) -> tuple[set[str], set[str]]:
    all_quotes, direct_quotes = set(), set()
    text = _without_opaque(text)
    for match in _QUOTES.finditer(text):
        value = next(group for group in match.groups() if group is not None)
        all_quotes.add(value)
        if _SPEECH.search(text[max(0, match.start() - 30):match.start()]):
            direct_quotes.add(value)
    return all_quotes, direct_quotes


def deterministic_check(source: str, candidate: str) -> list[dict]:
    """Return narrowly defined discrepancies. Empty does not mean semantically safe.

    Number checks compare unique canonical quantity/unit pairs, not occurrence
    counts. They cannot bind a number to the correct subject or prove equivalence
    of a newly calculated value. Errors should trigger review/repair, not certify
    the source as true. Quote-marked terms without attribution produce warnings.
    """
    issues = []
    if source.strip() and not candidate.strip():
        return [_issue("EMPTY_OUTPUT", "error", source, candidate, "改稿为空，无法保留原文。")]

    before, after = _quantities(source), _quantities(candidate)
    if before.keys() != after.keys():
        missing = [before[k] for k in before.keys() - after.keys()]
        added = [after[k] for k in after.keys() - before.keys()]
        issues.append(_issue("QUANTITY_CHANGED", "error", "、".join(sorted(missing)), "、".join(sorted(added)),
                             "数字或单位不一致；请核对新增、遗漏和量纲变化。此检查不能证明数字与主体的对应关系。"))

    for code, extractor, label in (("URL_CHANGED", _urls, "链接"), ("CODE_CHANGED", _codes, "代码片段")):
        old, new = extractor(source), extractor(candidate)
        if old != new:
            issues.append(_issue(code, "error", "\n".join(sorted(old - new)), "\n".join(sorted(new - old)), f"{label}新增、丢失或变化，应按原文保留。"))

    old_all, old_direct = _quotes(source)
    new_all, new_direct = _quotes(candidate)
    # Attribution detection is a conservative heuristic; text itself must remain.
    direct_removed = old_direct - new_all
    direct_added = new_direct - old_all
    if direct_removed or direct_added:
        issues.append(_issue("DIRECT_QUOTE_CHANGED", "error", "\n".join(sorted(direct_removed)), "\n".join(sorted(direct_added)),
                             "带引述线索的原话新增、丢失或改动；请保留原话，或交语义评审核实是否正确转述。"))
    other_removed = old_all - new_all - direct_removed
    other_added = new_all - old_all - direct_added
    if other_removed or other_added:
        issues.append(_issue("QUOTED_TEXT_CHANGED", "warning", "\n".join(sorted(other_removed)), "\n".join(sorted(other_added)),
                             "引号内文字发生变化，可能是术语、标题或转述；需要结合上下文判断。"))
    return issues


def _legacy_scan_style(text: str) -> list[dict]:
    """The v0.2 checks, unchanged for explicit/default deai=off compatibility."""
    issues = []
    lead = re.search(r"^\s*(?:在这个|在当今|随着).{0,45}(?:时代|不断发展|飞速发展|快速发展).{0,50}?[。！？]", text)
    if lead:
        issues.append(_issue("GENERIC_OPENING", "warning", lead[0].strip(), "", "开头可能只有宽泛背景；检查是否提供了本文需要的信息。"))
    # A single contrast, or three genuinely excluded causes, is not a finding.
    contrasts = list(re.finditer(r"不是[^。！？\n]{1,60}?而是[^。！？\n]{1,60}", text))
    if len(contrasts) >= 2:
        issues.append(_issue("REPEATED_CONTRAST", "warning", "\n".join(m[0] for m in contrasts), "", "多次使用否定后转折，检查每组对比是否有事实依据；有实际排除逻辑时应保留。"))
    address = list(re.finditer(r"(?:家人们|宝子们|兄弟们|姐妹们)[，,！!：:]", text))
    if len(address) >= 2:
        issues.append(_issue("REPEATED_ADDRESS", "warning", "\n".join(m[0] for m in address), "", "重复称呼可能打断信息；结合场景和用户口吻判断，不自动删除。"))
    ending = re.search(r"(?:让我们携手|共同谱写|共创辉煌|开启无限可能|未来可期)[^。！？\n]{0,40}[。！？]?\s*$", text)
    if ending:
        issues.append(_issue("GENERIC_ENDING", "warning", ending[0], "", "结尾可能是没有新增信息的口号；检查是否属于必要的演讲或品牌表达。"))
    return issues


# These are surface-form editing candidates, not an authorship classifier. In
# particular, a contrast may be a necessary factual exclusion. Only a semantic
# reviewer can decide whether to edit it; no finding below is a hard error.
_STYLE_URL = re.compile(r'https?://[^\s<>"“”「」『』，。；！？、]+')
_CONTRASTS = (
    re.compile(r"不是[^。！？\n]{1,60}?(?:[，,]\s*(?:而)?是|而是)"),
    re.compile(r"根本不是"),
    re.compile(r"真正[^。！？\n]{0,20}?的(?:根本)?(?:不是|是)"),
)
_INTENSIFIERS = re.compile(
    r"大刀阔斧|毫无疑问|真的|彻底|非常|疯狂|直接|根本|完全|震撼|残酷|全面|深入|狠"
)
_TEMPLATE_ADDRESS = re.compile(
    r"我想跟你说|你应该(?:还)?记得|你仔细看就会发现|今天我们来聊(?:一下)?|说白了|你会发现"
)
_SYMMETRY = (
    re.compile(r"既[^。！？；;\n]{1,40}?又"),
    re.compile(r"一边[^。！？；;\n]{1,40}?一边"),
    re.compile(r"又[^。，,！？；;\n]{1,12}?又"),
    re.compile(r"更[^。，,！？；;\n]{1,12}[，,、]\s*(?:也)?更"),
    re.compile(r"[^，,。！？；;\n]{1,24}[，,]\s*也(?!许|是)[^，,。！？；;\n]{1,24}"),
)
_CONNECTORS = re.compile(
    r"(?:^|(?<=[。！？\n]))\s*(?:毕竟|此外|然而|不过|所以|因此|而且|同时|"
    r"可(?!以|能|用|靠|行|选|见|爱|贵|怜|怕|惜)|而(?!今))"
)
_COLLOQUIAL = re.compile(r"封神|吃掉|端掉|砍掉|算明白|划不来|不划算")
_STYLE_LABELS = {
    "colon": "冒号", "semicolon": "分号", "symmetric_parallel": "对称并列",
    "sentence_connector": "句首衔接词", "revelatory_contrast": "揭示或否定转折句式",
}


def _masked(value: str) -> str:
    """Keep offsets and paragraph boundaries while excluding protected content."""
    return "".join("\n" if char == "\n" else " " for char in value)


def _style_surface(text: str) -> str:
    surface = _CODE.sub(lambda match: _masked(match[0]), text)
    surface = _STYLE_URL.sub(lambda match: _masked(match[0]), surface)
    # Explicitly attributed verbatim quotations are not editable style targets.
    # Quoted terminology is not automatically exempt from contextual review.
    spans = []
    for match in _QUOTES.finditer(surface):
        if _SPEECH.search(surface[max(0, match.start() - 30):match.start()]):
            spans.append(match.span())
    for start, end in reversed(spans):
        surface = surface[:start] + _masked(surface[start:end]) + surface[end:]
    return surface


def _merged_matches(patterns: tuple, text: str) -> list[str]:
    """Count overlapping recognizers for one construction only once.

    Patterns stop at the pivot (e.g. 是/而是), so another contrast later in the
    same sentence is still counted. Nested 根本不是/真正…的不是 is one candidate.
    """
    spans = sorted(match.span() for pattern in patterns for match in pattern.finditer(text))
    merged = []
    for start, end in spans:
        if merged and start < merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return [text[start:end].strip() for start, end in merged]


def style_counts(text: str) -> dict:
    """Return inspectable counts/evidence, never a probability of AI authorship.

    Counts exclude code, URLs, and attributed verbatim quotes. Intensifier
    density uses visible letter/number characters rather than punctuation or
    whitespace. Matching a word says nothing about whether its use is justified.
    """
    surface = _style_surface(text)
    def punctuation_evidence(pattern: str) -> list[str]:
        return [surface[max(0, m.start() - 16):min(len(surface), m.end() + 16)].strip()
                for m in re.finditer(pattern, surface)]

    evidence = {
        "colon": punctuation_evidence(r"(?<!\d)[:：]|[:：](?!\d)"),
        "semicolon": punctuation_evidence(r"[;；]"),
        "symmetric_parallel": _merged_matches(_SYMMETRY, surface),
        "sentence_connector": [m[0].strip() for m in _CONNECTORS.finditer(surface)],
        "revelatory_contrast": _merged_matches(_CONTRASTS, surface),
        "intensifier": [m[0] for m in _INTENSIFIERS.finditer(surface)],
        "template_address": [m[0] for m in _TEMPLATE_ADDRESS.finditer(surface)],
        "colloquial": [m[0] for m in _COLLOQUIAL.finditer(surface)],
    }
    count = sum(char.isalnum() for char in surface)
    return {"counts": {key: len(values) for key, values in evidence.items()},
            "evidence": evidence, "prose_characters": count,
            "intensifiers_per_100": round(len(evidence["intensifier"]) * 100 / max(count, 1), 3)}


def scan_style(text: str, deai: str = "off") -> list[dict]:
    """Suggest style-review candidates; deai=off preserves the v0.2 behavior.

    Both light and strong report the same surface candidates. Their *editing*
    permissions differ in the task/reviewer, not in an authorship score.
    """
    if deai not in {"off", "light", "strong"}:
        raise ValueError("deai must be off, light, or strong")
    if deai == "off":
        return _legacy_scan_style(text)
    surface = _style_surface(text)
    issues = [item for item in _legacy_scan_style(surface) if item["code"] != "REPEATED_CONTRAST"]
    stats = style_counts(text)
    counts, evidence = stats["counts"], stats["evidence"]
    if counts["revelatory_contrast"] >= 2:
        issue = _issue("REPEATED_CONTRAST", "warning", "\n".join(evidence["revelatory_contrast"]), "",
                       "多次出现揭示或否定转折句式。这里只定位编辑候选，不能判断是否是假揭示；真实排除项和事实否定应保留，light 不拆论述结构。")
        issue.update(counts={"revelatory_contrast": counts["revelatory_contrast"]},
                     evidence=evidence["revelatory_contrast"])
        issues.append(issue)
    # At least two hits avoids labelling a short factual sentence solely because
    # it contains one valid modifier (e.g. 完全/直接).
    if counts["intensifier"] >= 2 and stats["intensifiers_per_100"] >= 2:
        issue = _issue("INTENSIFIER_DENSITY", "warning", "、".join(evidence["intensifier"]), "",
                       "强化词较密集；检查相邻表达是否重复，只调整冗余程度词，不改变判断方向、条件或事实范围。")
        issue.update(counts={"intensifier": counts["intensifier"],
                             "prose_characters": stats["prose_characters"],
                             "per_100": stats["intensifiers_per_100"]}, evidence=evidence["intensifier"])
        issues.append(issue)
    if counts["template_address"] >= 2:
        issue = _issue("TEMPLATE_ADDRESS", "warning", "\n".join(evidence["template_address"]), "",
                       "模板互动出现多次；检查是否有实际沟通作用，可减少重复铺垫。引述原话应保持，不按词表自动删除。")
        issue.update(counts={"template_address": counts["template_address"]},
                     evidence=evidence["template_address"])
        issues.append(issue)
    return issues


def compare_style(source: str, candidate: str) -> list[dict]:
    """Warn about added templates or lost colloquial wording; never mutate text.

    Counts cannot determine whether a new colon or transition is useful. A human
    or model reviewer must inspect the evidence and preserve factual negations,
    direct quotations, scope, and meaningful authorial language.
    """
    before, after = style_counts(source), style_counts(candidate)
    issues = []
    for key, label in _STYLE_LABELS.items():
        old_count, new_count = before["counts"][key], after["counts"][key]
        if new_count > old_count:
            issue = _issue("ADDED_TEMPLATE", "warning", "\n".join(before["evidence"][key]),
                           "\n".join(after["evidence"][key]),
                           f"改稿的{label}从 {old_count} 处增至 {new_count} 处；检查是否只是新增套路，或为表达原有信息所必需。这不是作者判定。")
            issue.update(category=key, counts={"source": old_count, "candidate": new_count},
                         evidence={"source": before["evidence"][key], "candidate": after["evidence"][key]})
            issues.append(issue)
    lost = sorted(set(before["evidence"]["colloquial"]) - set(after["evidence"]["colloquial"]))
    if lost:
        issue = _issue("COLLOQUIAL_FLATTENED", "warning", "、".join(lost), "",
                       "原文的特色口语在改稿中消失；检查是否被无必要地换成中性书面词。仅提示复核，不要求保留已不适合上下文的词。")
        issue.update(counts={"lost_distinct_terms": len(lost)}, evidence=lost)
        issues.append(issue)
    return issues
