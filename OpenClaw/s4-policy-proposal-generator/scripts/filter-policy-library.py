#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


DEFAULT_POLICY_JSONL = Path(__file__).resolve().parent.parent / "references" / "policy_list.jsonl"
DEFAULT_TOP_K = 30
DEFAULT_VERIFY_TOP_K = 12
STANDARD_COMPANY_FIELDS = (
    "company_name",
    "registered_capital",
    "registration_date",
    "employee_count",
    "declared_projects",
    "main_business",
    "existing_qualifications",
    "registered_address",
    "intellectual_property",
    "industry",
)

SHENZHEN_DISTRICTS = (
    "福田区",
    "罗湖区",
    "南山区",
    "盐田区",
    "宝安区",
    "龙岗区",
    "龙华区",
    "坪山区",
    "光明区",
    "大鹏新区",
    "前海深港合作区",
)

PROVINCES = (
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

QUALIFICATION_TERMS = ("认定", "入库", "评估", "资格", "资质", "高新技术企业", "专精特新", "科技型中小企业")
ADVANCE_TERMS = ("事前资助", "立项", "揭榜挂帅", "专项资金", "研发资助")
POST_TERMS = ("事后资助", "奖励", "奖补", "补贴", "资助", "兑付")
ENTERPRISE_TERMS = ("企业", "公司", "单位", "法人", "申报单位", "申请单位", "机构")
NEGATIVE_SUBJECT_GROUPS = (
    ("个人", "个人申请", "申请人", "自然人"),
    ("高校", "高等院校", "大学", "学院", "学生", "教师"),
    ("医院", "临床", "医师", "医生", "护理"),
    ("协会", "学会", "联合会"),
    ("科研院所", "研究院", "实验室", "科研机构"),
)

KEYWORD_GROUPS = (
    ("ai", ("人工智能", "AI", "智能体", "知识库", "算法", "模型", "算力", "数字经济"), 0.22),
    ("digital", ("数字化", "信息化", "大数据", "云", "SaaS", "系统集成", "软件"), 0.14),
    ("manufacturing", ("制造", "装备", "自动化", "检测", "产线", "工业", "机器人", "硬件", "技改"), 0.22),
    ("ip", ("专利", "知识产权", "商标", "软著", "著作权"), 0.12),
    ("qualification", ("高新", "专精特新", "科技型中小企业", "认定", "资质"), 0.12),
    ("talent", ("人才", "工匠", "博士后", "工程师", "团队"), 0.08),
    ("space", ("租金", "场地", "园区", "厂房"), 0.05),
)

MONEY_PATTERNS = (
    re.compile(r"(最高[^，。；;\s]{0,24}(?:万元|亿元|万|元))"),
    re.compile(r"((?:\d+(?:\.\d+)?)\s*(?:万元|亿元|万|元))"),
)
DATE_PATTERNS = (
    re.compile(r"(\d{4}[-/.年]\d{1,2}[-/.月]\d{1,2}日?)"),
    re.compile(r"(\d{4}年\d{1,2}月)"),
    re.compile(r"(\d{4}[-/.]\d{1,2})"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Filter local policy library for a standardized company profile.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--company", help="Company profile JSON string.")
    group.add_argument("--company-file", type=Path, help="Path to company profile JSON file.")
    parser.add_argument("--policy-jsonl", type=Path, default=DEFAULT_POLICY_JSONL, help="Policy JSONL path.")
    parser.add_argument("--output", type=Path, required=True, help="Result JSON path.")
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K, help="Retained candidate count.")
    parser.add_argument("--verify-top-k", type=int, default=DEFAULT_VERIFY_TOP_K, help="Candidates eligible for verification.")
    parser.add_argument("--skip-online-verify", action="store_true", help="Skip metainflow verification.")
    return parser.parse_args()


def stringify(value: Any, joiner: str = "；") -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return joiner.join(item for item in (stringify(v, joiner=joiner) for v in value) if item)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value).strip()


def normalize_text(value: Any) -> str:
    return stringify(value).replace("\r\n", "\n").replace("\r", "\n").strip()


def load_company(args: argparse.Namespace) -> dict[str, Any]:
    raw = args.company if args.company is not None else args.company_file.read_text(encoding="utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("企业画像必须是 JSON 对象")
    company = {key: stringify(data.get(key)) for key in STANDARD_COMPANY_FIELDS}
    if "company_identified" in data:
        company["company_identified"] = data["company_identified"]
    return company


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for index, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                row = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"政策库第 {index} 行不是合法 JSON: {exc}") from exc
            if isinstance(row, dict):
                rows.append(row)
    return rows


def company_is_identified(company: dict[str, Any]) -> bool:
    if isinstance(company.get("company_identified"), bool):
        return bool(company["company_identified"])
    company_name = normalize_text(company.get("company_name"))
    return bool(company_name) and "待确认" not in company_name and "候选" not in company_name


def infer_region(company: dict[str, Any]) -> dict[str, str]:
    text = " ".join(normalize_text(company.get(key)) for key in ("registered_address", "industry", "main_business", "company_name"))
    district = next((item for item in SHENZHEN_DISTRICTS if item in text), "")
    province = next((item for item in PROVINCES if item in text), "")
    city = "深圳市" if "深圳" in text or district else ""
    if not province and city == "深圳市":
        province = "广东省"
    return {"district": district, "city": city, "province": province}


def area_level(area_name: str) -> str:
    if not area_name:
        return "unknown"
    if "国家" in area_name:
        return "national"
    if area_name in PROVINCES or area_name.endswith(("省", "自治区", "特别行政区")):
        return "province"
    if area_name in SHENZHEN_DISTRICTS or area_name.endswith("区"):
        return "district"
    if area_name.endswith("市"):
        return "city"
    return "unknown"


def region_match(area_name: str, region: dict[str, str]) -> tuple[bool, float, str]:
    level = area_level(area_name)
    if level == "national":
        return True, 0.55, "国家级"
    if level == "province":
        return (not region["province"] or area_name == region["province"]), 0.60 if not region["province"] or area_name == region["province"] else 0.0, "省级"
    if level == "city":
        return (not region["city"] or area_name == region["city"]), 0.70 if not region["city"] or area_name == region["city"] else 0.0, "市级"
    if level == "district":
        return (bool(region["district"]) and area_name == region["district"]), 0.85 if bool(region["district"]) and area_name == region["district"] else 0.0, "区级"
    return True, 0.45, "地区未明确"


def subject_compatible(text: str) -> bool:
    if any(term in text for term in ENTERPRISE_TERMS):
        return True
    return not any(any(term in text for term in group) for group in NEGATIVE_SUBJECT_GROUPS)


def company_tokens(company: dict[str, Any]) -> list[str]:
    text = "；".join(normalize_text(company.get(key)) for key in ("industry", "main_business", "existing_qualifications", "intellectual_property"))
    tokens = re.split(r"[；;,，/\n\-\s]+", text)
    return [token for token in tokens if len(token) >= 2 and token not in {"待补充", "暂无"}]


def keyword_score(company: dict[str, Any], policy_text: str) -> tuple[float, list[str]]:
    business_text = " ".join(normalize_text(company.get(key)) for key in ("company_name", "industry", "main_business"))
    support_text = " ".join(normalize_text(company.get(key)) for key in ("existing_qualifications", "intellectual_property"))
    score = 0.0
    hits: list[str] = []
    for label, keywords, weight in KEYWORD_GROUPS:
        source_text = support_text if label in {"ip", "qualification"} else business_text
        if any(keyword.lower() in source_text.lower() for keyword in keywords) and any(keyword.lower() in policy_text.lower() for keyword in keywords):
            score += weight
            hits.append(label)
    token_hits = [token for token in company_tokens(company) if token.lower() in policy_text.lower()]
    if token_hits:
        score += min(0.20, len(token_hits) * 0.03)
        hits.extend(token_hits[:4])
    return score, dedupe(hits)


def dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def infer_gaps(company: dict[str, Any], policy_text: str) -> list[str]:
    gaps: list[str] = []
    qualifications = normalize_text(company.get("existing_qualifications"))
    ip = normalize_text(company.get("intellectual_property"))
    if "高新技术企业" in policy_text and "高新" not in qualifications:
        gaps.append("高新技术企业资质")
    if "专精特新" in policy_text and "专精特新" not in qualifications:
        gaps.append("专精特新资质")
    if "科技型中小企业" in policy_text and "科技型中小企业" not in qualifications:
        gaps.append("科技型中小企业入库状态")
    if any(term in policy_text for term in ("发明专利", "专利", "知识产权")) and (not ip or "待补充" in ip):
        gaps.append("知识产权证明")
    if "发明专利" in policy_text and "发明专利" not in ip:
        gaps.append("发明专利数量")
    if any(term in policy_text for term in ("研发投入", "研发费用")):
        gaps.append("研发投入或研发费用数据")
    if any(term in policy_text for term in ("营收", "营业收入", "产值")):
        gaps.append("营收或产值数据")
    if any(term in policy_text for term in ("员工", "社保", "从业人员")) and (not normalize_text(company.get("employee_count")) or "待补充" in normalize_text(company.get("employee_count"))):
        gaps.append("员工或社保人数")
    return dedupe(gaps)


def existing_hit(company: dict[str, Any], title: str) -> bool:
    text = " ".join(normalize_text(company.get(key)) for key in ("declared_projects", "existing_qualifications"))
    if not text or "待补充" in text:
        return False
    return title in text


def classify_category(text: str) -> str:
    return "qualification" if any(term in text for term in QUALIFICATION_TERMS) else "funding"


def classify_project_type(category: str, text: str) -> str:
    if category == "qualification":
        return "认定类"
    if any(term in text for term in ADVANCE_TERMS):
        return "事前资助"
    if any(term in text for term in POST_TERMS):
        return "事后资助"
    return "资助类"


def extract_first(patterns: tuple[re.Pattern[str], ...], text: str, default: str = "") -> str:
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            return match.group(1).strip()
    return default


def company_missing_count(company: dict[str, Any]) -> int:
    tracked = ("registered_capital", "registration_date", "employee_count", "declared_projects", "existing_qualifications", "registered_address", "intellectual_property")
    return sum(1 for key in tracked if not normalize_text(company.get(key)) or "待补充" in normalize_text(company.get(key)))


def status_from(score: float, gaps: list[str], hits: list[str], missing_count: int) -> str:
    if missing_count >= 5:
        return "needs_review"
    if missing_count >= 3 and (gaps or score < 1.0):
        return "needs_review"
    if missing_count >= 2 and score >= 0.72:
        return "conditional"
    if score >= 1.0 and len(gaps) <= 1 and hits:
        return "eligible"
    if score >= 0.72 and len(gaps) <= 3:
        return "conditional"
    return "needs_review"


def status_label(status: str) -> str:
    return {"eligible": "明确匹配", "conditional": "有条件匹配", "needs_review": "需顾问复核"}[status]


def build_match_reason(status: str, region_label: str, hits: list[str], gaps: list[str]) -> str:
    current = f"{region_label}范围匹配" if region_label else "区域方向相关"
    if hits:
        current += f"，且命中关键词：{'、'.join(hits[:5])}"
    missing = "、".join(gaps) if gaps else "暂未识别明显缺口"
    return "\n".join((f"匹配状态：{status_label(status)}", f"当前判断：{current}", f"待补充条件：{missing}"))


def parse_json_payload(text: str) -> Any:
    stripped = text.strip()
    if not stripped:
        return None
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(stripped[start : end + 1])
            except json.JSONDecodeError:
                return None
    return None


def verified_fields(raw: str) -> dict[str, str]:
    payload = parse_json_payload(raw)
    if isinstance(payload, dict):
        candidate = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        values = {key: normalize_text(candidate.get(key)) for key in ("application_time", "funding_amount", "key_conditions", "source_link")}
    else:
        values = {"application_time": "", "funding_amount": "", "key_conditions": "", "source_link": ""}
    text = normalize_text(raw)
    if not values["application_time"]:
        values["application_time"] = extract_first(DATE_PATTERNS, text)
    if not values["funding_amount"]:
        values["funding_amount"] = extract_first(MONEY_PATTERNS, text)
    return values


def run_metainflow(command: list[str]) -> str:
    if shutil.which("metainflow") is None:
        return ""
    try:
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    except OSError:
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def verify_candidate(candidate: dict[str, Any]) -> dict[str, str]:
    instruction = "提取申报时间、资助金额、关键申报条件；不能确认的字段写待确认，不要编造，并输出 json"
    url = normalize_text(candidate.get("detail_url"))
    if url:
        output = run_metainflow(["metainflow", "web-crawl", "--url", url, "--instruction", instruction, "--output", "json"])
        if output:
            return verified_fields(output)
    query = f"{normalize_text(candidate.get('title'))} {normalize_text(candidate.get('area_name'))} 申报时间 申报条件 资助金额".strip()
    output = run_metainflow(["metainflow", "search-summary", "--query", query, "--instruction", instruction, "--output", "json"])
    return verified_fields(output) if output else {"application_time": "", "funding_amount": "", "key_conditions": "", "source_link": ""}


def candidate_from_row(company: dict[str, Any], row: dict[str, Any], region: dict[str, str]) -> dict[str, Any] | None:
    title = normalize_text(row.get("title"))
    conditions = normalize_text(row.get("conditions_preview"))
    area_name = normalize_text(row.get("area_name"))
    dept_name = normalize_text(row.get("dept_name"))
    detail_url = normalize_text(row.get("detail_url"))
    if not title or existing_hit(company, title):
        return None
    compatible, region_score, region_label = region_match(area_name, region)
    if not compatible:
        return None
    full_text = "\n".join(part for part in (title, dept_name, area_name, conditions) if part)
    if not subject_compatible(full_text):
        return None
    keyword_weight, hits = keyword_score(company, full_text.lower())
    if keyword_weight <= 0 and not any(term in full_text for term in ("企业", "科技", "创新", "扶持", "补贴", "资助")):
        return None
    gaps = infer_gaps(company, full_text)
    score = round(region_score + keyword_weight + (0.03 if "专利" in full_text or "资质" in full_text else 0.0), 4)
    status = status_from(score, gaps, hits, company_missing_count(company))
    category = classify_category(full_text)
    candidate = {
        "title": title,
        "dept_name": dept_name or "待确认",
        "area_name": area_name or "待确认",
        "detail_url": detail_url,
        "status": status,
        "status_label": status_label(status),
        "score": score,
        "region_label": region_label,
        "matched_keywords": hits,
        "gaps": gaps,
        "category": category,
        "project_type": classify_project_type(category, full_text),
        "application_time": extract_first(DATE_PATTERNS, full_text, "待确认（需核验时效）"),
        "funding_amount": extract_first(MONEY_PATTERNS, full_text, "待确认"),
        "key_conditions": conditions or "待确认",
        "match_reason": build_match_reason(status, region_label, hits, gaps),
    }
    return candidate


def candidate_sort_key(candidate: dict[str, Any]) -> tuple[int, float]:
    rank = {"eligible": 0, "conditional": 1, "needs_review": 2}.get(candidate["status"], 3)
    return (rank, -float(candidate["score"]))


def project_from_candidate(candidate: dict[str, Any]) -> dict[str, str]:
    return {
        "category": normalize_text(candidate.get("category")),
        "project_name": normalize_text(candidate.get("title")),
        "department": normalize_text(candidate.get("dept_name")) or "待确认",
        "application_time": normalize_text(candidate.get("application_time")) or "待确认（需核验时效）",
        "project_type": normalize_text(candidate.get("project_type")) or "资助类",
        "funding_amount": normalize_text(candidate.get("funding_amount")) or "待确认",
        "key_conditions": normalize_text(candidate.get("key_conditions")) or "待确认",
        "match_reason": normalize_text(candidate.get("match_reason")) or "匹配状态：需顾问复核",
        "source_link": normalize_text(candidate.get("source_link")) or normalize_text(candidate.get("detail_url")) or "待确认",
    }


def main() -> None:
    args = parse_args()
    company = load_company(args)
    if not company_is_identified(company):
        raise ValueError("企业主体尚未唯一识别，不能进入政策筛选")
    rows = read_jsonl(args.policy_jsonl)
    region = infer_region(company)
    candidates = [item for item in (candidate_from_row(company, row, region) for row in rows) if item]
    candidates.sort(key=candidate_sort_key)
    retained = candidates[: max(1, args.top_k)]
    if not args.skip_online_verify:
        for candidate in retained[: min(len(retained), max(0, args.verify_top_k))]:
            if not any(normalize_text(candidate.get(field)).startswith("待确认") or not normalize_text(candidate.get(field)) for field in ("application_time", "funding_amount", "key_conditions")):
                continue
            verified = verify_candidate(candidate)
            for field in ("application_time", "funding_amount", "key_conditions", "source_link"):
                if normalize_text(verified.get(field)):
                    candidate[field] = normalize_text(verified[field])
            candidate["match_reason"] = build_match_reason(candidate["status"], candidate["region_label"], candidate["matched_keywords"], candidate["gaps"])
    result = {"company_profile": company, "retained_candidates": retained, "projects": [project_from_candidate(item) for item in retained]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"政策预筛完成: {args.output}")
    print(json.dumps({"status": "ok", "retained_count": len(retained), "project_count": len(result['projects'])}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"政策预筛失败: {exc}", file=sys.stderr)
        sys.exit(1)
