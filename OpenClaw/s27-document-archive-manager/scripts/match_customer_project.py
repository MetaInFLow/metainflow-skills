from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from common import (
    clean_text,
    deep_copy,
    enterprise_query,
    enterprise_search,
    fetch_bitable_records,
    load_field_mapping,
    normalize_name,
    write_json,
)


def score_name_match(left: str | None, right: str | None) -> float:
    l_value = normalize_name(left)
    r_value = normalize_name(right)
    if not l_value or not r_value:
        return 0.0
    if l_value == r_value:
        return 1.0
    if l_value in r_value or r_value in l_value:
        return 0.9
    left_tokens = set(l_value.replace("有限公司", "").replace("科技", " 科技").split())
    right_tokens = set(r_value.replace("有限公司", "").replace("科技", " 科技").split())
    overlap = len(left_tokens & right_tokens)
    return round(overlap / max(1, min(len(left_tokens), len(right_tokens))), 2)


def first_non_empty(record: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = record.get(key)
        if value not in (None, ""):
            return value
    return None


def normalize_customer_record(record: dict[str, Any]) -> dict[str, Any]:
    aliases = first_non_empty(record, "aliases", "客户简称", "别名") or []
    if isinstance(aliases, str):
        aliases = [part.strip() for part in aliases.replace("；", ",").replace("，", ",").split(",") if part.strip()]
    return {
        "customer_id": first_non_empty(record, "customer_id", "客户编号"),
        "customer_name": first_non_empty(record, "customer_name", "客户名称", "公司名称", "企业名称"),
        "aliases": aliases,
        "recent_contact_date": first_non_empty(record, "recent_contact_date", "最近联系日期"),
        "record_id": record.get("record_id"),
    }


def normalize_project_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "project_id": first_non_empty(record, "project_id", "项目编号"),
        "project_name": first_non_empty(record, "project_name", "项目名称", "项目"),
        "customer_id": first_non_empty(record, "customer_id", "客户编号"),
        "project_status": first_non_empty(record, "project_status", "项目状态", "阶段"),
        "record_id": record.get("record_id"),
    }


def normalize_contract_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "contract_id": first_non_empty(record, "contract_id", "合同编号"),
        "customer_id": first_non_empty(record, "customer_id", "客户编号"),
        "project_id": first_non_empty(record, "project_id", "项目编号"),
        "record_id": record.get("record_id"),
    }


def load_master_data() -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    mapping = load_field_mapping()
    seed_data = mapping.get("seed_data", {})
    notes: list[str] = []
    try:
        customers = [normalize_customer_record(item) for item in fetch_bitable_records("客户档案表")]
        projects = [normalize_project_record(item) for item in fetch_bitable_records("项目总表")]
        contracts = [normalize_contract_record(item) for item in fetch_bitable_records("合同管理表")]
    except Exception as exc:
        notes.append(f"feishu-bitable 查询失败，回退到本地 seed_data：{exc}")
        customers = []
        projects = []
        contracts = []
    if customers or projects or contracts:
        notes.append("优先使用 feishu-bitable 主数据进行客户/项目匹配。")
        return customers, projects, contracts, notes
    notes.append("未检测到可用的 feishu-bitable 连接，回退到本地 seed_data。")
    return (
        [normalize_customer_record(item) for item in seed_data.get("customers", [])],
        [normalize_project_record(item) for item in seed_data.get("projects", [])],
        [normalize_contract_record(item) for item in seed_data.get("contracts", [])],
        notes,
    )


def match_customer_project(
    extracted_document: dict[str, Any],
    thread_id: str,
    output: Path,
    customer_hint: str | None = None,
    project_hint: str | None = None,
) -> dict[str, Any]:
    customers, projects, contracts, source_notes = load_master_data()
    result: dict[str, Any] = {
        "status": "unmatched",
        "customer": None,
        "project": None,
        "candidates": [],
        "notes": [],
        "enterprise_lookup": None,
    }
    result["notes"].extend(source_notes)

    project_id = extracted_document.get("project_id") or project_hint
    if project_id:
        project_candidates = [item for item in projects if clean_text(item.get("project_id")).upper() == clean_text(project_id).upper()]
        if len(project_candidates) == 1:
            project = deep_copy(project_candidates[0])
            customer = next((item for item in customers if item.get("customer_id") == project.get("customer_id")), None)
            result["project"] = project
            result["customer"] = deep_copy(customer) if customer else None
            result["status"] = "matched"
            result["notes"].append("按项目编号精确匹配。")
            write_json(output, result)
            return result

    contract_id = extracted_document.get("contract_id")
    if contract_id:
        contract_candidates = [item for item in contracts if clean_text(item.get("contract_id")).upper() == clean_text(contract_id).upper()]
        if len(contract_candidates) == 1:
            contract = contract_candidates[0]
            project = next((item for item in projects if item.get("project_id") == contract.get("project_id")), None)
            customer = next((item for item in customers if item.get("customer_id") == contract.get("customer_id")), None)
            result["project"] = deep_copy(project) if project else None
            result["customer"] = deep_copy(customer) if customer else None
            result["status"] = "matched" if result["customer"] else "unmatched"
            result["notes"].append("按合同编号反查匹配。")
            write_json(output, result)
            return result

    customer_name = customer_hint or extracted_document.get("customer_name")
    if customer_name:
        scored = []
        for customer in customers:
            score = score_name_match(customer_name, customer.get("customer_name"))
            if score >= 0.6:
                candidate = deep_copy(customer)
                candidate["score"] = score
                scored.append(candidate)
        scored.sort(key=lambda item: item["score"], reverse=True)
        if len(scored) == 1:
            customer = scored[0]
            project_name_hint = project_hint or extracted_document.get("project_name")
            related_projects = [item for item in projects if item.get("customer_id") == customer.get("customer_id")]
            project = None
            if len(related_projects) == 1:
                project = related_projects[0]
            elif project_name_hint:
                ranked = sorted(
                    related_projects,
                    key=lambda item: score_name_match(project_name_hint, item.get("project_name")),
                    reverse=True,
                )
                if ranked and score_name_match(project_name_hint, ranked[0].get("project_name")) >= 0.6:
                    project = ranked[0]
            result["customer"] = customer
            result["project"] = deep_copy(project) if project else None
            result["status"] = "matched"
            result["notes"].append("按客户名称命中飞书主数据。")
        elif len(scored) > 1:
            result["status"] = "ambiguous"
            result["candidates"] = scored
            result["notes"].append("客户名称命中多个候选，需要人工确认。")
        else:
            try:
                search_payload = enterprise_search(customer_name, thread_id)
                enterprise_candidates = search_payload.get("data", {}).get("results") or search_payload.get("data", {}).get("items") or []
                result["enterprise_lookup"] = {"mode": "search", "items": enterprise_candidates[:5]}
            except Exception as exc:  # pragma: no cover - env dependent
                result["notes"].append(f"企业模糊查询失败：{exc}")
            try:
                query_payload = enterprise_query(customer_name, thread_id)
                result["enterprise_lookup"] = {
                    "mode": "query",
                    "item": query_payload.get("data", {}),
                }
            except Exception:
                pass
            result["notes"].append("未在飞书主数据中命中客户。")

    write_json(output, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Match S27 customer and project.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--thread-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--customer-hint")
    parser.add_argument("--project-hint")
    args = parser.parse_args()
    extracted = json.loads(args.input.read_text(encoding="utf-8"))
    match_customer_project(extracted, args.thread_id, args.output, args.customer_hint, args.project_hint)


if __name__ == "__main__":
    import json

    main()
