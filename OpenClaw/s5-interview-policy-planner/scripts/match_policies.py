from __future__ import annotations

import argparse
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from common import (
    FIT_STATUS_CONDITIONAL,
    FIT_STATUS_ELIGIBLE,
    FIT_STATUS_INSUFFICIENT_EVIDENCE,
    FIT_STATUS_NOT_FIT,
    clean_text,
    infer_district,
    read_jsonl,
    stringify_value,
    write_json,
)


FIELD_LABELS = {
    "enterprise_name": "企业名称",
    "region": "所属地区",
    "address": "办公地址",
    "registered_date": "注册时间",
    "registered_capital_wanyuan": "注册资本",
    "employee_count": "员工人数",
    "rd_staff_count": "研发人员数量",
    "annual_output_wanyuan": "营业收入/年产值",
    "rd_ratio_pct": "研发投入占比",
    "patent_count_total": "专利总数",
    "patent_count_invention": "发明专利数量",
    "high_tech_enterprise": "高新技术企业状态",
    "main_product": "主要产品",
}


KEYWORD_GROUPS = {
    "制造": {
        "keywords": ("制造", "智能制造", "生产制造", "硬件", "电子产品", "电子设备", "工业设备", "工艺", "材料"),
        "weight": 0.04,
        "require_primary": True,
    },
    "设计": {
        "keywords": ("工业设计", "外观设计", "产品设计", "设计研发"),
        "weight": 0.02,
        "require_primary": True,
    },
    "知识产权": {
        "keywords": ("专利", "知识产权", "商标", "版权", "标准"),
        "weight": 0.06,
        "require_primary": False,
    },
    "数字化": {
        "keywords": ("软件", "数字化", "信息化", "人工智能", "大数据", "云计算", "算法"),
        "weight": 0.06,
        "require_primary": False,
    },
}

STRICT_DOMAIN_KEYWORDS = {
    "建筑工程": ("建筑", "工程建设", "施工", "BIM", "装配式", "绿色建筑"),
    "生物医疗": ("医疗器械", "生物技术", "新药", "中成药", "临床"),
    "农业": ("农业", "种植", "农产品", "渔业"),
    "文旅演艺": ("旅游", "演艺", "景区", "文化企业", "文旅", "数字文娱"),
    "时尚消费": ("时尚", "服装", "珠宝", "皮革", "眼镜", "化妆品"),
    "人才专项": ("博士后", "高层次人才", "优秀青年人才", "人才培育", "引才"),
}

TOP_CONTEXT_FIELDS = {
    "enterprise_name",
    "registered_capital_wanyuan",
    "registered_date",
    "employee_count",
    "applied_projects",
    "main_business",
    "honors",
    "address",
    "ip_summary",
    "industry",
}

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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Match a company profile against normalized policy rows.")
    parser.add_argument("--profile", type=Path, required=True, help="Path to company_profile.json.")
    parser.add_argument("--policy-jsonl", type=Path, required=True, help="Path to normalized policy JSONL.")
    parser.add_argument("--template-profile", type=Path, required=True, help="Path to template profile JSON.")
    parser.add_argument("--output", type=Path, required=True, help="Path to policy_matches.json.")
    parser.add_argument("--today", default=date.today().isoformat(), help="ISO date for date comparisons.")
    return parser.parse_args()


def excel_context_value(profile: dict[str, Any], field_name: str) -> Any:
    return profile.get("excel_context", {}).get(field_name, {}).get("value")


def transcript_fact_value(profile: dict[str, Any], field_name: str) -> Any:
    return profile.get("transcript_facts", {}).get(field_name, {}).get("value")


def effective_value(profile: dict[str, Any], field_name: str) -> Any:
    if field_name in TOP_CONTEXT_FIELDS:
        return excel_context_value(profile, field_name)
    return transcript_fact_value(profile, field_name)


def infer_city(text: Any) -> str | None:
    value = clean_text(str(text or ""))
    if not value:
        return None
    for city in KNOWN_CITY_TO_PROVINCE:
        if city in value:
            return city
    if infer_district(value):
        return "深圳市"
    match = re.search(r"([一-龥]{2,7}市)", value)
    if not match:
        return None
    candidate = match.group(1)
    if candidate in GENERIC_CITY_TERMS:
        return None
    return candidate


def infer_province(text: Any, city: str | None = None) -> str | None:
    value = clean_text(str(text or ""))
    for province in PROVINCE_NAMES:
        if province in value:
            return province
    return KNOWN_CITY_TO_PROVINCE.get(city)


def company_context(profile: dict[str, Any]) -> dict[str, Any]:
    address = excel_context_value(profile, "address")
    industry = excel_context_value(profile, "industry")
    enterprise_name = excel_context_value(profile, "enterprise_name")
    district = infer_district(address or industry or enterprise_name)
    city = infer_city(address or industry or enterprise_name)
    if not city and district:
        city = "深圳市"
    province = infer_province(address or industry or enterprise_name, city=city)
    region = district or city or province
    return {
        "enterprise_name": enterprise_name,
        "region": region,
        "province": province,
        "city": city,
        "district": district,
        "address": address,
        "registered_date": excel_context_value(profile, "registered_date"),
        "registered_capital_wanyuan": excel_context_value(profile, "registered_capital_wanyuan"),
        "employee_count": excel_context_value(profile, "employee_count"),
        "rd_staff_count": effective_value(profile, "rd_staff_count"),
        "annual_output_wanyuan": effective_value(profile, "annual_output_wanyuan"),
        "rd_ratio_pct": effective_value(profile, "rd_ratio_pct"),
        "patent_count_total": effective_value(profile, "patent_count_total"),
        "patent_count_invention": effective_value(profile, "patent_count_invention"),
        "high_tech_enterprise": effective_value(profile, "high_tech_enterprise"),
        "main_product": effective_value(profile, "main_product"),
        "main_business": excel_context_value(profile, "main_business"),
        "industry": industry,
        "honors": excel_context_value(profile, "honors"),
        "ip_summary": excel_context_value(profile, "ip_summary"),
        "applied_projects": excel_context_value(profile, "applied_projects"),
    }


def policy_target_section(policy: dict[str, Any], template_profile: dict[str, Any]) -> str | None:
    for section in template_profile["sections"]:
        if section["section_hint"] == policy["section_hint"]:
            return section["name"]
    return None


def is_policy_region_compatible(policy: dict[str, Any], ctx: dict[str, Any]) -> bool:
    region_scope = policy.get("region_scope", {})
    level = region_scope.get("level")
    if level in {None, "unknown", "national"}:
        return True

    company_province = ctx.get("province")
    company_city = ctx.get("city")
    company_district = ctx.get("district")
    policy_province = region_scope.get("province")
    policy_city = region_scope.get("city")
    policy_district = region_scope.get("district")

    if level == "province":
        if policy_province and company_province and policy_province != company_province:
            return False
        return True

    if level == "city":
        if policy_city and company_city and policy_city != company_city:
            return False
        if not policy_city and policy_province and company_province and policy_province != company_province:
            return False
        return True

    if level == "district":
        if policy_city and company_city and policy_city != company_city:
            return False
        if not policy_city and policy_province and company_province and policy_province != company_province:
            return False
        if policy_district and company_district and policy_city == company_city and policy_district != company_district:
            return False
        return True

    return True


def extract_company_age_years(ctx: dict[str, Any], today_value: date) -> int | None:
    registered_date = ctx.get("registered_date")
    if not registered_date:
        return None
    try:
        start = datetime.fromisoformat(str(registered_date)).date()
    except ValueError:
        return None
    return today_value.year - start.year - ((today_value.month, today_value.day) < (start.month, start.day))


def extract_required_years(text: str) -> int | None:
    match = re.search(r"(?:成立|经营|设立|从事相关领域|深耕[^，。；]{0,10})(?:满|达到)?\s*(\d+)\s*年", text)
    return int(match.group(1)) if match else None


def extract_min_revenue(text: str) -> float | None:
    matches = re.findall(r"(?:营收|营业收入|主营业务收入|销售收入)[^0-9]{0,20}(\d+(?:\.\d+)?)\s*(亿|万元|万|元)", text)
    values: list[float] = []
    for raw, unit in matches:
        number = float(raw)
        if unit == "亿":
            values.append(number * 10000)
        elif unit in ("万", "万元"):
            values.append(number)
        else:
            values.append(number / 10000)
    return min(values) if values else None


def extract_min_ratio(text: str) -> float | None:
    ratio_patterns = (
        r"(?:研发(?:投入|费用|经费)[^。；\n]{0,24}?(?:占(?:主营业务收入|主营收入|营业收入(?:总额)?|收入)?(?:比重|比例)|占比|比重|比例)[^0-9]{0,6}?)(\d+(?:\.\d+)?)\s*%",
        r"(?:研究开发经费[^。；\n]{0,24}?(?:占(?:主营业务收入|主营收入|营业收入(?:总额)?|收入)?(?:比重|比例)|占比|比重|比例)[^0-9]{0,6}?)(\d+(?:\.\d+)?)\s*%",
        r"(?:研发投入占比|研发经费占主营收入比重|研发费用占营业收入总额比重)[^0-9]{0,6}?(\d+(?:\.\d+)?)\s*%",
    )
    ratios: list[float] = []
    for pattern in ratio_patterns:
        ratios.extend(float(item) for item in re.findall(pattern, text))
    return min(ratios) if ratios else None


def extract_min_invention_patents(text: str) -> int | None:
    match = re.search(r"(?:发明专利|Ⅰ 类知识产权)[^0-9]{0,12}(\d+)\s*项", text)
    return int(match.group(1)) if match else None


def extract_min_total_patents(text: str) -> int | None:
    match = re.search(r"(?:专利|知识产权)[^0-9]{0,12}(\d+)\s*项", text)
    return int(match.group(1)) if match else None


def extract_min_employee(text: str) -> int | None:
    match = re.search(r"(?:从业人员|员工|职工总数|企业职工总数|专业人员不少于)(\d+)\s*人", text)
    return int(match.group(1)) if match else None


def is_explicit_high_tech_required(text: str) -> bool:
    return bool(re.search(r"(?:应为|须为|需为).{0,8}高新技术企业", text))


def keyword_score(ctx: dict[str, Any], policy_text: str) -> tuple[float, list[str], list[str]]:
    primary_corpus = " ".join(clean_text(ctx.get(key, "")) for key in ("main_product", "main_business", "industry"))
    extended_corpus = " ".join(clean_text(ctx.get(key, "")) for key in ("main_product", "main_business", "industry", "honors", "ip_summary"))
    score = 0.0
    reasons: list[str] = []
    matched_groups: list[str] = []
    for group, config in KEYWORD_GROUPS.items():
        keywords = config["keywords"]
        company_corpus = primary_corpus if config.get("require_primary") else extended_corpus
        if any(keyword in company_corpus for keyword in keywords) and any(keyword in policy_text for keyword in keywords):
            score += float(config["weight"])
            matched_groups.append(group)
            reasons.append(f"企业画像与政策在“{group}”方向有明显重合")
    return score, reasons, matched_groups


def policy_focus_text(policy: dict[str, Any]) -> str:
    return "\n".join(
        filter(
            None,
            [
                policy.get("项目名称"),
                policy.get("项目类型"),
                policy.get("支持方式"),
            ],
        )
    )


def strict_domain_mismatch(ctx: dict[str, Any], policy_text: str) -> str | None:
    company_text = " ".join(clean_text(ctx.get(key, "")) for key in ("main_product", "main_business", "industry", "honors"))
    for domain_name, keywords in STRICT_DOMAIN_KEYWORDS.items():
        if any(keyword in policy_text for keyword in keywords) and not any(keyword in company_text for keyword in keywords):
            return domain_name
    return None


def has_structured_rule_signal(
    required_years: int | None,
    revenue_min: float | None,
    ratio_min: float | None,
    invention_min: int | None,
    patents_min: int | None,
    employee_min: int | None,
    high_tech_required: bool,
) -> bool:
    return any(
        value is not None
        for value in (required_years, revenue_min, ratio_min, invention_min, patents_min, employee_min)
    ) or high_tech_required


def should_keep_review_candidate(
    score: float,
    matched_clauses: list[str],
    missing_evidence: list[str],
    gap_clauses: list[str],
    has_structured_rule: bool,
    direct_product_hit: bool,
    has_domain_mismatch: bool,
) -> bool:
    if has_domain_mismatch:
        return score >= 0.38 and (matched_clauses or direct_product_hit or has_structured_rule)
    if matched_clauses or direct_product_hit:
        return score >= 0.35
    if has_structured_rule and (missing_evidence or gap_clauses):
        return score >= 0.32
    if gap_clauses:
        return score >= 0.30
    return False


def should_keep_preview_candidate(
    score: float,
    matched_clauses: list[str],
    missing_evidence: list[str],
    gap_clauses: list[str],
    keyword_groups: list[str],
    has_domain_mismatch: bool,
) -> bool:
    if has_domain_mismatch:
        return False
    if score >= 0.30:
        return True
    if matched_clauses or missing_evidence or gap_clauses:
        return True
    return len(keyword_groups) >= 2


def evaluate_policy(policy: dict[str, Any], ctx: dict[str, Any], today_value: date, section_name: str | None) -> dict[str, Any]:
    reasons: list[str] = []
    missing_evidence: list[str] = []
    matched_clauses: list[str] = []
    gap_clauses: list[str] = []
    hard_fail_reasons: list[str] = []
    score = 0.15 if section_name else 0.0
    conditions = clean_text(policy.get("申报条件") or "")
    policy_text = "\n".join(filter(None, [policy.get("项目名称"), policy.get("申报对象"), policy.get("申报条件"), policy.get("解读版")]))
    direct_product_hit = False

    region_scope = policy.get("region_scope", {})
    if region_scope.get("level") == "district":
        if ctx.get("district") and ctx["district"] != region_scope.get("district"):
            hard_fail_reasons.append(f"地区不匹配：政策限定 {region_scope.get('district')}")
        elif not ctx.get("district"):
            missing_evidence.append("企业所在区")
        else:
            matched_clauses.append(f"地区符合 {region_scope.get('district')}")
            score += 0.08
    elif region_scope.get("level") in {"city", "province", "national"}:
        score += 0.05

    company_age = extract_company_age_years(ctx, today_value)
    required_years = extract_required_years(conditions)
    if required_years:
        if company_age is None:
            missing_evidence.append("注册时间")
        elif company_age < required_years:
            gap_clauses.append(f"成立年限暂未达到 {required_years} 年")
        else:
            matched_clauses.append(f"成立年限满足 {required_years} 年")
            score += 0.08

    revenue_min = extract_min_revenue(conditions)
    company_revenue = ctx.get("annual_output_wanyuan")
    if revenue_min:
        if company_revenue is None:
            missing_evidence.append("营业收入/年产值")
        elif float(company_revenue) < float(revenue_min):
            gap_clauses.append(f"营业收入暂未达到 {int(revenue_min)} 万元门槛")
        else:
            matched_clauses.append(f"营业收入满足 {int(revenue_min)} 万元门槛")
            score += 0.15

    ratio_min = extract_min_ratio(conditions)
    company_ratio = ctx.get("rd_ratio_pct")
    if ratio_min:
        if company_ratio is None:
            missing_evidence.append("研发投入占比")
        elif float(company_ratio) < float(ratio_min):
            gap_clauses.append(f"研发投入占比暂未达到 {ratio_min}%")
        else:
            matched_clauses.append(f"研发投入占比满足 {ratio_min}%")
            score += 0.08

    invention_min = extract_min_invention_patents(conditions)
    invention_value = ctx.get("patent_count_invention")
    if invention_min:
        if invention_value is None:
            missing_evidence.append("发明专利数量")
        elif int(invention_value) < invention_min:
            gap_clauses.append(f"发明专利数量暂未达到 {invention_min} 项")
        else:
            matched_clauses.append(f"发明专利数量满足 {invention_min} 项")
            score += 0.08

    patents_min = extract_min_total_patents(conditions)
    patent_total = ctx.get("patent_count_total")
    if patents_min:
        if patent_total is None:
            missing_evidence.append("专利/知识产权数量")
        elif int(patent_total) < patents_min:
            gap_clauses.append(f"知识产权数量暂未达到 {patents_min} 项")
        else:
            matched_clauses.append(f"知识产权数量满足 {patents_min} 项")
            score += 0.05

    employee_min = extract_min_employee(conditions)
    employees = ctx.get("employee_count")
    if employee_min:
        if employees is None:
            missing_evidence.append("员工人数")
        elif int(employees) < employee_min:
            gap_clauses.append(f"员工人数暂未达到 {employee_min} 人")
        else:
            matched_clauses.append(f"员工人数满足 {employee_min} 人")
            score += 0.04

    high_tech_required = is_explicit_high_tech_required(conditions)
    if high_tech_required:
        if ctx.get("high_tech_enterprise") is None:
            missing_evidence.append("高新技术企业状态")
        elif not ctx["high_tech_enterprise"]:
            gap_clauses.append("当前未具备高新技术企业资质")
        else:
            matched_clauses.append("具备高新技术企业资质")
            score += 0.05

    if ctx.get("main_product") and ctx["main_product"] in policy_text:
        score += 0.05
        direct_product_hit = True
        matched_clauses.append("政策文本与主要产品直接相关")

    kw_score, kw_reasons, keyword_groups = keyword_score(ctx, policy_text)
    score += kw_score
    reasons.extend(kw_reasons)

    mismatched_domain = strict_domain_mismatch(ctx, policy_focus_text(policy))
    has_domain_mismatch = bool(mismatched_domain)
    if mismatched_domain:
        gap_clauses.append(f"政策偏向“{mismatched_domain}”领域，需人工复核主营相关性")

    if ctx.get("district") and policy_text and "深圳市" in policy_text and ctx["district"] not in policy_text and region_scope.get("level") == "district":
        hard_fail_reasons.append("政策适用辖区与企业所在区不一致")

    score = min(score, 0.95)
    missing_evidence = list(dict.fromkeys(missing_evidence))
    has_structured_rule = has_structured_rule_signal(
        required_years,
        revenue_min,
        ratio_min,
        invention_min,
        patents_min,
        employee_min,
        high_tech_required,
    )
    keep_review_candidate = should_keep_review_candidate(
        score,
        matched_clauses,
        missing_evidence,
        gap_clauses,
        has_structured_rule,
        direct_product_hit,
        has_domain_mismatch,
    )
    keep_preview_candidate = (
        not hard_fail_reasons
        and not keep_review_candidate
        and should_keep_preview_candidate(score, matched_clauses, missing_evidence, gap_clauses, keyword_groups, has_domain_mismatch)
    )
    if hard_fail_reasons:
        fit_status = FIT_STATUS_NOT_FIT
    elif not gap_clauses and score >= 0.72 and len(missing_evidence) <= 2 and len(matched_clauses) >= 2:
        fit_status = FIT_STATUS_ELIGIBLE
    elif has_domain_mismatch:
        fit_status = FIT_STATUS_INSUFFICIENT_EVIDENCE if keep_review_candidate else FIT_STATUS_NOT_FIT
    elif score >= 0.48 and (matched_clauses or direct_product_hit):
        fit_status = FIT_STATUS_CONDITIONAL
    elif keep_review_candidate:
        fit_status = FIT_STATUS_INSUFFICIENT_EVIDENCE
    else:
        fit_status = FIT_STATUS_NOT_FIT

    summary_reasons: list[str] = []
    for bucket in (hard_fail_reasons, gap_clauses, matched_clauses, reasons):
        for item in bucket:
            cleaned = clean_text(item)
            if cleaned and cleaned not in summary_reasons:
                summary_reasons.append(cleaned)
    if not summary_reasons:
        summary_reasons = ["匹配证据较弱"]

    return {
        "section_name": section_name,
        "section_hint": policy.get("section_hint"),
        "source_row": policy.get("source_row"),
        "级别": policy.get("级别"),
        "部委": policy.get("部委"),
        "项目名称": policy.get("项目名称"),
        "项目类型": policy.get("项目类型"),
        "支持方式": policy.get("支持方式"),
        "申报时间（预估）": policy.get("申报时间") or policy.get("date_status", {}).get("start_date"),
        "资助金额": policy.get("资助强度"),
        "关键申报条件": policy.get("申报条件"),
        "fit_status": fit_status,
        "fit_score": round(score, 2),
        "reason": "；".join(summary_reasons[:3]),
        "missing_evidence": missing_evidence,
        "gap_clauses": gap_clauses,
        "matched_clauses": matched_clauses,
        "hard_fail_reasons": hard_fail_reasons,
        "keyword_groups": keyword_groups,
        "review_candidate": fit_status in {FIT_STATUS_ELIGIBLE, FIT_STATUS_CONDITIONAL, FIT_STATUS_INSUFFICIENT_EVIDENCE},
        "preview_candidate": keep_preview_candidate,
    }


def build_match_payload(
    profile: dict[str, Any],
    policies: list[dict[str, Any]],
    template_profile: dict[str, Any],
    today_value: date,
) -> dict[str, Any]:
    ctx = company_context(profile)
    eligible_for_region = [policy for policy in policies if is_policy_region_compatible(policy, ctx)]

    matches = []
    for policy in eligible_for_region:
        section_name = policy_target_section(policy, template_profile)
        evaluation = evaluate_policy(policy, ctx, today_value, section_name)
        matches.append(evaluation)

    matches.sort(key=lambda item: (item["section_hint"] or "", item["fit_score"], item["项目名称"] or ""), reverse=True)
    return {
        "company": {key: stringify_value(value) for key, value in ctx.items() if value is not None},
        "prefilter": {
            "strategy": "按地区做保守预过滤，仅剔除明确不属于企业地区层级的政策；未知地区保留继续匹配。",
            "original_policy_count": len(policies),
            "region_filtered_count": len(policies) - len(eligible_for_region),
            "retained_policy_count": len(eligible_for_region),
        },
        "matches": matches,
    }


def main() -> int:
    args = parse_args()
    profile = json.loads(args.profile.read_text(encoding="utf-8"))
    policies = read_jsonl(args.policy_jsonl)
    template_profile = json.loads(args.template_profile.read_text(encoding="utf-8"))
    today_value = date.fromisoformat(args.today)
    payload = build_match_payload(profile, policies, template_profile, today_value)
    write_json(args.output, payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
