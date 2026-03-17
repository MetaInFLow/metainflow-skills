from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
CONFIG_DIR = SKILL_DIR / "config"
FIELD_MAPPING_PATH = CONFIG_DIR / "field_mapping.json"
NAMING_RULES_PATH = CONFIG_DIR / "naming_rules.json"
FEISHU_SKILL_MAPPING_PATH = CONFIG_DIR / "feishu_skill_mapping.json"
DATE_RE = re.compile(r"(20\d{2})[.\-/年](\d{1,2})[.\-/月](\d{1,2})")


def clean_text(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip())


def normalize_name(text: Any) -> str:
    value = clean_text(text)
    value = value.replace("（", "(").replace("）", ")")
    return re.sub(r"[“”\"'`]", "", value)


def slugify(text: Any) -> str:
    value = normalize_name(text).lower()
    value = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "-", value)
    return value.strip("-") or "unknown"


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_field_mapping(path: Path | None = None) -> dict[str, Any]:
    return read_json(path or FIELD_MAPPING_PATH)


def load_naming_rules(path: Path | None = None) -> dict[str, Any]:
    return read_json(path or NAMING_RULES_PATH)


def load_feishu_skill_mapping(path: Path | None = None) -> dict[str, Any]:
    return read_json(path or FEISHU_SKILL_MAPPING_PATH)


def is_openclaw_lark_only_mode() -> bool:
    return getenv_bool("S27_FEISHU_LARK_ONLY", True)


def fetch_bitable_records(table_name: str, view_id: str | None = None) -> list[dict[str, Any]]:
    _ = (table_name, view_id)
    if not is_openclaw_lark_only_mode():
        raise RuntimeError("S27 禁止直连飞书 API；请通过 openclaw-lark 的 feishu-bitable 执行查询。")
    return []


def fetch_drive_files(page_size: int = 200, folder_token: str | None = None) -> list[dict[str, Any]]:
    _ = (page_size, folder_token)
    if not is_openclaw_lark_only_mode():
        raise RuntimeError("S27 禁止直连飞书 API；请通过 openclaw-lark 的 feishu-drive 执行检索。")
    return []


def detect_metainflow_runner() -> list[str]:
    command = shutil.which("metainflow")
    if command:
        try:
            subprocess.run([command, "--help"], check=True, capture_output=True, text=True)
            return [command]
        except subprocess.SubprocessError:
            pass
    fallback = [sys.executable, "-m", "metainflow_studio_cli.main"]
    try:
        subprocess.run([*fallback, "--help"], check=True, capture_output=True, text=True)
        return fallback
    except subprocess.SubprocessError as exc:
        raise RuntimeError("metainflow CLI 不可用，请先在服务器安装 metainflow-studio-cli。") from exc


def run_cli_json(arguments: list[str]) -> dict[str, Any]:
    runner = detect_metainflow_runner()
    completed = subprocess.run([*runner, *arguments], check=False, capture_output=True, text=True)
    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()
    if not stdout:
        raise RuntimeError(f"CLI 未返回结果：{' '.join(arguments)}; stderr={stderr}")
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"CLI 输出不是合法 JSON：{stdout[:300]}") from exc
    if not payload.get("success", False):
        error = payload.get("error") or {}
        message = error.get("message") or stderr or "unknown error"
        raise RuntimeError(f"CLI 调用失败：{message}")
    return payload


def parse_doc(source: str) -> dict[str, Any]:
    return run_cli_json(["parse-doc", "--file", source, "--output", "json"])


def enterprise_search(keyword: str, session_id: str) -> dict[str, Any]:
    return run_cli_json(["enterprise-search", "--keyword", keyword, "--session-id", session_id, "--output", "json"])


def enterprise_query(keyword: str, session_id: str) -> dict[str, Any]:
    return run_cli_json(
        ["enterprise-query", "--type", "business", "--keyword", keyword, "--session-id", session_id, "--output", "json"]
    )


def maybe_write_text_source(source: str, source_type: str) -> tuple[str, Path | None]:
    if source_type != "text":
        return source, None
    handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".txt", delete=False)
    handle.write(source)
    handle.flush()
    handle.close()
    return handle.name, Path(handle.name)


def parse_date_text(text: Any) -> str | None:
    value = str(text or "")
    match = DATE_RE.search(value)
    if match:
        year, month, day = match.groups()
        return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
    iso = re.search(r"(20\d{2}-\d{2}-\d{2})", value)
    if iso:
        return iso.group(1)
    return None


def today_iso() -> str:
    return date.today().isoformat()


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def make_confirmation_token(session_id: str, payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    digest = hashlib.sha256(f"{session_id}:{raw}".encode("utf-8")).hexdigest()
    return digest[:20]


def make_session_id(prefix: str = "s27") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def hash_payload(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def filename_stem(path_or_name: str) -> str:
    return Path(path_or_name).stem


def sanitize_filename(value: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "_", value).strip()


def parse_version_number(value: Any) -> int | None:
    text = clean_text(value).lower()
    match = re.search(r"\bv(\d+)\b", text)
    return int(match.group(1)) if match else None


def bump_version_label(existing_labels: list[str], current_label: str | None = None) -> str:
    numbers = [parse_version_number(label) for label in existing_labels]
    numeric = [number for number in numbers if number is not None]
    if current_label:
        current = parse_version_number(current_label)
        if current is not None:
            numeric.append(current)
    next_version = max(numeric or [0]) + 1
    return f"v{next_version}"


def find_best_customer_hint(text: str, candidates: list[dict[str, Any]]) -> str | None:
    normalized_text = normalize_name(text)
    for candidate in candidates:
        name = normalize_name(candidate.get("customer_name") or candidate.get("name"))
        if name and name in normalized_text:
            return candidate.get("customer_name") or candidate.get("name")
    return None


def find_lines(text: str, *keywords: str) -> list[str]:
    result: list[str] = []
    for line in str(text or "").splitlines():
        cleaned = clean_text(line)
        if cleaned and any(keyword in cleaned for keyword in keywords):
            result.append(cleaned)
    return result


def unique_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = clean_text(value)
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return result


def deep_copy(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def getenv_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}
