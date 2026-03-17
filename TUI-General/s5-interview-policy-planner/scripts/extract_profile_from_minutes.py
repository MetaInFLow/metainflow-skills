from __future__ import annotations

import argparse
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from common import (
    clean_text,
    contains_approximation,
    dedupe_texts,
    normalize_string,
    parse_amount_to_wanyuan,
    parse_int,
    parse_percentage,
    try_parse_date,
    write_json,
)


RISK_KEYWORDS = {
    "税务合规风险": ("避税", "私账"),
    "知识产权真实性风险": ("挂靠", "买几个专利"),
    "数据夸大风险": ("快一个亿", "全员皆研发", "常温超导"),
}

HONOR_KEYWORDS = (
    "高新技术企业",
    "专精特新",
    "创新型中小企业",
    "科技型中小企业",
    "制造业单项冠军",
    "瞪羚企业",
)

INDUSTRY_HINTS = (
    ("新能源", ("锂电池", "储能", "电池", "光伏", "氢能")),
    ("新材料", ("新材料", "复合材料", "膜材料", "材料")),
    ("软件与信息服务", ("软件", "平台", "系统", "人工智能", "大数据", "云计算")),
    ("高端装备", ("机器人", "自动化设备", "装备", "数控", "智能制造")),
    ("生物医药", ("医疗", "生物", "药", "器械", "临床")),
)

AMOUNT_WITH_UNIT_PATTERN = r"[0-9一二三四五六七八九十百千万亿两.,]+\s*(?:亿|万元|万|元)"
EMPLOYEE_TRIGGER_PATTERN = (
    r"(?:员工人数|实际员工人数|社保人数|缴纳社保的实际员工人数|正式员工(?:人数)?|交社保的正式工|员工总数)"
)
REVENUE_TRIGGER_PATTERN = (
    r"(?:营收|营业收入|年产值|销售收入|开票(?:销售)?收入|报税(?:的)?(?:应该是)?|报表上(?:体现|登记)?|税务系统里(?:实际申报的)?)"
)


@dataclass
class Turn:
    index: int
    speaker: str
    text: str


@dataclass
class Candidate:
    field: str
    value: Any
    source: str
    text: str
    confidence: float
    notes: list[str] = field(default_factory=list)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract a structured company profile from interview minutes.")
    parser.add_argument("--input", type=Path, required=True, help="Path to minutes or transcript text.")
    parser.add_argument("--output", type=Path, required=True, help="Path to company_profile.json.")
    return parser.parse_args()


def parse_turns(text: str) -> list[Turn]:
    turns: list[Turn] = []
    pattern = re.compile(r"^(?P<speaker>[^：:]{1,30})[：:]\s*(?P<text>.+)$")
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = pattern.match(line)
        if match:
            turns.append(Turn(index=len(turns), speaker=normalize_string(match.group("speaker")), text=match.group("text").strip()))
        elif turns:
            turns[-1].text = f"{turns[-1].text} {line}".strip()
    if turns:
        return turns
    return [Turn(index=0, speaker="纪要", text=clean_text(text))]


def candidate(field: str, value: Any, turn: Turn, confidence: float, notes: list[str] | None = None) -> Candidate:
    return Candidate(field=field, value=value, source=turn.speaker, text=turn.text, confidence=confidence, notes=notes or [])


def normalize_company_name(value: str) -> str:
    cleaned = normalize_string(value)
    cleaned = re.sub(r"^(?:本次填报主体|填报主体|企业主体|公司主体|企业名称|公司名称)(?:是|为)?", "", cleaned)
    return cleaned


def derived_fact(value: Any, confidence: float, note: str, evidence: list[dict[str, str]] | None = None) -> dict[str, Any]:
    return {
        "value": value,
        "status": "derived",
        "confidence": confidence,
        "notes": [note],
        "evidence": evidence or [],
    }


def infer_industry(main_business: Any, main_product: Any) -> str | None:
    corpus = clean_text(" ".join(str(item) for item in (main_business, main_product) if item))
    if not corpus:
        return None
    for industry, keywords in INDUSTRY_HINTS:
        if any(keyword in corpus for keyword in keywords):
            return industry
    return None


def build_ip_summary(facts: dict[str, Any]) -> str | None:
    total = facts.get("patent_count_total", {}).get("value")
    invention = facts.get("patent_count_invention", {}).get("value")
    utility = facts.get("patent_count_utility_model", {}).get("value")
    parts: list[str] = []
    if invention is not None:
        parts.append(f"发明专利{invention}项")
    if utility is not None:
        parts.append(f"实用新型{utility}项")
    if total is not None:
        parts.append(f"专利总数{total}项")
    if not parts:
        return None
    if total == 0 and invention in (None, 0) and utility in (None, 0):
        return "当前未发现已授权专利"
    return "，".join(parts)


def extract_ip_breakdown(text: str) -> dict[str, int | None]:
    patterns = {
        "invention": r"发明专利(?:有|共|拥有)?(?P<value>[0-9一二三四五六七八九十百千万亿两]+)\s*项",
        "utility": r"实用新型(?:专利)?(?:有|共|拥有)?(?P<value>[0-9一二三四五六七八九十百千万亿两]+)\s*项",
        "design": r"外观(?:设计)?专利(?:有|共|拥有)?(?P<value>[0-9一二三四五六七八九十百千万亿两]+)\s*项",
    }
    values: dict[str, int | None] = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, text)
        values[key] = parse_int(match.group("value")) if match else None
    return values


def candidate_note_priority(item: Candidate) -> int:
    if any("更正" in note or "核验" in note for note in item.notes):
        return 2
    if "近似值" in item.notes:
        return 0
    return 1


def collect_candidates(turns: list[Turn]) -> dict[str, list[Candidate]]:
    result: dict[str, list[Candidate]] = {}

    def add(item: Candidate | None) -> None:
        if item is None or item.value in (None, ""):
            return
        result.setdefault(item.field, []).append(item)

    for turn in turns:
        text = turn.text

        name_match = re.search(r"[“\"]?(?P<value>[^”“\"，。；]{4,40}(?:有限公司|股份有限公司|有限责任公司))[”\"]?", text)
        if name_match:
            add(candidate("enterprise_name", normalize_company_name(name_match.group("value")), turn, 0.92))

        add_match = re.search(r"(?:注册地|注册地址|办公地址|地址)(?:是|为)?(?P<value>深圳市[^，。；]+)", text)
        if add_match:
            value = normalize_string(add_match.group("value"))
            add(candidate("address", value, turn, 0.9))
            district_match = re.search(r"(南山区|宝安区|龙华区|罗湖区|福田区|龙岗区|盐田区|坪山区|光明区|大鹏新区|深汕特别合作区)", value)
            if district_match:
                add(candidate("region", f"深圳市{district_match.group(1)}", turn, 0.85))

        capital_match = re.search(r"(?:注册资本|注册资金)[^0-9一二三四五六七八九十百千万亿两]*(?P<value>[0-9一二三四五六七八九十百千万亿两.,]+\s*(?:个\s*)?(?:亿|万|元)?)", text)
        if capital_match:
            add(candidate("registered_capital_wanyuan", parse_amount_to_wanyuan(capital_match.group("value")), turn, 0.88))

        date_match = re.search(r"(?:注册时间|成立于|成立时间)[^0-9]*(?P<value>\d{4}[/-]\d{1,2}[/-]\d{1,2}|\d{4}年\d{1,2}月\d{1,2}日)", text)
        if date_match:
            add(candidate("registered_date", try_parse_date(date_match.group("value")), turn, 0.86))

        emp_match = re.search(
            rf"(?:{EMPLOYEE_TRIGGER_PATTERN}|五十多号人)[^0-9一二三四五六七八九十百千万亿两]{{0,12}}(?P<value>[0-9一二三四五六七八九十百千万亿两]+)\s*人",
            text,
        )
        if emp_match:
            notes = ["近似值"] if contains_approximation(text) else []
            add(candidate("employee_count", parse_int(emp_match.group("value")), turn, 0.84, notes))

        no_project_match = re.search(r"(?:已申报项目|申报项目|项目申报).{0,10}(?:暂无|没有|未申报|还没申报)", text)
        if no_project_match or ("没申报过" in text and "项目" in text):
            add(candidate("applied_projects", "暂无", turn, 0.84))
        project_match = re.search(r"(?:已申报项目|申报过(?:的)?项目|曾申报(?:过)?|以前申报过)(?:是|为|包括|主要包括)?(?P<value>[^。；]{2,120})", text)
        if project_match:
            add(candidate("applied_projects", normalize_string(project_match.group("value")), turn, 0.8))

        exact_emp = re.search(r"按(?P<value>\d+)\s*万写", text)
        if exact_emp and "营收" in (turns[max(turn.index - 1, 0)].text if turns else ""):
            add(candidate("annual_output_wanyuan", parse_amount_to_wanyuan(exact_emp.group("value") + "万"), turn, 0.95, ["按纠正值登记"]))

        rd_staff_corrected = re.search(r"(?:专职研发人员|研发人员).{0,12}(?:更正为|按|算)\s*(?P<value>[0-9一二三四五六七八九十百千万亿两]+)\s*人", text)
        if rd_staff_corrected:
            add(candidate("rd_staff_count", parse_int(rd_staff_corrected.group("value")), turn, 0.92, ["按纠正值登记"]))
        rd_staff = re.search(r"(?:研发(?:部门|团队|人员)|专职研发人员)[^0-9一二三四五六七八九十百千万亿两]*(?P<value>[0-9一二三四五六七八九十百千万亿两]+)\s*人", text)
        if rd_staff:
            notes = ["近似值"] if contains_approximation(text) else []
            add(candidate("rd_staff_count", parse_int(rd_staff.group("value")), turn, 0.86, notes))

        revenue_match = re.search(
            rf"{REVENUE_TRIGGER_PATTERN}[^0-9一二三四五六七八九十百千万亿两%]{{0,12}}(?P<value>{AMOUNT_WITH_UNIT_PATTERN})",
            text,
        )
        if revenue_match:
            notes = ["近似值"] if contains_approximation(text) else []
            add(candidate("annual_output_wanyuan", parse_amount_to_wanyuan(revenue_match.group("value")), turn, 0.85, notes))

        main_product_match = re.search(r"(?:主要产品(?:我为您客观修改为|更正为)|主营产品(?:是|为)?|主打产品(?:是|为)?|实际产品(?:其实)?(?:是|为)?)\s*[“\"]?(?P<value>[^”“\"，。；]{2,40})[”\"]?", text)
        if not main_product_match:
            main_product_match = re.search(r"(?:主要产品|主营产品|主打产品)(?:填写的是|是|为)\s*[“\"]?(?P<value>[^”“\"，。；]{2,40})[”\"]?", text)
        if not main_product_match:
            main_product_match = re.search(r"(?:当前|目前)主要产品(?:包括|有)\s*[“\"]?(?P<value>[^”“\"。；]{2,80})[”\"]?", text)
        if main_product_match:
            normalized_value = normalize_string(main_product_match.group("value"))
            add(candidate("main_product", normalized_value, turn, 0.87))
            add(candidate("main_business", normalized_value, turn, 0.72, ["由主要产品近似映射"]))

        business_match = re.search(r"(?:主营业务(?:及产品)?|公司主营业务(?:及产品)?|公司主营业务|主营方向|实际业务|目前业务|主要业务)(?:我为您客观修改为|是|为|主要是|主要做|为主|包括)\s*(?P<value>[^。；]{2,120})", text)
        if business_match:
            add(candidate("main_business", normalize_string(business_match.group("value")), turn, 0.86))

        industry_match = re.search(r"(?:所属行业|行业归类|所属赛道|行业方向)(?:是|为|属于)\s*(?P<value>[^，。；]{2,40})", text)
        if industry_match:
            add(candidate("industry", normalize_string(industry_match.group("value")), turn, 0.82))

        invention_match = re.search(r"发明专利(?:有|填报了)?(?P<value>[0-9一二三四五六七八九十百千万亿两]+)\s*项", text)
        if invention_match:
            add(candidate("patent_count_invention", parse_int(invention_match.group("value")), turn, 0.82))
        invention_zero = re.search(r"发明专利[^。；\n]{0,16}(?:数量)?(?:为|是)?\s*0(?!\d)", text)
        if invention_zero:
            add(candidate("patent_count_invention", 0, turn, 0.9, ["按访谈确认归零"]))
        utility_match = re.search(r"实用新型(?:专利)?(?:有)?(?P<value>[0-9一二三四五六七八九十百千万亿两]+)\s*项", text)
        if utility_match:
            add(candidate("patent_count_utility_model", parse_int(utility_match.group("value")), turn, 0.82))
        utility_zero = re.search(r"实用新型(?:专利)?[^。；\n]{0,16}(?:数量)?(?:为|是)?\s*0(?!\d)", text)
        if utility_zero:
            add(candidate("patent_count_utility_model", 0, turn, 0.9, ["按访谈确认归零"]))
        total_patent = re.search(
            r"(?:专利总数|专利数量|知识产权(?:数量|总数)?|已授权的到底有几项|总计|合计|共计|更正为)(?:是|为|有|共)?(?P<value>[0-9一二三四五六七八九十百千万亿两]+)\s*项",
            text,
        )
        if total_patent:
            add(candidate("patent_count_total", parse_int(total_patent.group("value")), turn, 0.83))
        zero_patent = re.search(r"专利数量更正为(?P<value>0)", text)
        if zero_patent:
            add(candidate("patent_count_total", 0, turn, 0.95, ["按系统核验更正"]))

        ip_match = None
        if "请问" not in text and "核实" not in text:
            ip_match = re.search(r"(?:知识产权(?:情况)?|专利情况)(?:是|为|包括|有|如下)\s*[“\"]?(?P<value>[^”“\"。；]{2,80})[”\"]?", text)
        if ip_match:
            add(candidate("ip_summary", normalize_string(ip_match.group("value")), turn, 0.8))

        high_tech = re.search(r"(?:高新技术企业|高新企业).*(已通过|通过了|有效期内|未通过|不是)", text)
        if high_tech:
            token = high_tech.group(1)
            add(candidate("high_tech_enterprise", token not in ("未通过", "不是"), turn, 0.88))
        high_tech_negative = re.search(r"(?:不符合|不满足).{0,8}高新技术企业|高新技术企业.{0,12}(?:不符合|不满足)", text)
        if high_tech_negative:
            add(candidate("high_tech_enterprise", False, turn, 0.8, ["按访谈口径判定当前不满足高企要求"]))

        honor_hits = [keyword for keyword in HONOR_KEYWORDS if keyword in text]
        if honor_hits:
            add(candidate("honors", "、".join(honor_hits), turn, 0.78))

        rd_ratio = re.search(r"(?:研发投入(?:占比)?|研发费用)[^0-9]*(?P<value>\d+(?:\.\d+)?\s*%(?:\s*(?:到|至|-|~)\s*\d+(?:\.\d+)?\s*%)?)", text)
        if rd_ratio:
            notes = ["近似值"] if contains_approximation(text) else []
            add(candidate("rd_ratio_pct", parse_percentage(rd_ratio.group("value")), turn, 0.84, notes))
        elif "研发投入" in text and any(token in text for token in ("0", "没有", "一项都没有")):
            add(candidate("rd_ratio_pct", 0, turn, 0.78))

        contact = re.search(r"(?:联系(?:谁|人)?|直接联系(?:我们)?|行政总监)(?P<value>[^，。；]*?(?:先生|女士|总))", text)
        if contact:
            add(candidate("contact_person", normalize_string(contact.group("value")), turn, 0.86))

        phone = re.search(r"(?P<value>1[3-9][0-9Xx\-\*]{9,})", text)
        if phone:
            add(candidate("contact_phone", clean_text(phone.group("value")).replace(" ", ""), turn, 0.9))

        email = re.search(r"(?P<value>[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})", text)
        if email:
            add(candidate("contact_email", clean_text(email.group("value")), turn, 0.9))

    return result


def pick_best(field_name: str, candidates: list[Candidate]) -> Candidate | None:
    if not candidates:
        return None
    ranked = sorted(
        enumerate(candidates),
        key=lambda item: (candidate_note_priority(item[1]), item[1].confidence, item[0]),
        reverse=True,
    )
    if field_name in {"annual_output_wanyuan", "employee_count", "rd_staff_count", "patent_count_total"}:
        return ranked[0][1]
    return ranked[0][1]


def summarize_candidates(field_name: str, candidates: list[Candidate]) -> dict[str, Any]:
    best = pick_best(field_name, candidates)
    if best is None:
        return {
            "value": None,
            "status": "missing",
            "confidence": 0.0,
            "notes": [],
            "evidence": [],
        }
    return {
        "value": best.value,
        "status": "confirmed" if "近似值" not in best.notes else "approximate",
        "confidence": round(best.confidence, 2),
        "notes": dedupe_texts(best.notes),
        "evidence": [{"source": best.source, "text": best.text}],
    }


def build_risk_flags(turns: list[Turn], facts: dict[str, Any], candidates_map: dict[str, list[Candidate]]) -> list[dict[str, str]]:
    flags: list[dict[str, str]] = []
    full_text = "\n".join(turn.text for turn in turns)
    for label, keywords in RISK_KEYWORDS.items():
        if any(keyword in full_text for keyword in keywords):
            flags.append({"field": "global", "severity": "high", "reason": label})

    for field_name, candidates in candidates_map.items():
        distinct_values = {str(item.value) for item in candidates if item.value is not None}
        if len(distinct_values) >= 2:
            flags.append(
                {
                    "field": field_name,
                    "severity": "medium",
                    "reason": f"{field_name} 存在多次不同口径，已按后续更明确值保守处理。",
                }
            )
    if facts.get("rd_staff_count", {}).get("value") and facts.get("employee_count", {}).get("value"):
        if facts["rd_staff_count"]["value"] > facts["employee_count"]["value"]:
            flags.append({"field": "rd_staff_count", "severity": "high", "reason": "研发人员数量高于员工总数。"})
    return flags


def main() -> int:
    args = parse_args()
    text = args.input.read_text(encoding="utf-8").strip()
    turns = parse_turns(text)
    candidates_map = collect_candidates(turns)
    ip_breakdown = extract_ip_breakdown(text)
    facts = {field: summarize_candidates(field, candidates_map.get(field, [])) for field in {
        "enterprise_name",
        "region",
        "address",
        "registered_date",
        "registered_capital_wanyuan",
        "employee_count",
        "applied_projects",
        "main_business",
        "honors",
        "ip_summary",
        "industry",
        "rd_staff_count",
        "annual_output_wanyuan",
        "rd_ratio_pct",
        "patent_count_total",
        "patent_count_invention",
        "patent_count_utility_model",
        "high_tech_enterprise",
        "main_product",
        "contact_person",
        "contact_phone",
        "contact_email",
    }}

    inv = facts["patent_count_invention"]["value"] or ip_breakdown.get("invention") or 0
    uti = facts["patent_count_utility_model"]["value"] or ip_breakdown.get("utility") or 0
    design = ip_breakdown.get("design") or 0
    derived_patent_total = inv + uti + design
    current_patent_total = facts["patent_count_total"]["value"]
    if derived_patent_total and (current_patent_total is None or int(current_patent_total) < derived_patent_total):
        ip_evidence = [
            {"source": turn.speaker, "text": turn.text}
            for turn in turns
            if any(token in turn.text for token in ("发明专利", "实用新型", "外观专利"))
        ]
        facts["patent_count_total"] = {
            "value": derived_patent_total,
            "status": "derived",
            "confidence": 0.84,
            "notes": ["由发明专利、实用新型和外观专利数量汇总修正"],
            "evidence": ip_evidence or (facts["patent_count_invention"]["evidence"] + facts["patent_count_utility_model"]["evidence"]),
        }

    if facts["main_business"]["value"] is None and facts["main_product"]["value"] is not None:
        facts["main_business"] = derived_fact(
            facts["main_product"]["value"],
            0.72,
            "由主要产品近似映射为主营业务",
            facts["main_product"]["evidence"],
        )

    if facts["industry"]["value"] is None:
        derived_industry = infer_industry(facts["main_business"]["value"], facts["main_product"]["value"])
        if derived_industry:
            evidence = facts["main_business"]["evidence"] + facts["main_product"]["evidence"]
            facts["industry"] = derived_fact(derived_industry, 0.68, "根据主营业务和主要产品推断所属行业", evidence)

    if facts["honors"]["value"] is None and facts["high_tech_enterprise"]["value"] is True:
        facts["honors"] = derived_fact("高新技术企业", 0.76, "由高新技术企业状态推导企业资质荣誉", facts["high_tech_enterprise"]["evidence"])

    if facts["ip_summary"]["value"] is None:
        summary = build_ip_summary(facts)
        if summary:
            evidence = (
                facts["patent_count_total"]["evidence"]
                + facts["patent_count_invention"]["evidence"]
                + facts["patent_count_utility_model"]["evidence"]
            )
            facts["ip_summary"] = derived_fact(summary, 0.8, "根据知识产权数量字段汇总生成", evidence)

    missing_fields = [name for name, record in facts.items() if record["value"] is None]
    risk_flags = build_risk_flags(turns, facts, candidates_map)
    evidence = []
    for field_name, record in facts.items():
        for item in record["evidence"]:
            evidence.append({"field": field_name, "text": item["text"], "source": item["source"]})

    payload = {
        "facts": facts,
        "missing_fields": missing_fields,
        "risk_flags": risk_flags,
        "evidence": evidence,
    }
    write_json(args.output, payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
