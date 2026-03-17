from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run_pipeline.py"
EXAMPLES = ROOT / "examples"


def run_pipeline(tmp_path: Path, *args: str) -> dict:
    completed = subprocess.run(
        [sys.executable, str(RUNNER), *args],
        check=True,
        text=True,
        capture_output=True,
        cwd=ROOT,
    )
    return json.loads(completed.stdout)


def test_prepare_visit_minutes_generates_card_payload(tmp_path: Path) -> None:
    output_dir = tmp_path / "prepare-minutes"
    result = run_pipeline(
        tmp_path,
        "--stage",
        "prepare",
        "--source",
        str(EXAMPLES / "visit_minutes_sample.txt"),
        "--source-type",
        "file",
        "--operator-id",
        "u-001",
        "--operator-name",
        "王工",
        "--thread-id",
        "thread-001",
        "--output-dir",
        str(output_dir),
    )
    assert result["extracted_document"]["document_type"] == "拜访纪要"
    assert result["match_result"]["status"] == "matched"
    assert (output_dir / "card_payload.json").exists()
    card = json.loads((output_dir / "card_payload.json").read_text(encoding="utf-8"))
    assert card["summary"]["customer"] == "深圳某科技"
    assert card["actions"][0]["value"] == "confirm"
    assert "## 客户反馈" in result["extracted_document"]["minutes_markdown"]
    assert result["extracted_document"]["action_items_structured"][0]["owner"] == "待确认"
    assert result["account_plan_append"]["lookup_context"]["preferred_folder_segments"][-1] == "01_客户档案"


def test_prepare_proposal_detects_version_conflict(tmp_path: Path) -> None:
    output_dir = tmp_path / "prepare-proposal"
    result = run_pipeline(
        tmp_path,
        "--stage",
        "prepare",
        "--source",
        str(EXAMPLES / "proposal_v2_sample.txt"),
        "--source-type",
        "file",
        "--operator-id",
        "u-002",
        "--operator-name",
        "陈工",
        "--thread-id",
        "thread-002",
        "--output-dir",
        str(output_dir),
    )
    assert result["version_check"]["blocking_conflict"] is True
    card = json.loads((output_dir / "card_payload.json").read_text(encoding="utf-8"))
    assert [item["value"] for item in card["actions"]] == ["overwrite", "save_as_new_version", "cancel"]


def test_finalize_save_as_new_version_updates_naming(tmp_path: Path) -> None:
    output_dir = tmp_path / "finalize-proposal"
    prepare_result = run_pipeline(
        tmp_path,
        "--stage",
        "prepare",
        "--source",
        str(EXAMPLES / "proposal_v2_sample.txt"),
        "--source-type",
        "file",
        "--operator-id",
        "u-003",
        "--operator-name",
        "陈工",
        "--thread-id",
        "thread-003",
        "--output-dir",
        str(output_dir),
    )
    finalize_result = run_pipeline(
        tmp_path,
        "--stage",
        "finalize",
        "--session-dir",
        str(output_dir),
        "--confirmation-token",
        prepare_result["confirmation_token"],
        "--confirmed-by",
        "陈工",
        "--action",
        "save_as_new_version",
    )
    assert finalize_result["status"] == "ready_for_feishu_skill_execution"
    assert finalize_result["resolved_naming"]["resolved_version"] == "v3"
    execution_plan = json.loads((output_dir / "feishu_skill_plan.json").read_text(encoding="utf-8"))
    assert execution_plan["action"] == "save_as_new_version"
    assert execution_plan["skill_calls"][0]["skill"] == "feishu-contact"
    assert any(call["intent"] == "locate_account_plan_in_customer_folder" for call in execution_plan["skill_calls"]) is False


def test_finalize_cancel_produces_no_write_operations(tmp_path: Path) -> None:
    output_dir = tmp_path / "cancel-minutes"
    prepare_result = run_pipeline(
        tmp_path,
        "--stage",
        "prepare",
        "--source",
        str(EXAMPLES / "visit_minutes_sample.txt"),
        "--source-type",
        "file",
        "--operator-id",
        "u-004",
        "--operator-name",
        "王工",
        "--thread-id",
        "thread-004",
        "--output-dir",
        str(output_dir),
    )
    finalize_result = run_pipeline(
        tmp_path,
        "--stage",
        "finalize",
        "--session-dir",
        str(output_dir),
        "--confirmation-token",
        prepare_result["confirmation_token"],
        "--confirmed-by",
        "王工",
        "--action",
        "cancel",
    )
    assert finalize_result["status"] == "cancelled"
    execution_plan = json.loads((output_dir / "feishu_skill_plan.json").read_text(encoding="utf-8"))
    assert execution_plan["action"] == "cancel"
    assert execution_plan["skill_calls"][-1]["skill"] == "feishu-im"


def test_finalize_minutes_plan_contains_account_plan_lookup_calls(tmp_path: Path) -> None:
    output_dir = tmp_path / "finalize-minutes"
    prepare_result = run_pipeline(
        tmp_path,
        "--stage",
        "prepare",
        "--source",
        str(EXAMPLES / "visit_minutes_sample.txt"),
        "--source-type",
        "file",
        "--operator-id",
        "u-008",
        "--operator-name",
        "王工",
        "--thread-id",
        "thread-008",
        "--output-dir",
        str(output_dir),
    )
    run_pipeline(
        tmp_path,
        "--stage",
        "finalize",
        "--session-dir",
        str(output_dir),
        "--confirmation-token",
        prepare_result["confirmation_token"],
        "--confirmed-by",
        "王工",
        "--action",
        "confirm",
    )
    execution_plan = json.loads((output_dir / "feishu_skill_plan.json").read_text(encoding="utf-8"))
    intents = [call["intent"] for call in execution_plan["skill_calls"]]
    assert "locate_account_plan_in_customer_folder" in intents
    assert "locate_account_plan_wiki_node" in intents
    assert "append_account_plan_summary" in intents


def test_completeness_check_marks_blocking(tmp_path: Path) -> None:
    output_dir = tmp_path / "completeness"
    result = run_pipeline(
        tmp_path,
        "--stage",
        "completeness-check",
        "--customer-hint",
        "深圳某科技",
        "--project-hint",
        "QF-P-0078",
        "--operator-id",
        "u-005",
        "--operator-name",
        "主管",
        "--thread-id",
        "thread-005",
        "--output-dir",
        str(output_dir),
    )
    assert result["is_blocking_closeout"] is True
    assert "交付物" in result["missing_items"]
    feishu_skill_plan = json.loads((output_dir / "feishu_skill_plan.json").read_text(encoding="utf-8"))
    assert feishu_skill_plan["skill_calls"][0]["skill"] == "feishu-bitable"


def test_completeness_check_accepts_customer_and_project_ids(tmp_path: Path) -> None:
    output_dir = tmp_path / "completeness-by-id"
    result = run_pipeline(
        tmp_path,
        "--stage",
        "completeness-check",
        "--customer-id",
        "QF-C-0042",
        "--project-id",
        "QF-P-0078",
        "--operator-id",
        "u-006",
        "--operator-name",
        "主管",
        "--thread-id",
        "thread-006",
        "--output-dir",
        str(output_dir),
    )
    assert result["customer"]["customer_id"] == "QF-C-0042"
    assert result["project"]["project_id"] == "QF-P-0078"
    assert result["is_blocking_closeout"] is True


def test_prepare_detects_same_name_conflict_in_drive(tmp_path: Path) -> None:
    proposal = tmp_path / "drive-conflict-proposal.txt"
    proposal.write_text(
        "\n".join(
            [
                "客户：深圳市某科技有限公司",
                "项目编号：QF-P-0099",
                "日期：2026-03-17",
                "文档类型：方案",
                "版本：v1",
                "状态：终稿",
                "",
                "这是一个用于验证目录同名冲突的方案终稿。",
            ]
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "prepare-drive-conflict"
    result = run_pipeline(
        tmp_path,
        "--stage",
        "prepare",
        "--source",
        str(proposal),
        "--source-type",
        "file",
        "--operator-id",
        "u-007",
        "--operator-name",
        "陈工",
        "--thread-id",
        "thread-007",
        "--output-dir",
        str(output_dir),
    )
    assert result["version_check"]["blocking_conflict"] is True
    assert result["version_check"]["conflict_type"] == "same_name_in_drive"
    assert result["version_check"]["expected_file_name"] == "QF-P-0099_v1_终稿"
