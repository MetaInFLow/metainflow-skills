# S27 Data Contracts

## `ExtractedDocument`

- `document_type`
- `customer_name`
- `project_id`
- `project_name`
- `document_date`
- `version_label`
- `status_label`
- `contract_id`
- `deliverable_name`
- `participants`
- `summary`
- `requirements`
- `decision_chain`
- `risks`
- `action_items`
- `evidence_refs`

## `MatchResult`

- `status`: `matched | ambiguous | unmatched`
- `customer`
- `project`
- `candidates`
- `notes`
- `enterprise_lookup`

## `VersionCheckResult`

- `blocking_conflict`
- `conflict_type`
- `existing_records`
- `recommended_actions`
- `notes`

## `NamingResult`

- `normalized_name`
- `folder_segments`
- `folder_path`
- `file_key`
- `resolved_version`

## `PrepareResult`

- `status`
- `session_id`
- `output_dir`
- `confirmation_token`
- `extracted_document`
- `match_result`
- `version_check`
- `naming_result`
- `table_update_plan`
- `account_plan_append`
- `card_payload`
- `feishu_skill_plan_preview`
- `prepare_hash`

## `TableSchemaRequirement`

- `table_name`
- `app_token`
- `table_id`
- `key_field`
- `operation`
- `required_fields`
- `record_lookup_fields`
- `update_fields`

补充约束：

- `required_fields` 必须基于 materialized 后的真实写入字段生成，不能包含被字段映射裁掉的内部字段。
- 空值字段不进入 `record_lookup_fields` / `update_fields`。

## `FinalizeResult`

- `status`
- `written_targets`
- `skipped_targets`
- `warnings`
- `audit_log`
- `resolved_naming`

## `feishu_skill_plan.json`

- `status`
- `stage`
- `action`
- `business_skill`
- `sub_agent`
- `skill_calls[]`
  - `skill`
  - `intent`
  - `reason`
  - `inputs`
    - `candidate_tables[]`（当 intent=`resolve_target_tables_and_schema`）
    - `schema_validation_required`（当写入依赖前置 schema 校验时）
