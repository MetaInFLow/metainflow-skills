#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")"/.. && pwd)"
OUTPUT_DIR="${1:-/tmp/openclaw-s27-local}"
SESSION_ID="${S27_OPENCLAW_SESSION_ID:-s27-local-test}"

mkdir -p "$OUTPUT_DIR"

openclaw agent \
  --local \
  --json \
  --session-id "$SESSION_ID" \
  --thinking low \
  --timeout 180 \
  --message "请使用 s27-document-archive-manager skill，运行 prepare：source=${ROOT_DIR}/examples/visit_minutes_sample.txt，source-type=file，operator-id=local-test，operator-name=本地测试，thread-id=thread-local-s27，output-dir=${OUTPUT_DIR}。只返回 session_id、status 和输出文件列表。"
