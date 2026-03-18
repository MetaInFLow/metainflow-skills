from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from common import bump_version_label, clean_text, load_field_mapping, load_naming_rules, sanitize_filename, write_json


def render_name(template: str, values: dict[str, Any]) -> str:
    result = template.format(**values)
    return sanitize_filename(clean_text(result).replace(" ", "_"))


def resolve_folder_segments(document_type: str, customer_name: str) -> list[str]:
    field_mapping = load_field_mapping()
    mapping = field_mapping.get("archive_structure", {})
    root_segments = list(field_mapping.get("archive_root_segments") or [])
    customer_root = root_segments + [customer_name]
    route = mapping.get(document_type) or mapping.get("default") or []
    return customer_root + route


def normalize_naming(
    extracted_document: dict[str, Any],
    match_result: dict[str, Any],
    existing_records: list[dict[str, Any]],
    output: Path,
    forced_version_label: str | None = None,
) -> dict[str, Any]:
    rules = load_naming_rules()
    customer = match_result.get("customer") or {}
    project = match_result.get("project") or {}
    document_type = extracted_document.get("document_type")
    rule = rules.get("rules", {}).get(document_type, rules.get("default", {}))
    version_label = forced_version_label or extracted_document.get("version_label")
    if rule.get("auto_version") and not version_label:
        version_label = bump_version_label([item.get("version_label", "") for item in existing_records])
    values = {
        "日期": (extracted_document.get("document_date") or "").replace("-", ""),
        "客户名称": customer.get("customer_name") or extracted_document.get("customer_name") or "未匹配客户",
        "项目编号": project.get("project_id") or extracted_document.get("project_id") or "UNMATCHED",
        "状态": extracted_document.get("status_label") or "草稿",
        "合同编号": extracted_document.get("contract_id") or "UNKNOWN",
        "交付物名称": extracted_document.get("deliverable_name") or "交付物",
        "版本": version_label or "未标注版本",
        "x": (version_label or "v1").replace("v", ""),
    }
    normalized_name = render_name(rule.get("template", "{客户名称}_{日期}"), values)
    folder_segments = resolve_folder_segments(document_type, values["客户名称"])
    payload = {
        "normalized_name": normalized_name,
        "folder_segments": folder_segments,
        "folder_path": "/".join(folder_segments),
        "file_key": f"{values['项目编号']}::{document_type}::{version_label or values['日期'] or 'unknown'}",
        "resolved_version": version_label,
        "document_type": document_type,
    }
    write_json(output, payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize S27 naming.")
    parser.add_argument("--document", type=Path, required=True)
    parser.add_argument("--match", type=Path, required=True)
    parser.add_argument("--conflict", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--forced-version-label")
    args = parser.parse_args()
    import json

    document = json.loads(args.document.read_text(encoding="utf-8"))
    match = json.loads(args.match.read_text(encoding="utf-8"))
    conflict = json.loads(args.conflict.read_text(encoding="utf-8"))
    normalize_naming(document, match, conflict.get("existing_records", []), args.output, args.forced_version_label)


if __name__ == "__main__":
    main()
