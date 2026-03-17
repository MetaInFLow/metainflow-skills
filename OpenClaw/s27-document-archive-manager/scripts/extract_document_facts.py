from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

from common import (
    clean_text,
    filename_stem,
    find_best_customer_hint,
    find_lines,
    load_field_mapping,
    maybe_write_text_source,
    parse_date_text,
    parse_doc,
    unique_strings,
    write_json,
)


PROJECT_RE = re.compile(r"\bQF-P-\d{4}\b", re.IGNORECASE)
CONTRACT_RE = re.compile(r"\bQF-HT-\d{4}\b", re.IGNORECASE)
VERSION_RE = re.compile(r"\bv\d+\b", re.IGNORECASE)


def infer_document_type(markdown: str, source_name: str) -> str:
    text = f"{source_name}\n{markdown}"
    if any(keyword in text for keyword in ("拜访纪要", "会议纪要", "会议转写")):
        return "拜访纪要"
    if sum(1 for keyword in ("参会人", "决策链", "下一步行动", "拜访") if keyword in text) >= 2:
        return "拜访纪要"
    checks = [
        ("验收单", ("验收确认书", "验收单")),
        ("合同", ("合同", "签署版", "甲方", "乙方")),
        ("报价", ("报价单", "报价", "待审")),
        ("方案", ("解决方案", "方案", "终稿")),
        ("交付物", ("交付物", "材料包", "实施计划")),
    ]
    for doc_type, keywords in checks:
        if any(keyword in text for keyword in keywords):
            return doc_type
    return "其他"


def extract_customer_name(markdown: str, seed_customers: list[dict[str, Any]], customer_hint: str | None = None) -> str | None:
    pattern = re.compile(r"(?:客户名称|客户|企业名称|企业|甲方)[:：]\s*([^\n]+)")
    match = pattern.search(markdown)
    if match:
        return clean_text(match.group(1)).split("，")[0].split(",")[0]
    if customer_hint:
        return clean_text(customer_hint)
    return find_best_customer_hint(markdown, seed_customers)


def extract_summary(markdown: str) -> str:
    lines = [clean_text(line) for line in markdown.splitlines() if clean_text(line)]
    if not lines:
        return ""
    return "；".join(lines[:3])


def extract_minutes_sections(markdown: str) -> dict[str, list[str]]:
    lines = [clean_text(line) for line in markdown.splitlines() if clean_text(line)]
    topic_summary = [
        line
        for line in lines
        if not any(prefix in line for prefix in ("客户：", "项目编号：", "日期：", "参会人：", "下一步行动："))
        and not any(keyword in line for keyword in ("决策链", "风险", "需求变化", "项目进展"))
    ]
    customer_feedback = [
        line for line in lines if "客户" in line and any(keyword in line for keyword in ("表示", "反馈", "提到", "认为", "希望"))
    ]
    requirement_changes = find_lines(markdown, "需求变化", "新增需求", "变更需求", "希望", "要求")
    project_progress = find_lines(markdown, "项目进展", "当前阶段", "已完成", "待办事项", "推进")
    return {
        "topic_summary": unique_strings(topic_summary[:3]),
        "customer_feedback": unique_strings(customer_feedback),
        "requirement_changes": unique_strings(requirement_changes),
        "project_progress": unique_strings(project_progress),
    }


def extract_status_label(markdown: str, source_name: str, doc_type: str) -> str | None:
    text = f"{source_name}\n{markdown}"
    if doc_type == "合同" and "签署版" in text:
        return "签署版"
    if doc_type in {"方案", "报价"} and "终稿" in text:
        return "终稿"
    if doc_type == "报价" and "待审" in text:
        return "待审"
    if doc_type == "拜访纪要":
        return "已整理"
    return None


def extract_action_items(markdown: str) -> list[str]:
    lines = find_lines(markdown, "下一步", "行动项", "待办", "跟进", "TODO")
    bullets = re.findall(r"(?:^|\n)[-•]\s*([^\n]+)", markdown)
    return unique_strings(lines + bullets)


def structure_action_items(action_items: list[str]) -> list[dict[str, Any]]:
    structured: list[dict[str, Any]] = []
    ignored_owner_labels = {"下一步行动", "行动项", "待办", "跟进", "todo", "TODO"}
    for index, item in enumerate(action_items, start=1):
        owner = None
        if "：" in item:
            maybe_owner, _, remainder = item.partition("：")
            if len(maybe_owner) <= 6 and maybe_owner not in ignored_owner_labels:
                owner = maybe_owner
                item = remainder or item
        due_date = parse_date_text(item) or "待确认"
        structured.append(
            {
                "seq": index,
                "item": clean_text(item),
                "owner": owner or "待确认",
                "due_date": due_date,
            }
        )
    return structured


def extract_participants(markdown: str) -> list[str]:
    lines = find_lines(markdown, "参会人", "参与人", "出席")
    participants: list[str] = []
    for line in lines:
        _, _, value = line.partition("：")
        fragment = value or line
        participants.extend(re.split(r"[、,，/ ]+", fragment))
    return unique_strings(participants)


def extract_evidence(markdown: str) -> dict[str, list[str]]:
    return {
        "decision_chain": find_lines(markdown, "决策", "拍板", "老板", "总经理", "采购"),
        "risks": find_lines(markdown, "风险", "问题", "担心", "预算", "竞品", "延期"),
        "requirements": find_lines(markdown, "需求", "希望", "要求", "目标"),
    }


def build_minutes_markdown(document: dict[str, Any]) -> str:
    topic_summary = document.get("topic_summary") or ["待补充"]
    customer_feedback = document.get("customer_feedback") or ["待补充"]
    requirement_changes = document.get("requirement_changes") or document.get("requirements") or ["待补充"]
    decision_chain = document.get("decision_chain") or ["待补充"]
    project_progress = document.get("project_progress") or ["待补充"]
    action_items = document.get("action_items_structured") or []
    action_lines = ["| 序号 | 事项 | 责任人 | 截止日期 |", "|---|---|---|---|"]
    for item in action_items:
        action_lines.append(
            f"| {item['seq']} | {item['item']} | {item['owner']} | {item['due_date']} |"
        )
    if len(action_lines) == 2:
        action_lines.append("| 1 | 待补充 | 待确认 | 待确认 |")
    return "\n".join(
        [
            f"# 拜访纪要 - {document.get('customer_name') or '待确认客户'}",
            f"- 日期：{(document.get('document_date') or '').replace('-', '/') or '待确认'}",
            f"- 参会人：{' / '.join(document.get('participants') or ['待确认'])}",
            f"- 关联项目：{document.get('project_id') or '待确认'}",
            "",
            "## 议题摘要",
            *[f"- {item}" for item in topic_summary],
            "",
            "## 客户反馈",
            *[f"- {item}" for item in customer_feedback],
            "",
            "## 需求变化",
            *[f"- {item}" for item in requirement_changes],
            "",
            "## 决策链",
            *[f"- {item}" for item in decision_chain],
            "",
            "## 项目进展",
            *[f"- {item}" for item in project_progress],
            "",
            "## 行动项",
            *action_lines,
            "",
            "## 更新来源",
            f"本次拜访记录，由 BeeClaw S27 自动生成，{document.get('archive_date') or document.get('document_date') or '待确认'}",
        ]
    )


def extract_document_facts(source: str, source_type: str, output: Path, customer_hint: str | None = None) -> dict[str, Any]:
    temp_path = None
    try:
        actual_source, temp_path = maybe_write_text_source(source, source_type)
        envelope = parse_doc(actual_source)
    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink(missing_ok=True)

    markdown = envelope.get("data", {}).get("markdown", "")
    resolved = envelope.get("data", {}).get("source", {}).get("resolved_path") or source
    source_name = filename_stem(str(resolved))
    document_type = infer_document_type(markdown, source_name)
    mapping = load_field_mapping()
    seed_customers = mapping.get("seed_data", {}).get("customers", [])
    project_match = PROJECT_RE.search(markdown)
    contract_match = CONTRACT_RE.search(markdown)
    version_match = VERSION_RE.search(f"{source_name}\n{markdown}")
    evidence = extract_evidence(markdown)
    minutes_sections = extract_minutes_sections(markdown) if document_type == "拜访纪要" else {}
    action_items = extract_action_items(markdown)
    document = {
        "source_type": source_type,
        "source": source,
        "resolved_source": resolved,
        "document_type": document_type,
        "customer_name": extract_customer_name(markdown, seed_customers, customer_hint),
        "project_id": project_match.group(0).upper() if project_match else None,
        "project_name": None,
        "document_date": parse_date_text(markdown) or parse_date_text(source_name),
        "version_label": version_match.group(0).lower() if version_match else None,
        "status_label": extract_status_label(markdown, source_name, document_type),
        "contract_id": contract_match.group(0).upper() if contract_match else None,
        "deliverable_name": "高新认定材料包" if "材料包" in markdown else None,
        "participants": extract_participants(markdown),
        "summary": extract_summary(markdown),
        "requirements": evidence["requirements"],
        "decision_chain": evidence["decision_chain"],
        "risks": evidence["risks"],
        "action_items": action_items,
        "action_items_structured": structure_action_items(action_items),
        "topic_summary": minutes_sections.get("topic_summary", []),
        "customer_feedback": minutes_sections.get("customer_feedback", []),
        "requirement_changes": minutes_sections.get("requirement_changes", []),
        "project_progress": minutes_sections.get("project_progress", []),
        "evidence_refs": [{"type": "source_markdown", "preview": line} for line in markdown.splitlines()[:5] if clean_text(line)],
        "parse_meta": envelope.get("meta", {}),
        "archive_date": None,
    }
    if document["document_type"] == "拜访纪要" and not document["status_label"]:
        document["status_label"] = "已整理"
    document["archive_date"] = document.get("document_date")
    if document["document_type"] == "拜访纪要":
        document["minutes_markdown"] = build_minutes_markdown(document)
    write_json(output, document)
    return document


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract S27 document facts.")
    parser.add_argument("--source", required=True)
    parser.add_argument("--source-type", choices=("file", "url", "text"), default="file")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--customer-hint")
    args = parser.parse_args()
    extract_document_facts(args.source, args.source_type, args.output, args.customer_hint)


if __name__ == "__main__":
    main()
