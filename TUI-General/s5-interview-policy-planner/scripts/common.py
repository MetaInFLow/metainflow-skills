from __future__ import annotations

import csv
import json
import math
import re
import unicodedata
from copy import copy
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable


CHINESE_DIGITS = {
    "零": 0,
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "两": 2,
}

UNIT_MAP = {
    "十": 10,
    "百": 100,
    "千": 1000,
    "万": 10000,
    "亿": 100000000,
}

FIT_STATUS_ELIGIBLE = "符合"
FIT_STATUS_CONDITIONAL = "有条件符合"
FIT_STATUS_INSUFFICIENT_EVIDENCE = "证据不足"
FIT_STATUS_NOT_FIT = "不符合"

FIT_STATUS_ALIASES = {
    "eligible": FIT_STATUS_ELIGIBLE,
    "conditional": FIT_STATUS_CONDITIONAL,
    "insufficient_evidence": FIT_STATUS_INSUFFICIENT_EVIDENCE,
    "not_fit": FIT_STATUS_NOT_FIT,
    FIT_STATUS_ELIGIBLE: FIT_STATUS_ELIGIBLE,
    FIT_STATUS_CONDITIONAL: FIT_STATUS_CONDITIONAL,
    FIT_STATUS_INSUFFICIENT_EVIDENCE: FIT_STATUS_INSUFFICIENT_EVIDENCE,
    FIT_STATUS_NOT_FIT: FIT_STATUS_NOT_FIT,
}

SELECTABLE_FIT_STATUSES = {FIT_STATUS_ELIGIBLE, FIT_STATUS_CONDITIONAL}
REVIEWABLE_FIT_STATUSES = {
    FIT_STATUS_ELIGIBLE,
    FIT_STATUS_CONDITIONAL,
    FIT_STATUS_INSUFFICIENT_EVIDENCE,
}

APPROXIMATE_MARKERS = (
    "大概",
    "左右",
    "约",
    "得有",
    "差不多",
    "上下",
    "出头",
    "快",
    "将近",
    "差不多奔着",
)

DISTRICTS = (
    "南山区",
    "宝安区",
    "龙华区",
    "罗湖区",
    "福田区",
    "龙岗区",
    "盐田区",
    "坪山区",
    "光明区",
    "大鹏新区",
    "深汕特别合作区",
)

POLICY_SECTION_LABELS = (
    "申报对象：",
    "申报条件：",
    "基础条件：",
    "专项条件：",
    "基本条件：",
    "认定标准：",
    "优先条件：",
    "优先范围：",
    "受理范围：",
    "受理标准：",
    "服务对象：",
    "支持对象：",
    "支持标准：",
    "奖励标准：",
)


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text).strip())


def normalize_multiline_text(text: Any) -> str:
    value = str(text or "").replace("\r\n", "\n").replace("\r", "\n").replace("\u3000", " ")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in value.split("\n")]
    return "\n".join(line for line in lines if line)


def format_policy_conditions(text: Any) -> str:
    value = normalize_multiline_text(text)
    if not value:
        return ""

    for label in sorted(POLICY_SECTION_LABELS, key=len, reverse=True):
        value = re.sub(rf"(?<!\n){re.escape(label)}", f"\n{label}", value)

    value = re.sub(r"(?<!\n)([一二三四五六七八九十]+、)", r"\n\1", value)
    value = re.sub(r"(?<!\n)([（(][一二三四五六七八九十]+[)）])", r"\n\1", value)
    value = re.sub(r"(?<!\n)([（(]\d+[)）])", r"\n\1", value)
    value = re.sub(r"(?<!\n)([①②③④⑤⑥⑦⑧⑨⑩])", r"\n\1", value)
    value = re.sub(r"(?<!\n)([一二三四五六七八九十]类。)", r"\n\1", value)
    value = re.sub(r"([：:；;。])\s*(\d+\.(?=[^\d]))", r"\1\n\2", value)
    value = re.sub(r"(?<!\n)\s+(\d+\.(?=[^\d]))", r"\n\1", value)

    if "\n" not in value and len(value) > 120:
        value = re.sub(r"；\s*", "；\n", value)

    value = re.sub(r"\n{2,}", "\n", value)
    return value.strip()


def display_width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(char) in {"F", "W"} else 1 for char in str(text))


def estimate_wrapped_lines(text: Any, chars_per_line: int) -> int:
    value = normalize_multiline_text(text)
    if not value:
        return 1
    total = 0
    for line in value.split("\n"):
        total += max(1, math.ceil(max(1, display_width(line)) / max(1, chars_per_line)))
    return total


def estimate_row_height(
    texts: Iterable[tuple[Any, int]],
    min_height: float = 24.0,
    line_height: float = 16.5,
    padding: float = 8.0,
    max_height: float = 409.5,
) -> float:
    line_count = 1
    for text, chars_per_line in texts:
        line_count = max(line_count, estimate_wrapped_lines(text, chars_per_line))
    return round(min(max_height, max(min_height, line_count * line_height + padding)), 2)


def normalize_fit_status(value: Any) -> str:
    return FIT_STATUS_ALIASES.get(clean_text(str(value)), clean_text(str(value)))


def normalize_string(text: Any) -> str:
    return clean_text(str(text)).strip("“”\"'[]()（）")


def contains_approximation(text: str) -> bool:
    value = clean_text(text)
    return any(marker in value for marker in APPROXIMATE_MARKERS)


def chinese_to_int(text: str) -> int | None:
    value = clean_text(text).replace("个", "")
    if not value:
        return None

    if all(char in CHINESE_DIGITS for char in value):
        return int("".join(str(CHINESE_DIGITS[char]) for char in value))

    total = 0
    section = 0
    number = 0
    for char in value:
        if char in CHINESE_DIGITS:
            number = CHINESE_DIGITS[char]
            continue
        unit = UNIT_MAP.get(char)
        if unit is None:
            return None
        if unit < 10000:
            if number == 0:
                number = 1
            section += number * unit
        else:
            section = (section + number) * unit
            total += section
            section = 0
        number = 0
    return total + section + number


def extract_number(text: Any) -> float | None:
    value = clean_text(str(text)).replace(",", "")
    arabic = re.search(r"\d+(?:\.\d+)?", value)
    if arabic:
        return float(arabic.group())

    chinese = re.search(r"[零一二三四五六七八九十百千万亿两]+", value)
    if chinese:
        parsed = chinese_to_int(chinese.group())
        if parsed is not None:
            return float(parsed)

    range_hint = re.search(r"([一二三四五六七八九])([一二三四五六七八九])十", value)
    if range_hint:
        low = CHINESE_DIGITS[range_hint.group(1)] * 10
        high = CHINESE_DIGITS[range_hint.group(2)] * 10
        return float((low + high) / 2)
    return None


def normalize_number(value: float | None) -> int | float | None:
    if value is None:
        return None
    if float(value).is_integer():
        return int(value)
    return round(float(value), 2)


def parse_amount_to_wanyuan(text: Any) -> int | float | None:
    value = clean_text(str(text)).replace(",", "")
    number = extract_number(value)
    if number is None:
        return None
    if "亿" in value:
        return normalize_number(number * 10000)
    if "万" in value:
        return normalize_number(number)
    if "元" in value:
        return normalize_number(number / 10000)
    return normalize_number(number)


def parse_percentage(text: Any) -> int | float | None:
    value = clean_text(str(text))
    numbers = re.findall(r"\d+(?:\.\d+)?", value)
    if len(numbers) >= 2 and re.search(r"(到|至|-|~)", value):
        return normalize_number(float(numbers[0]))
    return normalize_number(extract_number(value))


def parse_int(text: Any) -> int | None:
    value = normalize_number(extract_number(text))
    if value is None:
        return None
    return int(float(value))


def try_parse_date(text: Any) -> str | None:
    value = clean_text(str(text))
    if not value or value.lower() == "nan":
        return None

    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue

    m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", value)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
    return None


def today_iso() -> str:
    return date.today().isoformat()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False))
            handle.write("\n")


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [{k: (v if v is not None else "") for k, v in row.items()} for row in reader]


def dedupe_texts(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    items: list[str] = []
    for value in values:
        cleaned = clean_text(value)
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        items.append(cleaned)
    return items


def ensure_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def cell_value_to_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def copy_row_style(ws, source_row: int, target_row: int, max_col: int) -> None:
    ws.row_dimensions[target_row].height = ws.row_dimensions[source_row].height
    for col in range(1, max_col + 1):
        source = ws.cell(source_row, col)
        target = ws.cell(target_row, col)
        if source.has_style:
            target._style = copy(source._style)
        if source.number_format:
            target.number_format = source.number_format
        if source.font:
            target.font = copy(source.font)
        if source.fill:
            target.fill = copy(source.fill)
        if source.border:
            target.border = copy(source.border)
        if source.alignment:
            target.alignment = copy(source.alignment)
        if source.protection:
            target.protection = copy(source.protection)


def infer_district(text: str | None) -> str | None:
    if not text:
        return None
    value = clean_text(text)
    for district in DISTRICTS:
        if district in value:
            return district
    return None


def stringify_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)
