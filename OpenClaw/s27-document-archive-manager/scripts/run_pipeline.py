from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from build_card_payload import build_card_payload
from check_version_conflict import check_version_conflict
from common import (
    deep_copy,
    ensure_dir,
    hash_payload,
    load_field_mapping,
    load_feishu_skill_mapping,
    make_session_id,
    now_iso,
    require_real_feishu_roots,
    read_json,
    today_iso,
    write_json,
)
from extract_document_facts import extract_document_facts
from match_customer_project import match_customer_project
from normalize_naming import normalize_naming
from update_account_plan import build_account_plan_append
from write_prepare_state import write_prepare_state


def render_account_plan_markdown(account_plan_append: dict[str, Any]) -> str:
    blocks = account_plan_append.get("append_blocks") or []
    rendered: list[str] = []
    for block in blocks:
        heading = block.get("heading") or "未命名章节"
        content = block.get("content") or "待补充"
        rendered.append(f"## {heading}\n\n{content}")
    return "\n\n".join(rendered)


def looks_like_feishu_receive_id(target: str | None) -> tuple[str, str] | None:
    if not target:
        return None
    if target.startswith("oc_"):
        return ("chat_id", target)
    if target.startswith("ou_"):
        return ("open_id", target)
    return None


def build_archive_folder_segments(naming_result: dict[str, Any]) -> list[str]:
    folder_path = naming_result.get("folder_path") or ""
    return [segment for segment in str(folder_path).split("/") if segment]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the S27 document archive pipeline.")
    parser.add_argument("--stage", choices=("prepare", "finalize", "completeness-check"), required=True)
    parser.add_argument("--source")
    parser.add_argument("--source-type", choices=("file", "url", "text"), default="file")
    parser.add_argument("--operator-id")
    parser.add_argument("--operator-name")
    parser.add_argument("--thread-id")
    parser.add_argument("--customer-hint")
    parser.add_argument("--project-hint")
    parser.add_argument("--customer-id")
    parser.add_argument("--project-id")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--session-dir", type=Path)
    parser.add_argument("--confirmation-token")
    parser.add_argument("--confirmed-by")
    parser.add_argument("--action", choices=("confirm", "overwrite", "save_as_new_version", "cancel"))
    return parser.parse_args()


def build_table_schema_requirements(table_updates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    mapping = load_field_mapping().get("tables", {})
    requirements: list[dict[str, Any]] = []
    for update in materialize_table_updates(table_updates):
        table_name = update.get("table_name")
        if not table_name or table_name not in mapping:
            continue
        table_config = mapping[table_name]
        record_lookup = update.get("record_lookup") or {}
        fields = update.get("fields") or {}
        required_fields: list[str] = []
        for field_name in [*record_lookup.keys(), *fields.keys()]:
            if field_name and field_name not in required_fields:
                required_fields.append(field_name)
        requirements.append(
            {
                "table_name": table_name,
                "app_token": table_config.get("app_token"),
                "table_id": table_config.get("table_id"),
                "key_field": table_config.get("key_field"),
                "operation": update.get("operation"),
                "required_fields": required_fields,
                "record_lookup_fields": list(record_lookup.keys()),
                "update_fields": list(fields.keys()),
            }
        )
    return requirements


def build_table_schema_requirement(
    table_name: str,
    operation: str,
    record_lookup: dict[str, Any],
    fields: dict[str, Any],
) -> dict[str, Any]:
    mapping = load_field_mapping().get("tables", {})
    table_config = mapping.get(table_name, {})
    required_fields: list[str] = []
    for field_name in [*record_lookup.keys(), *fields.keys()]:
        if field_name and field_name not in required_fields:
            required_fields.append(field_name)
    return {
        "table_name": table_name,
        "app_token": table_config.get("app_token"),
        "table_id": table_config.get("table_id"),
        "key_field": table_config.get("key_field"),
        "operation": operation,
        "required_fields": required_fields,
        "record_lookup_fields": list(record_lookup.keys()),
        "update_fields": list(fields.keys()),
    }


def materialize_table_update(update: dict[str, Any]) -> dict[str, Any]:
    mapping = load_field_mapping().get("tables", {})
    table_name = update.get("table_name")
    table_config = mapping.get(table_name, {})
    lookup_aliases = table_config.get("lookup_field_aliases", {})
    field_aliases = table_config.get("field_aliases", {})
    static_fields = table_config.get("static_fields", {})
    record_lookup = update.get("record_lookup") or {}
    fields = update.get("fields") or {}

    mapped_lookup: dict[str, Any] = {}
    for key, value in record_lookup.items():
        target_key = lookup_aliases.get(key, key)
        if target_key and value is not None:
            mapped_lookup[target_key] = value

    mapped_fields: dict[str, Any] = {}
    for key, value in fields.items():
        target_key = field_aliases.get(key, key)
        if target_key and value is not None:
            mapped_fields[target_key] = value

    if static_fields:
        mapped_fields.update(static_fields)

    key_field = table_config.get("key_field")
    if key_field and key_field not in mapped_lookup and key_field in mapped_fields:
        mapped_lookup = {key_field: mapped_fields[key_field], **mapped_lookup}

    materialized = deep_copy(update)
    materialized["record_lookup"] = mapped_lookup
    materialized["fields"] = mapped_fields
    return materialized


def materialize_table_updates(table_updates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [materialize_table_update(update) for update in table_updates]


def build_table_update_plan(
    extracted_document: dict[str, Any],
    match_result: dict[str, Any],
    naming_result: dict[str, Any],
    account_plan_append: dict[str, Any],
) -> list[dict[str, Any]]:
    field_mapping = load_field_mapping()
    table_mapping = field_mapping.get("tables", {})

    def with_table_meta(update: dict[str, Any]) -> dict[str, Any]:
        table_name = update.get("table_name")
        table_meta = table_mapping.get(table_name, {})
        if table_meta:
            update = {
                **update,
                "app_token": table_meta.get("app_token"),
                "table_id": table_meta.get("table_id"),
                "key_field": table_meta.get("key_field"),
            }
        return update

    customer = match_result.get("customer") or {}
    project = match_result.get("project") or {}
    operator_name = extracted_document.get("operator_name")
    document_record = with_table_meta({
        "table_name": "文档归档索引表",
        "operation": "upsert",
        "record_lookup": {
            "customer_id": customer.get("customer_id"),
            "project_id": project.get("project_id") or extracted_document.get("project_id"),
            "document_type": extracted_document.get("document_type"),
            "version_label": naming_result.get("resolved_version"),
        },
        "fields": {
            "文件名": naming_result.get("normalized_name"),
            "文档类型": extracted_document.get("document_type"),
            "版本": naming_result.get("resolved_version"),
            "归档路径": naming_result.get("archive_url"),
            "关联项目": project.get("project_id") or extracted_document.get("project_id"),
            "归档时间": now_iso(),
            "归档人": operator_name,
            "document_date": extracted_document.get("document_date"),
        },
    })
    updates = [document_record]
    if customer.get("customer_id"):
        updates.append(
            with_table_meta({
                "table_name": "客户档案表",
                "operation": "update",
                "record_lookup": {"customer_id": customer.get("customer_id")},
                "fields": {
                    "最近联系日期": extracted_document.get("document_date") or today_iso(),
                    "最近归档": naming_result.get("normalized_name"),
                },
            })
        )
    if project.get("project_id"):
        updates.append(
            with_table_meta({
                "table_name": "项目总表",
                "operation": "update",
                "record_lookup": {"project_id": project.get("project_id")},
                "fields": {
                    "最近跟进日期": extracted_document.get("document_date") or today_iso(),
                    "最近归档日期": extracted_document.get("document_date") or today_iso(),
                },
            })
        )
    doc_type = extracted_document.get("document_type")
    type_to_table = {"方案": "方案管理表", "报价": "报价管理表", "合同": "合同管理表"}
    if doc_type in type_to_table:
        lookup_key = "合同编号" if doc_type == "合同" else "项目编号"
        lookup_value = extracted_document.get("contract_id") if doc_type == "合同" else project.get("project_id")
        updates.append(
            with_table_meta({
                "table_name": type_to_table[doc_type],
                "operation": "update",
                "record_lookup": {lookup_key: lookup_value},
                "fields": {
                    "归档路径": naming_result.get("archive_url"),
                    "版本号" if doc_type != "合同" else "归档状态": naming_result.get("resolved_version") or "已归档",
                    "状态" if doc_type != "合同" else "财务同步标记": extracted_document.get("status_label") or "已归档",
                },
            })
        )
    if account_plan_append.get("status") in {"pending", "lookup_required"}:
        updates.append(
            with_table_meta({
                "table_name": "Account Plan",
                "operation": "append",
                "record_lookup": {
                    "target_doc_ref": account_plan_append.get("target_doc_ref"),
                    "customer_id": (match_result.get("customer") or {}).get("customer_id"),
                },
                "fields": {
                    "source_label": account_plan_append.get("source_label"),
                    "lookup_context": account_plan_append.get("lookup_context"),
                },
            })
        )
    return updates


def build_prepare_feishu_skill_plan(
    session_state: dict[str, Any],
    naming_result: dict[str, Any],
    conflict_result: dict[str, Any],
    table_update_plan: list[dict[str, Any]],
) -> dict[str, Any]:
    mapping = load_feishu_skill_mapping()
    customer = (session_state.get("match_result") or {}).get("customer") or {}
    project = (session_state.get("match_result") or {}).get("project") or {}
    extracted = session_state.get("extracted_document") or {}
    schema_requirements = build_table_schema_requirements(table_update_plan)
    calls = [
        {
            "skill": mapping["skills"]["feishu-contact"],
            "intent": "search_user",
            "reason": "使用最新 openclaw-lark 协议时，联系人解析通过 feishu_search_user 完成。",
            "inputs": {
                "query": extracted.get("operator_name") or extracted.get("operator_id") or "",
                "page_size": 10,
            },
        },
        {
            "skill": mapping["skills"]["feishu-bitable"],
            "intent": "resolve_target_tables_and_schema",
            "reason": "执行前先读取多维表表结构，确认目标表、主键字段和必需字段是否存在。",
            "inputs": {
                "mode": "prepare_precheck",
                "candidate_tables": schema_requirements,
                "customer_id": customer.get("customer_id"),
                "project_id": project.get("project_id"),
                "document_type": extracted.get("document_type"),
            },
        },
        {
            "skill": mapping["skills"]["feishu-bitable"],
            "intent": "preflight_conflict_check",
            "reason": "所有结构化业务状态先落多维表，且冲突判断以索引表为真相源。",
            "inputs": {
                "tables": ["客户档案表", "项目总表", "文档归档索引表"],
                "record_lookup": {
                    "customer_id": customer.get("customer_id"),
                    "project_id": project.get("project_id"),
                    "document_type": extracted.get("document_type"),
                    "version_label": naming_result.get("resolved_version"),
                },
                "conflict_detected": conflict_result.get("blocking_conflict"),
            },
        },
    ]
    return {
        "status": "planned",
        "stage": "prepare",
        "business_skill": "S27",
        "sub_agent": "归档反馈 Agent",
        "skill_calls": calls,
    }


def build_feishu_skill_plan(
    session_state: dict[str, Any],
    action: str,
    naming_result: dict[str, Any],
    table_update_plan: list[dict[str, Any]],
    account_plan_append: dict[str, Any],
) -> dict[str, Any]:
    mapping = load_feishu_skill_mapping()
    customer_name = ((session_state.get("match_result") or {}).get("customer") or {}).get("customer_name") or (
        session_state.get("extracted_document") or {}
    ).get("customer_name")
    customer_id = ((session_state.get("match_result") or {}).get("customer") or {}).get("customer_id")
    project_id = ((session_state.get("match_result") or {}).get("project") or {}).get("project_id") or (
        session_state.get("extracted_document") or {}
    ).get("project_id")
    schema_requirements = build_table_schema_requirements(table_update_plan)
    materialized_updates = materialize_table_updates(table_update_plan)
    archive_execution_mode = (mapping.get("defaults") or {}).get("archive_execution_mode", "wiki_docx_only")
    folder_segments = build_archive_folder_segments(naming_result)
    calls = []
    reply_target = looks_like_feishu_receive_id(session_state["inputs"].get("thread_id"))
    archive_drive_call_id = "archive_source_file"
    calls.append(
        {
            "call_id": "resolve_archive_actors",
            "skill": mapping["skills"]["feishu-contact"],
            "intent": "search_user",
            "reason": "最新 openclaw-lark 联系人协议使用 feishu_search_user。",
            "inputs": {
                "query": session_state["inputs"]["operator_name"] or session_state["inputs"]["operator_id"] or customer_name or "",
                "page_size": 10,
            },
        }
    )
    if action != "cancel":
        if archive_execution_mode == "wiki_docx_only":
            calls.append(
                {
                    "call_id": "resolve_archive_root_node",
                    "skill": mapping["skills"]["feishu-wiki"],
                    "intent": "get_root_wiki_node",
                    "reason": "先通过 feishu_wiki_space_node.get 读取根 wiki 节点，获取真实的 space_id 和根 node 信息。",
                    "inputs": {
                        "action": "get",
                        "token": mapping["roots"]["customer_wiki_root"],
                        "obj_type": "wiki",
                    },
                }
            )
            calls.append(
                {
                    "call_id": "resolve_archive_parent_path",
                    "skill": mapping["skills"]["feishu-wiki"],
                    "intent": "resolve_archive_parent_path",
                    "reason": "归档测试只验证 wiki 落点。执行器需要从根节点开始，按 folder_segments 逐层 list/定位父节点，必要时补建缺失目录。",
                    "depends_on": ["resolve_archive_root_node"],
                    "inputs": {
                        "root_token": mapping["roots"]["customer_wiki_root"],
                        "folder_segments": folder_segments,
                        "folder_path": naming_result.get("folder_path"),
                        "create_missing_nodes": True,
                        "expected_leaf_title": folder_segments[-1] if folder_segments else "",
                    },
                }
            )
            calls.append(
                {
                    "call_id": "create_archive_docx_in_wiki",
                    "skill": mapping["skills"]["feishu-wiki"],
                    "intent": "create_archive_docx_under_parent",
                    "reason": "在目标父节点下创建 docx 实体节点，这是本轮验收的核心步骤。请调用 feishu_wiki_space_node.create，使用 root node 解析出的 space_id 和目标 parent_node_token。",
                    "depends_on": ["resolve_archive_parent_path"],
                    "inputs": {
                        "root_token": mapping["roots"]["customer_wiki_root"],
                        "folder_segments": folder_segments,
                        "folder_path": naming_result.get("folder_path"),
                        "title": naming_result.get("normalized_name"),
                        "obj_type": "docx",
                        "node_type": "origin",
                        "source_file_path": session_state["inputs"]["source"],
                        "archive_mode": "wiki_docx_only",
                    },
                }
            )
        else:
            calls.append(
                {
                    "call_id": archive_drive_call_id,
                    "skill": mapping["skills"]["feishu-drive"],
                    "intent": "upload",
                    "reason": "最新 openclaw-lark 通过 feishu_drive_file.upload 上传源文件。",
                    "inputs": {
                        "action": "upload",
                        "parent_node": mapping["roots"]["customer_document_root"],
                        "file_path": session_state["inputs"]["source"],
                    },
                }
            )
            if session_state["extracted_document"].get("document_type") == "拜访纪要":
                calls.append(
                    {
                        "call_id": "create_minutes_doc",
                        "skill": mapping["skills"]["feishu-doc-create"],
                        "intent": "create_doc",
                        "reason": "纪要正文使用 feishu-create-doc 创建到指定 wiki 节点下。",
                        "inputs": {
                            "title": naming_result.get("normalized_name"),
                            "wiki_node": mapping["roots"]["customer_wiki_root"],
                            "markdown": session_state["extracted_document"].get("minutes_markdown"),
                        },
                    }
                )
            calls.append(
                {
                    "call_id": "mount_archive_into_customer_tree",
                    "skill": mapping["skills"]["feishu-wiki"],
                    "intent": "get_root_wiki_node",
                    "reason": "最新 openclaw-lark 使用 feishu_wiki_space_node.get 解析根 wiki 节点信息。",
                    "inputs": {
                        "action": "get",
                        "token": mapping["roots"]["customer_wiki_root"],
                        "obj_type": "wiki",
                    },
                }
            )
            calls.append(
                {
                    "call_id": "write_archive_business_state",
                    "skill": mapping["skills"]["feishu-bitable"],
                    "intent": "resolve_target_tables_and_schema",
                    "reason": "正式写入前必须先读取当前多维表结构，确认目标表、主键字段与写入字段兼容。",
                    "inputs": {
                        "mode": "finalize_prewrite_validation",
                        "candidate_tables": schema_requirements,
                        "customer_id": customer_id,
                        "project_id": project_id,
                        "document_type": session_state["extracted_document"].get("document_type"),
                        "blocking_on_missing_fields": True,
                    },
                }
            )
            calls.append(
                {
                    "skill": mapping["skills"]["feishu-bitable"],
                    "intent": "write_archive_business_state",
                    "reason": "所有结构化业务状态统一落在 feishu-bitable。",
                    "inputs": {
                        "updates": materialized_updates,
                        "customer_id": customer_id,
                        "project_id": project_id,
                        "schema_validation_required": True,
                    },
                }
            )
            if account_plan_append.get("status") in {"pending", "lookup_required"}:
                calls.append(
                    {
                        "call_id": "locate_account_plan_in_customer_folder",
                        "skill": mapping["skills"]["feishu-search-doc-wiki"],
                        "intent": "search_account_plan",
                        "reason": "最新 openclaw-lark 通过 feishu_search_doc_wiki 搜索 Account Plan。",
                        "inputs": {
                            "action": "search",
                            "query": f"{customer_name} Account Plan",
                            "page_size": 10,
                        },
                    }
                )
                if account_plan_append.get("target_doc_ref"):
                    calls.append(
                        {
                            "call_id": "append_account_plan_summary",
                            "skill": mapping["skills"]["feishu-doc-update"],
                            "intent": "append_account_plan_summary",
                            "reason": "Account Plan 追加在最新协议中通过 feishu-update-doc append 完成。",
                            "inputs": {
                                "doc_id": account_plan_append.get("target_doc_ref"),
                                "mode": "append",
                                "markdown": render_account_plan_markdown(account_plan_append),
                            },
                        }
                    )
    if reply_target:
        receive_id_type, receive_id = reply_target
        calls.append(
            {
                "call_id": "send_archive_result",
                "skill": mapping["skills"]["feishu-im"],
                "intent": "send_result_message",
                "reason": "当 thread_id 本身就是 openclaw-lark 可识别的聊天目标时，直接通过 IM 工具发送结果文本。",
                "inputs": {
                    "action": "send",
                    "receive_id_type": receive_id_type,
                    "receive_id": receive_id,
                    "msg_type": "text",
                    "content": json.dumps(
                        {
                            "text": (
                                f"S27 {action} 完成\n"
                                f"文件名：{naming_result.get('normalized_name')}\n"
                                f"归档路径：{naming_result.get('folder_path')}"
                            )
                        },
                        ensure_ascii=False,
                    ),
                },
            }
        )
    return {"status": "planned", "stage": "finalize", "action": action, "business_skill": "S27", "sub_agent": "归档反馈 Agent", "skill_calls": calls}


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    require_real_feishu_roots()
    output_dir = ensure_dir(args.output_dir or Path("output") / "s27-document-archive-manager" / make_session_id())
    session_id = make_session_id()
    extracted_document = extract_document_facts(
        args.source,
        args.source_type,
        output_dir / "extracted_document.json",
        customer_hint=args.customer_hint,
    )
    extracted_document["operator_id"] = args.operator_id
    extracted_document["operator_name"] = args.operator_name
    extracted_document["thread_id"] = args.thread_id
    match_result = match_customer_project(
        extracted_document,
        args.thread_id,
        output_dir / "match_result.json",
        customer_hint=args.customer_hint,
        project_hint=args.project_hint,
    )
    conflict_result = check_version_conflict(extracted_document, match_result, output_dir / "version_check.json")
    naming_result = normalize_naming(
        extracted_document,
        match_result,
        conflict_result.get("existing_records", []),
        output_dir / "naming_result.json",
    )
    account_plan_append = build_account_plan_append(extracted_document, match_result, output_dir / "account_plan_append.json")
    table_update_plan = build_table_update_plan(extracted_document, match_result, naming_result, account_plan_append)
    write_json(output_dir / "table_update_plan.json", table_update_plan)
    state, confirmation_token = write_prepare_state(
        session_id=session_id,
        thread_id=args.thread_id,
        inputs={
            "source": args.source,
            "source_type": args.source_type,
            "operator_id": args.operator_id,
            "operator_name": args.operator_name,
            "thread_id": args.thread_id,
            "customer_hint": args.customer_hint,
            "project_hint": args.project_hint,
        },
        extracted_document=extracted_document,
        match_result=match_result,
        conflict_result=conflict_result,
        naming_result=naming_result,
        table_update_plan=table_update_plan,
        account_plan_append=account_plan_append,
        output_dir=output_dir,
    )
    card_payload = build_card_payload(
        extracted_document,
        match_result,
        conflict_result,
        naming_result,
        table_update_plan,
        account_plan_append,
        confirmation_token,
        output_dir / "card_payload.json",
    )
    feishu_skill_preview = build_prepare_feishu_skill_plan(state, naming_result, conflict_result, table_update_plan)
    write_json(output_dir / "feishu_skill_plan.preview.json", feishu_skill_preview)
    prepare_result = {
        "status": (
            "needs_confirmation"
            if match_result.get("status") != "matched" or conflict_result.get("blocking_conflict")
            else "ready_for_confirmation"
        ),
        "session_id": session_id,
        "output_dir": str(output_dir),
        "confirmation_token": confirmation_token,
        "extracted_document": extracted_document,
        "match_result": match_result,
        "version_check": conflict_result,
        "naming_result": naming_result,
        "table_update_plan": table_update_plan,
        "account_plan_append": account_plan_append,
        "card_payload": card_payload,
        "feishu_skill_plan_preview": feishu_skill_preview,
        "prepare_hash": state["prepare_hash"],
    }
    write_json(output_dir / "prepare_result.json", prepare_result)
    return prepare_result


def finalize(args: argparse.Namespace) -> dict[str, Any]:
    if not args.session_dir:
        raise ValueError("finalize 需要 --session-dir")
    state_path = args.session_dir / "session_state.json"
    state = read_json(state_path)
    if args.confirmation_token != state.get("confirmation_token"):
        raise ValueError("confirmation_token 不匹配。")
    if args.action == "cancel":
        state["status"] = "cancelled"
        state["selected_conflict_action"] = "cancel"
        feishu_skill_plan = build_feishu_skill_plan(
            state,
            args.action,
            state["naming_result"],
            [],
            state["account_plan_append"],
        )
        result = {
            "status": "cancelled",
            "written_targets": [],
            "skipped_targets": ["all"],
            "warnings": [],
            "audit_log": {"confirmed_by": args.confirmed_by, "action": args.action, "time": now_iso()},
        }
        write_json(args.session_dir / "feishu_skill_plan.json", feishu_skill_plan)
        write_json(args.session_dir / "finalize_result.json", result)
        write_json(state_path, state)
        return result

    require_real_feishu_roots()
    conflict_result = state["conflict_result"]
    naming_result = deep_copy(state["naming_result"])
    if conflict_result.get("blocking_conflict") and args.action not in {"overwrite", "save_as_new_version"}:
        raise ValueError("存在冲突时必须显式选择 overwrite 或 save_as_new_version。")
    if args.action == "save_as_new_version":
        existing_labels = [item.get("version_label", "") for item in conflict_result.get("existing_records", [])]
        from common import bump_version_label

        next_version = bump_version_label(existing_labels, naming_result.get("resolved_version"))
        naming_result = normalize_naming(
            state["extracted_document"],
            state["match_result"],
            conflict_result.get("existing_records", []),
            args.session_dir / "naming_result.finalized.json",
            forced_version_label=next_version,
        )
    table_update_plan = build_table_update_plan(
        state["extracted_document"],
        state["match_result"],
        naming_result,
        state["account_plan_append"],
    )
    state["status"] = "finalized"
    state["selected_conflict_action"] = args.action
    state["naming_result"] = naming_result
    state["table_update_plan"] = table_update_plan
    state["finalized_at"] = now_iso()
    state["finalize_hash"] = hash_payload({"action": args.action, "naming_result": naming_result})
    feishu_skill_plan = build_feishu_skill_plan(
        state,
        args.action,
        naming_result,
        table_update_plan,
        state["account_plan_append"],
    )
    result = {
        "status": "ready_for_feishu_skill_execution",
        "written_targets": [],
        "skipped_targets": [],
        "warnings": [] if state["account_plan_append"].get("status") in {"pending", "lookup_required"} else ["account_plan_pending"],
        "audit_log": {
            "confirmed_by": args.confirmed_by,
            "action": args.action,
            "time": now_iso(),
            "session_id": state["session_id"],
        },
        "resolved_naming": naming_result,
    }
    write_json(args.session_dir / "table_update_plan.finalized.json", table_update_plan)
    write_json(args.session_dir / "feishu_skill_plan.json", feishu_skill_plan)
    write_json(args.session_dir / "finalize_result.json", result)
    write_json(args.session_dir / "table_update_plan.json", state["table_update_plan"])
    write_json(state_path, state)
    return result


def completeness_check(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = ensure_dir(args.output_dir or Path("output") / "s27-document-archive-manager" / make_session_id("s27-check"))
    mapping = load_field_mapping()
    seed_data = mapping.get("seed_data", {})
    customer_hint = args.customer_hint or args.customer_id
    project_hint = args.project_hint or args.project_id
    customer = next(
        (
            item
            for item in seed_data.get("customers", [])
            if (args.customer_id and args.customer_id == item.get("customer_id"))
            or (customer_hint and customer_hint in item.get("customer_name", ""))
        ),
        None,
    )
    project = next(
        (
            item
            for item in seed_data.get("projects", [])
            if (args.project_id and args.project_id == item.get("project_id"))
            or (project_hint and project_hint == item.get("project_id"))
        ),
        None,
    )
    existing = [
        item
        for item in seed_data.get("document_index", [])
        if (not customer or item.get("customer_id") == customer.get("customer_id"))
        and (not project or item.get("project_id") == project.get("project_id"))
    ]
    required = mapping.get("completeness", {}).get("required_document_types", [])
    existing_types = sorted({item.get("document_type") for item in existing})
    missing = [item for item in required if item not in existing_types]
    result = {
        "customer": customer,
        "project": project,
        "required_items": required,
        "existing_items": existing_types,
        "missing_items": missing,
        "is_blocking_closeout": bool(missing),
        "notification_targets": [args.operator_id] if args.operator_id else [],
    }
    feishu_skill_plan = {
        "status": "planned",
        "action": "completeness_check",
        "stage": "completeness-check",
        "business_skill": "S27",
        "sub_agent": "归档反馈 Agent",
        "skill_calls": [
            {
                "skill": load_feishu_skill_mapping()["skills"]["feishu-bitable"],
                "intent": "resolve_target_tables_and_schema",
                "reason": "写入完整性检查结果前，先确认目标表存在且字段结构满足写入要求。",
                "inputs": {
                    "mode": "completeness_prewrite_validation",
                    "candidate_tables": [
                        build_table_schema_requirement(
                            "文档完整性检查表",
                            "insert",
                            {},
                            {
                                "客户编号": (customer or {}).get("customer_id"),
                                "项目编号": (project or {}).get("project_id"),
                                "检查日期": today_iso(),
                                "已归档项": existing_types,
                                "缺失项": missing,
                                "责任人": args.operator_name,
                                "是否阻塞结项": bool(missing),
                            },
                        )
                    ],
                    "customer_id": (customer or {}).get("customer_id"),
                    "project_id": (project or {}).get("project_id"),
                    "blocking_on_missing_fields": True,
                },
            },
            {
                "skill": load_feishu_skill_mapping()["skills"]["feishu-bitable"],
                "intent": "write_completeness_check_result",
                "reason": "完整性检查结果属于结构化业务状态，应落在 feishu-bitable。",
                "inputs": {
                    "table_name": "文档完整性检查表",
                    "app_token": load_field_mapping().get("tables", {}).get("文档完整性检查表", {}).get("app_token"),
                    "table_id": load_field_mapping().get("tables", {}).get("文档完整性检查表", {}).get("table_id"),
                    "key_field": load_field_mapping().get("tables", {}).get("文档完整性检查表", {}).get("key_field"),
                    "operation": "insert",
                    "fields": {
                        "客户编号": (customer or {}).get("customer_id"),
                        "项目编号": (project or {}).get("project_id"),
                        "检查日期": today_iso(),
                        "已归档项": existing_types,
                        "缺失项": missing,
                        "责任人": args.operator_name,
                        "是否阻塞结项": bool(missing),
                    },
                    "schema_validation_required": True,
                },
            },
        ],
    }
    write_json(output_dir / "completeness_check_result.json", result)
    # Keep completeness output isolated so it cannot clobber the archive finalize plan
    # when the caller reuses the same output directory after a successful archive.
    write_json(output_dir / "feishu_skill_plan.completeness.json", feishu_skill_plan)
    return result


def main() -> None:
    args = parse_args()
    if args.stage == "prepare":
        if not all([args.source, args.operator_id, args.operator_name, args.thread_id]):
            raise ValueError("prepare 需要 source/operator/thread 参数。")
        result = prepare(args)
    elif args.stage == "finalize":
        if not all([args.session_dir, args.confirmation_token, args.confirmed_by, args.action]):
            raise ValueError("finalize 需要 session-dir/confirmation-token/confirmed-by/action。")
        result = finalize(args)
    else:
        if not all([args.operator_id, args.operator_name, args.thread_id]):
            raise ValueError("completeness-check 需要 operator/thread 参数。")
        result = completeness_check(args)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
