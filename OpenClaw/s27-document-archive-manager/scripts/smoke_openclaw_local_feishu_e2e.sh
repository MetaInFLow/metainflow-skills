#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")"/.. && pwd)"
OUTPUT_DIR="${1:-/tmp/openclaw-s27-local-feishu-e2e}"
SOURCE_FILE="${2:-${ROOT_DIR}/examples/visit_minutes_sample.txt}"

SESSION_ID="${S27_OPENCLAW_SESSION_ID:-s27-local-feishu-e2e}"
THREAD_ID="${S27_THREAD_ID:-thread-local-s27-feishu-e2e}"
OPERATOR_ID="${S27_OPERATOR_ID:-local-feishu-e2e}"
OPERATOR_NAME="${S27_OPERATOR_NAME:-本地飞书联调}"
ACTION="${S27_ACTION:-save_as_new_version}"
OPENCLAW_AGENT_MODE="${S27_OPENCLAW_AGENT_MODE:---agent s27}"
EXEC_TIMEOUT="${S27_EXEC_TIMEOUT:-420}"
EXEC_RETRIES="${S27_EXEC_RETRIES:-2}"

SKIP_EXECUTE="${S27_SKIP_EXECUTE:-false}"

mkdir -p "$OUTPUT_DIR"

echo "[1/4] prepare (local deterministic pipeline)"
python3 "$ROOT_DIR/scripts/run_pipeline.py" \
  --stage prepare \
  --source "$SOURCE_FILE" \
  --source-type file \
  --operator-id "$OPERATOR_ID" \
  --operator-name "$OPERATOR_NAME" \
  --thread-id "$THREAD_ID" \
  --output-dir "$OUTPUT_DIR"

CONFIRMATION_TOKEN="$(python3 - <<'PY' "$OUTPUT_DIR/prepare_result.json"
import json
import sys
path = sys.argv[1]
data = json.load(open(path, "r", encoding="utf-8"))
print(data["confirmation_token"])
PY
)"

echo "[2/4] finalize with action=${ACTION}"
python3 "$ROOT_DIR/scripts/run_pipeline.py" \
  --stage finalize \
  --session-dir "$OUTPUT_DIR" \
  --confirmation-token "$CONFIRMATION_TOKEN" \
  --confirmed-by "$OPERATOR_ID" \
  --action "$ACTION"

if [[ "$SKIP_EXECUTE" == "true" ]]; then
  echo "[3/4] skip execute: S27_SKIP_EXECUTE=true"
  echo "Plan generated at: $OUTPUT_DIR/feishu_skill_plan.json"
  exit 0
fi

PLAN_PATH="$OUTPUT_DIR/feishu_skill_plan.json"
if [[ ! -f "$PLAN_PATH" ]]; then
  echo "ERROR: plan not found: $PLAN_PATH" >&2
  exit 1
fi

EXEC_LOG="$OUTPUT_DIR/openclaw_execute_result.jsonl"
LAST_LOG="$EXEC_LOG"

echo "[3/4] execute feishu_skill_plan.json via OpenClaw (${OPENCLAW_AGENT_MODE})"
attempt=1
while [[ "$attempt" -le "$EXEC_RETRIES" ]]; do
  ATTEMPT_LOG="${OUTPUT_DIR}/openclaw_execute_result.attempt${attempt}.jsonl"
  openclaw agent \
    ${OPENCLAW_AGENT_MODE} \
    --json \
    --session-id "$SESSION_ID" \
    --thinking low \
    --timeout "$EXEC_TIMEOUT" \
    --message "请作为执行器，不要编辑本地 memory 文件来替代执行。读取并执行这个计划文件：${PLAN_PATH}。严格按 skill_calls 顺序调用对应 Feishu_Skills。执行完成后只返回 JSON，格式为：{\"status\":\"ok|failed\",\"bitable_receipts\":[{\"table_name\":\"\",\"operation\":\"\",\"record_id\":\"\"}],\"drive_receipts\":[],\"wiki_receipts\":[],\"errors\":[]}" \
    | tee "$ATTEMPT_LOG"
  LAST_LOG="$ATTEMPT_LOG"
  if rg -n "\"record_id\"\\s*:\\s*\"" "$ATTEMPT_LOG" >/dev/null 2>&1; then
    cp "$ATTEMPT_LOG" "$EXEC_LOG"
    break
  fi
  if [[ "$attempt" -lt "$EXEC_RETRIES" ]]; then
    echo "WARN: attempt ${attempt} has no record_id, retrying..."
  fi
  attempt=$((attempt + 1))
done

echo "[4/4] verify execution receipts"
if ! rg -n "\"record_id\"\\s*:\\s*\"" "$LAST_LOG" >/dev/null 2>&1; then
  echo "ERROR: no record_id found in execution output after ${EXEC_RETRIES} attempt(s). This run cannot prove Feishu Bitable write succeeded." >&2
  echo "Inspect: $LAST_LOG" >&2
  exit 2
fi

cp "$LAST_LOG" "$EXEC_LOG"

echo "SUCCESS: found record_id in execution output."
echo "prepare_result: $OUTPUT_DIR/prepare_result.json"
echo "finalize_result: $OUTPUT_DIR/finalize_result.json"
echo "execution_log : $EXEC_LOG"
