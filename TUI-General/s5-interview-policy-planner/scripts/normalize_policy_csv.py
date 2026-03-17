from __future__ import annotations

import argparse
import re
from datetime import date
from pathlib import Path
from typing import Any

from common import clean_text, dedupe_texts, read_csv_rows, today_iso, try_parse_date, write_jsonl


DEFAULT_COLUMNS = [
    "级别",
    "部委",
    "项目名称",
    "项目类型",
    "申报对象",
    "申报条件",
    "解读版",
    "资助强度",
    "支持方式",
    "申报时间",
    "申报截止时间",
    "通知链接",
    "文件有效期",
    "管理办法",
]

SHENZHEN_DISTRICTS = (
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

KNOWN_CITY_TO_PROVINCE = {
    "深圳市": "广东省",
    "广州市": "广东省",
    "佛山市": "广东省",
    "东莞市": "广东省",
    "惠州市": "广东省",
    "中山市": "广东省",
    "珠海市": "广东省",
    "江门市": "广东省",
    "湛江市": "广东省",
    "汕头市": "广东省",
    "汕尾市": "广东省",
    "梅州市": "广东省",
    "揭阳市": "广东省",
    "潮州市": "广东省",
    "茂名市": "广东省",
    "阳江市": "广东省",
    "肇庆市": "广东省",
    "清远市": "广东省",
    "韶关市": "广东省",
    "河源市": "广东省",
    "云浮市": "广东省",
    "北京市": "北京市",
    "天津市": "天津市",
    "上海市": "上海市",
    "重庆市": "重庆市",
}

PROVINCE_NAMES = (
    "北京市",
    "天津市",
    "上海市",
    "重庆市",
    "河北省",
    "山西省",
    "辽宁省",
    "吉林省",
    "黑龙江省",
    "江苏省",
    "浙江省",
    "安徽省",
    "福建省",
    "江西省",
    "山东省",
    "河南省",
    "湖北省",
    "湖南省",
    "广东省",
    "海南省",
    "四川省",
    "贵州省",
    "云南省",
    "陕西省",
    "甘肃省",
    "青海省",
    "台湾省",
    "内蒙古自治区",
    "广西壮族自治区",
    "西藏自治区",
    "宁夏回族自治区",
    "新疆维吾尔自治区",
    "香港特别行政区",
    "澳门特别行政区",
)

GENERIC_CITY_TERMS = {"本市", "我市", "全市", "市级", "地市"}
GENERIC_DISTRICT_TERMS = {"本区", "全区", "区内", "辖区", "园区"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Normalize policy CSV into JSONL for policy matching.")
    parser.add_argument("--input", type=Path, required=True, help="Path to policy CSV.")
    parser.add_argument("--output", type=Path, required=True, help="Path to normalized JSONL output.")
    parser.add_argument("--today", default=today_iso(), help="ISO date for date-status calculations.")
    return parser.parse_args()


def infer_section_hint(row: dict[str, str]) -> str:
    project_type = clean_text(row.get("项目类型", ""))
    support_mode = clean_text(row.get("支持方式", ""))
    title = clean_text(row.get("项目名称", ""))
    strength = clean_text(row.get("资助强度", ""))
    text = " ".join([project_type, support_mode, title, strength])

    if "认定" in project_type or "认定" in title:
        return "资质认定类"
    if any(token in text for token in ("资助", "补助", "奖补", "扶持", "配套")):
        return "资助类"
    if any(token in text for token in ("评选", "评价", "征集", "示范", "中心", "品牌", "小巨人", "单项冠军", "专利奖", "领军企业", "创新产品")):
        return "资质认定类"
    return "未知"


def build_scope(level: str, district: str | None = None, city: str | None = None, province: str | None = None) -> dict[str, str | None]:
    return {"level": level, "district": district, "city": city, "province": province}


def scope_priority(scope: dict[str, str | None] | None) -> int:
    if not scope:
        return -1
    return {
        "unknown": -1,
        "national": 0,
        "province": 1,
        "city": 2,
        "district": 3,
    }.get(str(scope.get("level")), -1)


def extract_explicit_province(text: str) -> str | None:
    for province in PROVINCE_NAMES:
        if province in text:
            return province
    return None


def infer_province_from_city(city: str | None) -> str | None:
    if not city:
        return None
    return KNOWN_CITY_TO_PROVINCE.get(city)


def extract_explicit_city(text: str) -> str | None:
    for city in KNOWN_CITY_TO_PROVINCE:
        if city in text:
            return city
    match = re.search(r"([一-龥]{2,7}市)", text)
    if not match:
        return None
    candidate = match.group(1)
    if candidate in GENERIC_CITY_TERMS:
        return None
    return candidate


def extract_explicit_district(text: str) -> str | None:
    for district in SHENZHEN_DISTRICTS:
        if district in text:
            return district
    match = re.search(r"([一-龥]{2,10}(?:区|新区|特别合作区))", text)
    if not match:
        return None
    candidate = match.group(1)
    if candidate in GENERIC_DISTRICT_TERMS:
        return None
    return candidate


def infer_scope_from_level_text(level_text: str) -> dict[str, str | None] | None:
    if not level_text:
        return None
    if "国家" in level_text or "全国" in level_text:
        return build_scope("national")

    district = extract_explicit_district(level_text)
    city = extract_explicit_city(level_text)
    province = extract_explicit_province(level_text)

    if district:
        if not city and district in SHENZHEN_DISTRICTS:
            city = "深圳市"
        if not province and city:
            province = infer_province_from_city(city)
        if not province and district in SHENZHEN_DISTRICTS:
            province = "广东省"
        return build_scope("district", district=district, city=city, province=province)

    if "深圳" in level_text or level_text == "市级":
        return build_scope("city", city="深圳市", province="广东省")
    if city:
        return build_scope("city", city=city, province=province or infer_province_from_city(city))

    if "广东" in level_text or level_text == "省级":
        return build_scope("province", province="广东省")
    if province:
        return build_scope("province", province=province)
    return None


def infer_scope_from_title_text(title_text: str) -> dict[str, str | None] | None:
    if not title_text:
        return None
    normalized_title = re.sub(r"^[0-9０-９]{4}(?:[-—至到][0-9０-９]{4})?(?:年|年度)", "", title_text)

    for district in SHENZHEN_DISTRICTS:
        if district in normalized_title:
            return build_scope("district", district=district, city="深圳市", province="广东省")

    city = next((item for item in KNOWN_CITY_TO_PROVINCE if item in normalized_title), None)
    if city:
        return build_scope("city", city=city, province=infer_province_from_city(city))

    province = next((item for item in PROVINCE_NAMES if item in normalized_title), None)
    if province:
        return build_scope("province", province=province)

    if "深圳" in normalized_title:
        return build_scope("city", city="深圳市", province="广东省")
    return None


def infer_region_scope(row: dict[str, str]) -> dict[str, str | None]:
    level_text = clean_text(row.get("级别", ""))
    title_text = clean_text(row.get("项目名称", ""))
    level_scope = infer_scope_from_level_text(level_text)
    title_scope = infer_scope_from_title_text(title_text)
    if level_scope and title_scope:
        if level_scope.get("level") == "national":
            return level_scope
        if scope_priority(title_scope) > scope_priority(level_scope):
            return title_scope
        return level_scope
    return level_scope or title_scope or build_scope("unknown")


def infer_valid_until(text: str) -> str | None:
    value = clean_text(text)
    if not value:
        return None

    direct = try_parse_date(value)
    if direct:
        return direct

    start_match = re.search(r"自(\d{4})年(\d{1,2})月(\d{1,2})日起施行", value)
    year_match = re.search(r"有效期(\d+)年", value)
    if start_match and year_match:
        start = date(int(start_match.group(1)), int(start_match.group(2)), int(start_match.group(3)))
        try:
            return start.replace(year=start.year + int(year_match.group(1))).isoformat()
        except ValueError:
            return start.replace(month=2, day=28, year=start.year + int(year_match.group(1))).isoformat()
    return None


def determine_date_status(row: dict[str, str], today_value: date) -> dict[str, Any]:
    start_text = row.get("申报时间", "")
    deadline_text = row.get("申报截止时间", "")
    valid_text = row.get("文件有效期", "")
    start_iso = try_parse_date(start_text)
    deadline_iso = try_parse_date(deadline_text)
    valid_until = infer_valid_until(valid_text)

    status = "unknown"
    if valid_until and date.fromisoformat(valid_until) < today_value:
        status = "expired"
    elif deadline_iso and date.fromisoformat(deadline_iso) < today_value:
        status = "window_closed"
    elif deadline_iso or valid_until or start_iso:
        status = "active"

    return {
        "start_date": start_iso,
        "deadline": deadline_iso,
        "valid_until": valid_until,
        "status": status,
    }


def normalize_row(row: dict[str, str], row_number: int, today_value: date) -> dict[str, Any]:
    normalized = {column: clean_text(row.get(column, "")) or None for column in DEFAULT_COLUMNS}
    section_hint = infer_section_hint(row)
    region_scope = infer_region_scope(row)
    date_status = determine_date_status(row, today_value)
    text_blob = "\n".join(
        dedupe_texts(
            [
                normalized.get("项目名称") or "",
                normalized.get("项目类型") or "",
                normalized.get("申报对象") or "",
                normalized.get("申报条件") or "",
                normalized.get("解读版") or "",
            ]
        )
    )

    normalized.update(
        {
            "source_row": row_number,
            "section_hint": section_hint,
            "region_scope": region_scope,
            "date_status": date_status,
            "text_blob": text_blob,
        }
    )
    return normalized


def main() -> int:
    args = parse_args()
    rows = read_csv_rows(args.input)
    today_value = date.fromisoformat(args.today)
    normalized = [normalize_row(row, index + 2, today_value) for index, row in enumerate(rows)]
    write_jsonl(args.output, normalized)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
