from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from common import write_json


def build_card_payload(
    extracted_document: dict[str, Any],
    match_result: dict[str, Any],
    conflict_result: dict[str, Any],
    naming_result: dict[str, Any],
    table_update_plan: list[dict[str, Any]],
    account_plan_append: dict[str, Any],
    confirmation_token: str,
    output: Path,
) -> dict[str, Any]:
    actions = []
    if match_result.get("status") == "unmatched":
        actions = ["confirm_match", "cancel"]
    elif conflict_result.get("blocking_conflict"):
        actions = ["overwrite", "save_as_new_version", "cancel"]
    else:
        actions = ["confirm", "cancel"]

    payload = {
        "card_type": "s27_archive_confirmation",
        "confirmation_token": confirmation_token,
        "title": f"S27 归档确认 - {naming_result.get('normalized_name')}",
        "summary": {
            "document_type": extracted_document.get("document_type"),
            "customer": (match_result.get("customer") or {}).get("customer_name") or extracted_document.get("customer_name"),
            "project": (match_result.get("project") or {}).get("project_id") or extracted_document.get("project_id"),
            "folder_path": naming_result.get("folder_path"),
            "normalized_name": naming_result.get("normalized_name"),
            "version": naming_result.get("resolved_version"),
        },
        "match_status": match_result.get("status"),
        "conflict": conflict_result,
        "table_updates": table_update_plan,
        "account_plan": account_plan_append,
        "actions": [{"value": action, "label": action} for action in actions],
    }
    write_json(output, payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Build S27 card payload.")
    parser.add_argument("--document", type=Path, required=True)
    parser.add_argument("--match", type=Path, required=True)
    parser.add_argument("--conflict", type=Path, required=True)
    parser.add_argument("--naming", type=Path, required=True)
    parser.add_argument("--table-updates", type=Path, required=True)
    parser.add_argument("--account-plan", type=Path, required=True)
    parser.add_argument("--confirmation-token", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    import json

    build_card_payload(
        json.loads(args.document.read_text(encoding="utf-8")),
        json.loads(args.match.read_text(encoding="utf-8")),
        json.loads(args.conflict.read_text(encoding="utf-8")),
        json.loads(args.naming.read_text(encoding="utf-8")),
        json.loads(args.table_updates.read_text(encoding="utf-8")),
        json.loads(args.account_plan.read_text(encoding="utf-8")),
        args.confirmation_token,
        args.output,
    )


if __name__ == "__main__":
    main()
