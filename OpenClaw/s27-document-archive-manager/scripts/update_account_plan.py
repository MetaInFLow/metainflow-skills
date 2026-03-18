from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from common import load_feishu_skill_mapping, load_field_mapping, write_json


def build_account_plan_append(extracted_document: dict[str, Any], match_result: dict[str, Any], output: Path) -> dict[str, Any]:
    customer = match_result.get("customer") or {}
    if extracted_document.get("document_type") != "拜访纪要":
        payload = {
            "status": "not_applicable",
            "target_doc_ref": None,
            "append_blocks": [],
            "source_label": None,
            "lookup_context": None,
        }
        write_json(output, payload)
        return payload

    source_label = f"来源：{(extracted_document.get('document_date') or '').replace('-', '')}拜访纪要"
    account_plan_map = load_field_mapping().get("seed_data", {}).get("account_plans", {})
    archive_root_segments = list(load_field_mapping().get("archive_root_segments") or [])
    skill_mapping = load_feishu_skill_mapping()
    lookup_context = {
        "customer_id": customer.get("customer_id"),
        "customer_name": customer.get("customer_name") or extracted_document.get("customer_name"),
        "document_root_token": skill_mapping.get("roots", {}).get("customer_document_root"),
        "wiki_root_token": skill_mapping.get("roots", {}).get("customer_wiki_root"),
        "candidate_titles": skill_mapping.get("defaults", {}).get("account_plan_titles", ["Account Plan", "客户计划"]),
        "preferred_folder_segments": archive_root_segments
        + [customer.get("customer_name") or extracted_document.get("customer_name") or "未匹配客户", "01_客户档案"],
    }
    payload = {
        "status": "pending",
        "target_doc_ref": account_plan_map.get(customer.get("customer_id")),
        "append_blocks": [
            {"heading": "拜访摘要", "content": extracted_document.get("summary") or "待补充"},
            {"heading": "决策链变化", "content": "；".join(extracted_document.get("decision_chain", [])) or "未识别到明确变化"},
            {
                "heading": "需求变化",
                "content": "；".join(extracted_document.get("requirement_changes", []) or extracted_document.get("requirements", []))
                or "未识别到明确变化",
            },
            {
                "heading": "新识别机会",
                "content": "；".join(extracted_document.get("customer_feedback", [])) or "待补充",
            },
            {"heading": "风险点", "content": "；".join(extracted_document.get("risks", [])) or "未识别到显著风险"},
            {"heading": "下一步行动", "content": "；".join(extracted_document.get("action_items", [])) or "待补充"},
        ],
        "source_label": source_label,
        "lookup_context": lookup_context,
    }
    if payload["target_doc_ref"] is None:
        payload["status"] = "lookup_required"
    write_json(output, payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Build S27 Account Plan append payload.")
    parser.add_argument("--document", type=Path, required=True)
    parser.add_argument("--match", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    import json

    document = json.loads(args.document.read_text(encoding="utf-8"))
    match = json.loads(args.match.read_text(encoding="utf-8"))
    build_account_plan_append(document, match, args.output)


if __name__ == "__main__":
    main()
