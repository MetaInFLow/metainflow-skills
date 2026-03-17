from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

from common import (
    FIT_STATUS_CONDITIONAL,
    FIT_STATUS_ELIGIBLE,
    FIT_STATUS_INSUFFICIENT_EVIDENCE,
    REVIEWABLE_FIT_STATUSES,
    SELECTABLE_FIT_STATUSES,
    clean_text,
    normalize_fit_status,
    normalize_string,
    parse_amount_to_wanyuan,
    parse_int,
    parse_percentage,
    read_jsonl,
    stringify_value,
    try_parse_date,
    write_json,
)
from match_policies import build_match_payload
from template_utils import DEFAULT_REGISTRY_PATH, extract_seed_context, resolve_template_profile


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
DEFAULT_POLICY_JSONL_PATH = SKILL_DIR / "references" / "policy_library.normalized.jsonl"
SESSION_STATE_FILENAME = "session_state.json"
PREVIEW_CANDIDATES_FILENAME = "preview_candidates.json"
WORKBOOK_NOTE = "主表中序号列为淡黄色的行为 AI 初筛候选，匹配理由与缺口说明已写入备注列。"

TOP_CONTEXT_FIELDS = (
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
)
SUPPLEMENTAL_MATCH_FIELDS = (
    "annual_output_wanyuan",
    "rd_ratio_pct",
    "rd_staff_count",
    "patent_count_total",
    "patent_count_invention",
    "patent_count_utility_model",
    "high_tech_enterprise",
    "main_product",
)
SUPPLEMENTAL_FIELD_LABELS = {
    "region": "所属地区",
    "annual_output_wanyuan": "营业收入/年产值",
    "rd_ratio_pct": "研发投入占比",
    "rd_staff_count": "专职研发人数",
    "patent_count_total": "知识产权数量",
    "patent_count_invention": "发明专利数量",
    "patent_count_utility_model": "实用新型专利数量",
    "high_tech_enterprise": "高新技术企业状态",
    "main_product": "主要产品",
}
HIGH_PRIORITY_PREPARE_FIELDS = {"region", "annual_output_wanyuan", "patent_count_total", "rd_ratio_pct"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the interview-policy-planner pipeline in staged mode.")
    parser.add_argument("--workbook", type=Path)
    parser.add_argument("--minutes", type=Path)
    parser.add_argument("--policy-jsonl", type=Path)
    parser.add_argument("--policy-csv", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--today")
    parser.add_argument("--confirmations", type=Path)
    parser.add_argument("--stage", choices=("prepare", "finalize", "full"), default="prepare")
    return parser.parse_args()


def run_python(script_name: str, arguments: list[str]) -> None:
    subprocess.run([sys.executable, str(SCRIPT_DIR / script_name), *arguments], check=True)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_session_state(output_dir: Path) -> dict[str, Any] | None:
    path = output_dir / SESSION_STATE_FILENAME
    return load_json(path) if path.exists() else None


def resolve_runtime_inputs(args: argparse.Namespace, state: dict[str, Any] | None) -> dict[str, Any]:
    inputs = (state or {}).get("inputs", {})
    workbook = args.workbook.resolve() if args.workbook else (Path(inputs["workbook"]) if inputs.get("workbook") else None)
    minutes = args.minutes.resolve() if args.minutes else (Path(inputs["minutes"]) if inputs.get("minutes") else None)
    if args.stage in {"prepare", "full"} and (workbook is None or minutes is None):
        raise ValueError(f"{args.stage} 阶段需要 workbook 和 minutes。")
    if args.stage == "finalize" and state is None and (workbook is None or minutes is None):
        raise ValueError("finalize 阶段需要已有 session_state，或显式传入 workbook 和 minutes。")
    return {
        "workbook": workbook,
        "minutes": minutes,
        "policy_jsonl": args.policy_jsonl.resolve() if args.policy_jsonl else Path(inputs.get("policy_jsonl") or DEFAULT_POLICY_JSONL_PATH),
        "policy_csv": args.policy_csv.resolve() if args.policy_csv else (Path(inputs["policy_csv"]) if inputs.get("policy_csv") else None),
        "registry": args.registry.resolve() if args.registry else Path(inputs.get("registry") or DEFAULT_REGISTRY_PATH),
        "today": args.today or inputs.get("today") or date.today().isoformat(),
    }


def prepare_policy_jsonl(policy_jsonl: Path, policy_csv: Path | None, normalized_policy_path: Path) -> None:
    normalized_policy_path.parent.mkdir(parents=True, exist_ok=True)
    if policy_csv:
        run_python("normalize_policy_csv.py", ["--input", str(policy_csv), "--output", str(normalized_policy_path)])
        return
    if not policy_jsonl.exists():
        raise FileNotFoundError(f"未找到政策库 JSONL：{policy_jsonl}")
    shutil.copy2(policy_jsonl, normalized_policy_path)


def build_excel_context(seed: dict[str, Any], template_profile: dict[str, Any]) -> dict[str, Any]:
    configs = {item["name"]: item for item in template_profile.get("top_fields", [])}
    context: dict[str, Any] = {}
    for field_name in TOP_CONTEXT_FIELDS:
        config = configs.get(field_name, {})
        value = seed.get(field_name)
        context[field_name] = {
            "value": value,
            "status": "present" if value not in (None, "") else "missing",
            "confidence": 1.0 if value not in (None, "") else 0.0,
            "notes": ["来自目标工作簿顶部字段"],
            "evidence": [{"source": "workbook_seed", "text": str(value)}] if value not in (None, "") else [],
            "label": config.get("label", field_name),
            "cell": config.get("cell"),
        }
    return context


def comparable_tokens(value: str) -> set[str]:
    return {item for item in re.split(r"[\s,，、；;：:（）()\-/]+", clean_text(value)) if item}


def values_conflict(excel_value: Any, transcript_value: Any) -> bool:
    if excel_value in (None, "") or transcript_value in (None, ""):
        return False
    if isinstance(excel_value, (int, float)) and isinstance(transcript_value, (int, float)):
        return round(float(excel_value), 2) != round(float(transcript_value), 2)
    excel_text = normalize_string(str(excel_value))
    transcript_text = normalize_string(str(transcript_value))
    if not excel_text or not transcript_text or excel_text == transcript_text:
        return False
    if excel_text in transcript_text or transcript_text in excel_text:
        return False
    excel_tokens = comparable_tokens(excel_text)
    transcript_tokens = comparable_tokens(transcript_text)
    if excel_tokens and transcript_tokens:
        overlap_ratio = len(excel_tokens & transcript_tokens) / max(1, min(len(excel_tokens), len(transcript_tokens)))
        if overlap_ratio >= 0.6:
            return False
    return True


def should_compare_transcript_record(record: dict[str, Any]) -> bool:
    notes = [clean_text(str(item)) for item in record.get("notes", [])]
    return record.get("value") not in (None, "") and not any(any(token in note for token in ("由", "汇总", "推导", "推断", "映射")) for note in notes)


def build_conflicts(excel_context: dict[str, Any], transcript_facts: dict[str, Any]) -> list[dict[str, Any]]:
    conflicts = []
    for field_name in TOP_CONTEXT_FIELDS:
        transcript_record = transcript_facts.get(field_name, {})
        if not should_compare_transcript_record(transcript_record):
            continue
        if not values_conflict(excel_context.get(field_name, {}).get("value"), transcript_record.get("value")):
            continue
        conflicts.append(
            {
                "field": field_name,
                "label": excel_context.get(field_name, {}).get("label", field_name),
                "cell": excel_context.get(field_name, {}).get("cell"),
                "excel_value": excel_context.get(field_name, {}).get("value"),
                "transcript_value": transcript_record.get("value"),
                "reason": "工作簿顶部字段与访谈纪要口径不一致，本次匹配按 Excel 顶部字段处理。",
            }
        )
    return conflicts


def build_missing_fields(excel_context: dict[str, Any], transcript_facts: dict[str, Any]) -> list[str]:
    missing = [name for name in TOP_CONTEXT_FIELDS if excel_context.get(name, {}).get("value") in (None, "")]
    missing.extend(name for name in SUPPLEMENTAL_MATCH_FIELDS if transcript_facts.get(name, {}).get("value") in (None, ""))
    return list(dict.fromkeys(missing))


def field_label(profile: dict[str, Any], field_name: str) -> str:
    record = profile.get("excel_context", {}).get(field_name, {})
    return record.get("label", SUPPLEMENTAL_FIELD_LABELS.get(field_name, field_name))


def build_minutes_summary(profile: dict[str, Any]) -> dict[str, Any]:
    excel = profile.get("excel_context", {})
    facts = profile.get("transcript_facts", {})
    risk_flags = profile.get("risk_flags", [])
    items = [
        {"label": "企业主体", "value": f"{excel.get('enterprise_name', {}).get('value') or '未识别企业主体'}，注册地址：{excel.get('address', {}).get('value') or '未填写注册地址'}，所属行业：{excel.get('industry', {}).get('value') or '未填写所属行业'}"},
        {"label": "经营基础", "value": f"注册资金：{stringify_value(excel.get('registered_capital_wanyuan', {}).get('value')) or '未填写'}万元；注册时间：{stringify_value(excel.get('registered_date', {}).get('value')) or '未填写'}；社保人数：{stringify_value(excel.get('employee_count', {}).get('value')) or '未填写'}"},
        {"label": "主营与资质", "value": f"主营业务及产品：{excel.get('main_business', {}).get('value') or facts.get('main_product', {}).get('value') or '未明确主营方向'}；企业资质荣誉：{excel.get('honors', {}).get('value') or '未填写资质荣誉'}"},
        {"label": "经营指标", "value": f"营业收入/年产值：{stringify_value(facts.get('annual_output_wanyuan', {}).get('value')) or '未补充'}万元；研发投入占比：{stringify_value(facts.get('rd_ratio_pct', {}).get('value')) or '未补充'}%；专职研发人数：{stringify_value(facts.get('rd_staff_count', {}).get('value')) or '未补充'}"},
        {"label": "知识产权与风险", "value": f"知识产权数量：{stringify_value(facts.get('patent_count_total', {}).get('value')) or '未补充'}；高企状态：{stringify_value(facts.get('high_tech_enterprise', {}).get('value')) or '未补充'}；风险提示：{'；'.join(item.get('reason', '') for item in risk_flags[:3]) or '未发现明显风险提示'}"},
    ]
    return {"text": "；".join(item["value"] for item in items), "items": items}


def build_company_profile(extracted_profile: dict[str, Any], seed: dict[str, Any], template_profile: dict[str, Any]) -> dict[str, Any]:
    transcript_facts = json.loads(json.dumps(extracted_profile.get("facts", {})))
    excel_context = build_excel_context(seed, template_profile)
    profile = {
        "excel_context": excel_context,
        "transcript_facts": transcript_facts,
        "risk_flags": extracted_profile.get("risk_flags", []),
        "evidence": extracted_profile.get("evidence", []),
    }
    profile["conflicts"] = build_conflicts(excel_context, transcript_facts)
    profile["missing_fields"] = build_missing_fields(excel_context, transcript_facts)
    profile["minutes_summary"] = build_minutes_summary(profile)
    profile["match_summary"] = {"text": "待完成政策匹配后生成。", "items": [], "selected_policy_count": 0, "eligible_count": 0, "conditional_count": 0, "insufficient_evidence_count": 0}
    return profile


def normalize_confirmation_value(field_name: str, value: Any) -> Any:
    raw_value = value.get("value") if isinstance(value, dict) and "value" in value else value
    if raw_value in (None, ""):
        return None
    if field_name in {"registered_capital_wanyuan", "annual_output_wanyuan"}:
        return parse_amount_to_wanyuan(raw_value)
    if field_name in {"employee_count", "rd_staff_count", "patent_count_total", "patent_count_invention", "patent_count_utility_model"}:
        return parse_int(raw_value)
    if field_name == "rd_ratio_pct":
        return parse_percentage(raw_value)
    if field_name == "registered_date":
        return try_parse_date(raw_value)
    if field_name == "high_tech_enterprise":
        text = clean_text(str(raw_value)).lower()
        if text in {"true", "1", "yes", "是", "有", "有效", "已取得"}:
            return True
        if text in {"false", "0", "no", "否", "无", "未取得", "不是"}:
            return False
    return raw_value


def load_confirmations(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None:
        return {"transcript_facts": {}, "excel_override_requests": {}}
    payload = load_json(path)
    if not isinstance(payload, dict):
        raise ValueError("confirmations 必须是 JSON object。")
    transcript_values = payload.get("transcript_facts")
    if transcript_values is None:
        transcript_values = {key: value for key, value in payload.items() if key != "excel_override_requests"}
    transcript_values = transcript_values if isinstance(transcript_values, dict) else {}
    request_values = payload.get("excel_override_requests", {})
    request_values = request_values if isinstance(request_values, dict) else {}
    return {
        "transcript_facts": {key: normalize_confirmation_value(key, value) for key, value in transcript_values.items() if normalize_confirmation_value(key, value) is not None},
        "excel_override_requests": {key: normalize_confirmation_value(key, value) for key, value in request_values.items() if normalize_confirmation_value(key, value) is not None},
    }


def rebuild_profile(profile: dict[str, Any]) -> dict[str, Any]:
    profile["conflicts"] = build_conflicts(profile.get("excel_context", {}), profile.get("transcript_facts", {}))
    profile["missing_fields"] = build_missing_fields(profile.get("excel_context", {}), profile.get("transcript_facts", {}))
    profile["minutes_summary"] = build_minutes_summary(profile)
    return profile


def apply_confirmations(profile: dict[str, Any], overrides: dict[str, Any], explicit_requests: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    updated = json.loads(json.dumps(profile))
    for field_name, value in overrides.items():
        updated.setdefault("transcript_facts", {})[field_name] = {
            "value": value,
            "status": "confirmed_by_user",
            "confidence": 1.0,
            "notes": ["用户补充确认"],
            "evidence": [{"source": "user_confirmation", "text": f"{field_name}={stringify_value(value)}"}],
        }
    updated = rebuild_profile(updated)
    requests: dict[str, dict[str, Any]] = {}
    for field_name, value in explicit_requests.items():
        excel = updated.get("excel_context", {}).get(field_name, {})
        requests[field_name] = {"field": field_name, "label": excel.get("label", field_name), "cell": excel.get("cell"), "excel_value": excel.get("value"), "requested_value": value, "reason": "用户已确认该字段需按访谈/补充口径处理，但当前 Excel 顶部字段未修改。"}
    for field_name, value in overrides.items():
        if field_name not in TOP_CONTEXT_FIELDS:
            continue
        excel = updated.get("excel_context", {}).get(field_name, {})
        requests[field_name] = {"field": field_name, "label": excel.get("label", field_name), "cell": excel.get("cell"), "excel_value": excel.get("value"), "requested_value": value, "reason": "用户已确认该字段，但最终匹配仍以 Excel 顶部字段为准。"}
    return updated, list(requests.values())


def unique_texts(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = clean_text(value)
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return result


def build_match_summary(profile: dict[str, Any], matches_payload: dict[str, Any]) -> dict[str, Any]:
    review_candidates = [item for item in matches_payload.get("matches", []) if normalize_fit_status(item.get("fit_status")) in REVIEWABLE_FIT_STATUSES]
    eligible = sum(1 for item in review_candidates if normalize_fit_status(item.get("fit_status")) == FIT_STATUS_ELIGIBLE)
    conditional = sum(1 for item in review_candidates if normalize_fit_status(item.get("fit_status")) == FIT_STATUS_CONDITIONAL)
    insufficient = sum(1 for item in review_candidates if normalize_fit_status(item.get("fit_status")) == FIT_STATUS_INSUFFICIENT_EVIDENCE)
    section_counter = Counter(item.get("section_name") or item.get("section_hint") or "未分类" for item in review_candidates)
    reasons = unique_texts([item.get("reason", "") for item in review_candidates])
    items = [
        {"label": "匹配概览", "value": f"共列出 {len(review_candidates)} 项人工审核候选，其中“符合”{eligible} 项，“有条件符合”{conditional} 项，“证据不足”{insufficient} 项。"},
        {"label": "主要命中方向", "value": "、".join(name for name, _count in section_counter.most_common(3)) or "暂无明显命中方向"},
        {"label": "代表政策", "value": "、".join(item.get('项目名称') or '' for item in review_candidates[:5]) or "暂无审核候选政策"},
        {"label": "核心匹配理由", "value": "；".join(reasons[:3]) or "暂无高置信匹配理由"},
        {"label": "主要缺口与冲突", "value": f"主要缺失：{'、'.join(field_label(profile, name) for name in profile.get('missing_fields', [])[:5]) or '无'}；上下文冲突：{'、'.join(item.get('label', item.get('field', '')) for item in profile.get('conflicts', [])[:5]) or '无'}；高置信候选 {sum(1 for item in review_candidates if normalize_fit_status(item.get('fit_status')) in SELECTABLE_FIT_STATUSES)} 项。"},
    ]
    return {"text": "；".join(item["value"] for item in items), "items": items, "selected_policy_count": len(review_candidates), "eligible_count": eligible, "conditional_count": conditional, "insufficient_evidence_count": insufficient}


def build_preview_candidates(matches_payload: dict[str, Any], limit: int = 20) -> list[dict[str, Any]]:
    items = [item for item in matches_payload.get("matches", []) if item.get("preview_candidate")]
    items.sort(key=lambda item: (item.get("fit_score") or 0.0, item.get("项目名称") or ""), reverse=True)
    return [
        {
            "project_name": item.get("项目名称") or "",
            "section_name": item.get("section_name") or item.get("section_hint") or "",
            "fit_score": item.get("fit_score"),
            "reason": item.get("reason") or "",
            "matched_clauses": item.get("matched_clauses", []),
            "missing_evidence": item.get("missing_evidence", []),
            "keyword_groups": item.get("keyword_groups", []),
            "source_row": item.get("source_row"),
        }
        for item in items[:limit]
    ]


def build_pending_questions(profile: dict[str, Any], excel_override_requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    request_fields = {item.get("field") for item in excel_override_requests}
    questions: list[dict[str, Any]] = []
    for item in profile.get("conflicts", []):
        field_name = item.get("field") or ""
        if field_name in request_fields:
            continue
        questions.append({"kind": "conflict", "field": field_name, "label": item.get("label") or field_name, "priority": "高", "question": f"Excel 顶部字段“{item.get('label') or field_name}”当前为“{stringify_value(item.get('excel_value'))}”，访谈/补充口径为“{stringify_value(item.get('transcript_value'))}”。如不修改 Excel，本轮仍按 Excel 当前值继续。"})
    for field_name in profile.get("missing_fields", []):
        if field_name in request_fields and field_name in TOP_CONTEXT_FIELDS:
            continue
        questions.append({"kind": "missing", "field": field_name, "label": field_label(profile, field_name), "priority": "高" if field_name in HIGH_PRIORITY_PREPARE_FIELDS else "中", "question": f"请补充“{field_label(profile, field_name)}”。"})
    questions.sort(key=lambda item: (0 if item["kind"] == "conflict" else 1 if item["field"] in HIGH_PRIORITY_PREPARE_FIELDS else 2, item["field"]))
    return questions[:3]


def build_gating_reasons(profile: dict[str, Any], excel_override_requests: list[dict[str, Any]]) -> list[str]:
    reasons = [f"已记录 Excel 顶部字段更正请求：{item.get('label')}" for item in excel_override_requests]
    request_fields = {item.get("field") for item in excel_override_requests}
    reasons.extend(f"存在顶部字段冲突：{item.get('label')}" for item in profile.get("conflicts", []) if item.get("field") not in request_fields)
    reasons.extend(f"存在待确认字段：{field_label(profile, name)}" for name in profile.get("missing_fields", []) if not (name in request_fields and name in TOP_CONTEXT_FIELDS))
    return list(dict.fromkeys(reasons))


def build_session_state(runtime: dict[str, Any], output_dir: Path, overrides: dict[str, Any], excel_override_requests: list[dict[str, Any]], pending_questions: list[dict[str, Any]], gating_reasons: list[str], preview_candidates: list[dict[str, Any]], status: str) -> dict[str, Any]:
    return {
        "status": status,
        "inputs": {key: (str(value) if isinstance(value, Path) else value) for key, value in runtime.items()},
        "confirmed_transcript_overrides": overrides,
        "excel_override_requests": excel_override_requests,
        "pending_questions": pending_questions,
        "gating_reasons": gating_reasons,
        "preview_candidate_ids": [str(item.get("source_row") or item.get("project_name")) for item in preview_candidates],
        "artifacts": {"preview_candidates_path": str(output_dir / PREVIEW_CANDIDATES_FILENAME), "profile_path": str(output_dir / "company_profile.json"), "template_profile_path": str(output_dir / "resolved_template_profile.json"), "normalized_policy_path": str(output_dir / "policy_library.normalized.jsonl")},
    }


def finalize_outputs(runtime: dict[str, Any], output_dir: Path, template_profile: dict[str, Any], merged_profile: dict[str, Any], matches_payload: dict[str, Any], session_state: dict[str, Any]) -> dict[str, Any]:
    matches_path = output_dir / "policy_matches.json"
    updated_workbook_path = output_dir / f"{runtime['workbook'].stem}_updated{runtime['workbook'].suffix}"
    merged_profile["match_summary"] = build_match_summary(merged_profile, matches_payload)
    matches_payload["match_summary"] = merged_profile["match_summary"]
    write_json(output_dir / "company_profile.json", merged_profile)
    write_json(matches_path, matches_payload)
    run_python("update_workbook.py", ["--workbook", str(runtime["workbook"]), "--matches", str(matches_path), "--profile", str(output_dir / "company_profile.json"), "--registry", str(runtime["registry"]), "--output", str(updated_workbook_path)])
    session_state["status"] = "finalized"
    session_state.setdefault("artifacts", {})["matches_path"] = str(matches_path)
    session_state["artifacts"]["updated_workbook"] = str(updated_workbook_path)
    write_json(output_dir / SESSION_STATE_FILENAME, session_state)
    review_candidates = [item for item in matches_payload["matches"] if normalize_fit_status(item.get("fit_status")) in REVIEWABLE_FIT_STATUSES]
    return {
        "updated_workbook": str(updated_workbook_path),
        "selected_policy_count": len(review_candidates),
        "review_sheet": template_profile["review_sheet"]["name"],
        "missing_fields": merged_profile.get("missing_fields", []),
        "minutes_summary": merged_profile.get("minutes_summary", {}).get("text", ""),
        "match_summary": matches_payload["match_summary"].get("text", ""),
        "workbook_note": WORKBOOK_NOTE,
        "session_state": str(output_dir / SESSION_STATE_FILENAME),
    }


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    state = load_session_state(args.output_dir)
    runtime = resolve_runtime_inputs(args, state)
    confirmations = load_confirmations(args.confirmations)
    overrides = dict((state or {}).get("confirmed_transcript_overrides", {}))
    overrides.update(confirmations.get("transcript_facts", {}))
    explicit_requests = {item["field"]: item.get("requested_value") for item in (state or {}).get("excel_override_requests", []) if item.get("field")}
    explicit_requests.update(confirmations.get("excel_override_requests", {}))

    normalized_policy_path = args.output_dir / "policy_library.normalized.jsonl"
    prepare_policy_jsonl(runtime["policy_jsonl"], runtime["policy_csv"], normalized_policy_path)
    run_python("extract_profile_from_minutes.py", ["--input", str(runtime["minutes"]), "--output", str(args.output_dir / "company_profile.extracted.json")])
    template_profile = resolve_template_profile(runtime["workbook"], runtime["registry"])
    seed = extract_seed_context(runtime["workbook"], template_profile)
    extracted_profile = load_json(args.output_dir / "company_profile.extracted.json")
    merged_profile = build_company_profile(extracted_profile, seed, template_profile)
    merged_profile, excel_override_requests = apply_confirmations(merged_profile, overrides, explicit_requests)
    write_json(args.output_dir / "company_profile.json", merged_profile)
    write_json(args.output_dir / "resolved_template_profile.json", template_profile)

    matches_payload = build_match_payload(merged_profile, read_jsonl(normalized_policy_path), template_profile, date.fromisoformat(runtime["today"]))
    preview_candidates = build_preview_candidates(matches_payload, limit=20)
    write_json(args.output_dir / PREVIEW_CANDIDATES_FILENAME, preview_candidates)
    pending_questions = build_pending_questions(merged_profile, excel_override_requests)
    gating_reasons = build_gating_reasons(merged_profile, excel_override_requests)
    status = "ready_to_run" if not gating_reasons and not pending_questions else "pending_confirmation"
    session_state = build_session_state(runtime, args.output_dir, overrides, excel_override_requests, pending_questions, gating_reasons, preview_candidates, status)
    write_json(args.output_dir / SESSION_STATE_FILENAME, session_state)

    if args.stage == "full":
        print(json.dumps(finalize_outputs(runtime, args.output_dir, template_profile, merged_profile, matches_payload, session_state), ensure_ascii=False, indent=2))
        return 0
    if args.stage == "prepare":
        if status == "ready_to_run":
            summary = {"status": status, "auto_finalized": True, "pending_questions": pending_questions, "preview_candidates": preview_candidates, "missing_fields": merged_profile.get("missing_fields", []), "conflicts": merged_profile.get("conflicts", []), "minutes_summary": merged_profile.get("minutes_summary", {}).get("text", ""), "session_state": str(args.output_dir / SESSION_STATE_FILENAME), "final_result": finalize_outputs(runtime, args.output_dir, template_profile, merged_profile, matches_payload, session_state)}
        else:
            summary = {"status": status, "auto_finalized": False, "pending_questions": pending_questions, "preview_candidates": preview_candidates, "missing_fields": merged_profile.get("missing_fields", []), "conflicts": merged_profile.get("conflicts", []), "minutes_summary": merged_profile.get("minutes_summary", {}).get("text", ""), "session_state": str(args.output_dir / SESSION_STATE_FILENAME), "gating_reasons": gating_reasons}
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    print(json.dumps(finalize_outputs(runtime, args.output_dir, template_profile, merged_profile, matches_payload, session_state), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
