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
