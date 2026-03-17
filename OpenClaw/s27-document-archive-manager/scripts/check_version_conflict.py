from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from common import clean_text, deep_copy, fetch_drive_files, load_field_mapping, write_json
from normalize_naming import render_name, resolve_folder_segments


def infer_expected_file_name(extracted_document: dict[str, Any], customer_name: str | None, project_id: str | None) -> str:
    document_type = extracted_document.get("document_type")
    if document_type == "拜访纪要":
        return render_name(
            "{日期}_拜访纪要_{客户名称}",
            {
                "日期": (extracted_document.get("document_date") or "").replace("-", ""),
                "客户名称": customer_name or extracted_document.get("customer_name") or "未匹配客户",
            },
        )
    if document_type == "方案":
        return render_name(
            "{项目编号}_{版本}_{状态}",
            {
                "项目编号": project_id or extracted_document.get("project_id") or "UNMATCHED",
                "版本": extracted_document.get("version_label") or "未标注版本",
                "状态": extracted_document.get("status_label") or "草稿",
            },
        )
    if document_type == "报价":
        return render_name(
            "{项目编号}_报价_{版本}_{状态}",
            {
                "项目编号": project_id or extracted_document.get("project_id") or "UNMATCHED",
                "版本": extracted_document.get("version_label") or "未标注版本",
                "状态": extracted_document.get("status_label") or "草稿",
            },
        )
    if document_type == "合同":
        return render_name(
            "{合同编号}_{版本}",
            {
                "合同编号": extracted_document.get("contract_id") or "UNKNOWN",
                "版本": extracted_document.get("version_label") or "未标注版本",
            },
        )
    if document_type == "交付物":
        return render_name(
            "{项目编号}_{交付物名称}",
            {
                "项目编号": project_id or extracted_document.get("project_id") or "UNMATCHED",
                "交付物名称": extracted_document.get("deliverable_name") or "交付物",
            },
        )
    if document_type == "验收单":
        return render_name("{项目编号}_验收确认书", {"项目编号": project_id or extracted_document.get("project_id") or "UNMATCHED"})
    return ""


def check_version_conflict(extracted_document: dict[str, Any], match_result: dict[str, Any], output: Path) -> dict[str, Any]:
    mapping = load_field_mapping()
    seed_data = mapping.get("seed_data", {})
    index_records = seed_data.get("document_index", [])
    drive_files = seed_data.get("drive_files", [])
    customer_id = (match_result.get("customer") or {}).get("customer_id")
    customer_name = (match_result.get("customer") or {}).get("customer_name") or extracted_document.get("customer_name")
    project_id = (match_result.get("project") or {}).get("project_id") or extracted_document.get("project_id")
    document_type = extracted_document.get("document_type")
    version_label = extracted_document.get("version_label")
    document_date = extracted_document.get("document_date")
    conflicts = []
    for record in index_records:
        same_customer = not customer_id or record.get("customer_id") == customer_id
        same_project = not project_id or record.get("project_id") == project_id
        same_type = record.get("document_type") == document_type
        same_version = version_label and clean_text(record.get("version_label")).lower() == clean_text(version_label).lower()
        same_visit_date = document_type == "拜访纪要" and document_date and record.get("document_date") == document_date
        if same_customer and same_project and same_type and (same_version or same_visit_date):
            conflicts.append(deep_copy(record))
    folder_path = "/".join(resolve_folder_segments(document_type, customer_name or "未匹配客户"))
    expected_file_name = infer_expected_file_name(extracted_document, customer_name, project_id)
    drive_conflicts = []
    drive_notes: list[str] = []
    real_drive_files = fetch_drive_files()
    if real_drive_files:
        drive_files = real_drive_files
        drive_notes.append("命中 feishu-drive 预读取缓存。")
    else:
        drive_notes.append("prepare 阶段不直连飞书 API；当前使用本地 drive_files mock 进行同名冲突预判。")
        drive_notes.append("正式目录检索与落库由 openclaw-lark 的 feishu-drive 在执行阶段完成。")
    for item in drive_files:
        same_folder = item.get("folder_path") == folder_path
        same_name = expected_file_name and clean_text(item.get("file_name")).lower() == clean_text(expected_file_name).lower()
        weak_same_name = same_name and not item.get("folder_path")
        if (same_folder and same_name) or weak_same_name:
            drive_conflicts.append(deep_copy(item))
    conflicts.extend(drive_conflicts)
    conflict_type = None
    if drive_conflicts:
        conflict_type = "same_name_in_drive"
    elif version_label and conflicts:
        conflict_type = "same_version"
    elif conflicts:
        conflict_type = "same_date_minutes"

    payload = {
        "blocking_conflict": bool(conflicts),
        "conflict_type": conflict_type,
        "existing_records": conflicts,
        "recommended_actions": ["overwrite", "save_as_new_version", "cancel"] if conflicts else ["confirm", "cancel"],
        "notes": [
            "文档归档索引表是版本判断的事实源。",
            "目标归档目录下的同名文件会作为额外阻断条件。",
            *drive_notes,
        ],
        "expected_file_name": expected_file_name,
        "expected_folder_path": folder_path,
    }
    write_json(output, payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Check S27 version conflict.")
    parser.add_argument("--document", type=Path, required=True)
    parser.add_argument("--match", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    import json

    document = json.loads(args.document.read_text(encoding="utf-8"))
    match = json.loads(args.match.read_text(encoding="utf-8"))
    check_version_conflict(document, match, args.output)


if __name__ == "__main__":
    main()
