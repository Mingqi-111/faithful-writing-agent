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


def scan_style(text: str) -> list[dict]:
    """Suggest limited style review candidates; never infer AI authorship."""
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
