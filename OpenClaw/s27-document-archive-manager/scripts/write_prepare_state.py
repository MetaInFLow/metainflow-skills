from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from common import hash_payload, make_confirmation_token, now_iso, write_json


def write_prepare_state(
    session_id: str,
    thread_id: str,
    inputs: dict[str, Any],
    extracted_document: dict[str, Any],
    match_result: dict[str, Any],
    conflict_result: dict[str, Any],
    naming_result: dict[str, Any],
    table_update_plan: list[dict[str, Any]],
    account_plan_append: dict[str, Any],
    output_dir: Path,
) -> tuple[dict[str, Any], str]:
    snapshot = {
        "inputs": inputs,
        "extracted_document": extracted_document,
        "match_result": match_result,
        "conflict_result": conflict_result,
        "naming_result": naming_result,
        "table_update_plan": table_update_plan,
        "account_plan_append": account_plan_append,
    }
    confirmation_token = make_confirmation_token(session_id, snapshot)
    state = {
        "session_id": session_id,
        "thread_id": thread_id,
        "confirmation_token": confirmation_token,
        "prepare_hash": hash_payload(snapshot),
        "status": "pending_confirmation",
        "selected_match": None,
        "selected_conflict_action": None,
        "openclaw_message_ref": None,
        "created_at": now_iso(),
        **snapshot,
    }
    write_json(output_dir / "session_state.json", state)
    return state, confirmation_token


def main() -> None:
    parser = argparse.ArgumentParser(description="Write S27 session state.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--thread-id", required=True)
    args = parser.parse_args()
    raise SystemExit("请通过 run_pipeline.py 调用 write_prepare_state。")


if __name__ == "__main__":
    main()
