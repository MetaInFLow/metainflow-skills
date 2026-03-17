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
from urllib import error, parse, request


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


def is_real_feishu_bitable_enabled() -> bool:
    return getenv_bool("S27_ENABLE_REAL_FEISHU_BITABLE", True)


def is_real_feishu_drive_enabled() -> bool:
    return getenv_bool("S27_ENABLE_REAL_FEISHU_DRIVE", True)


def get_feishu_app_credentials() -> tuple[str, str] | None:
    app_id = os.getenv("FEISHU_APP_ID") or os.getenv("LARK_APP_ID")
    app_secret = os.getenv("FEISHU_APP_SECRET") or os.getenv("LARK_APP_SECRET")
    if app_id and app_secret:
        return app_id, app_secret
    return None


def get_feishu_api_base() -> str:
    return os.getenv("FEISHU_API_BASE", "https://open.feishu.cn").rstrip("/")


def _http_json(method: str, url: str, payload: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> dict[str, Any]:
    body = None
    request_headers = {"Content-Type": "application/json; charset=utf-8"}
    if headers:
        request_headers.update(headers)
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(url, data=body, headers=request_headers, method=method)
    try:
        with request.urlopen(req, timeout=20) as response:
            raw = response.read().decode("utf-8")
    except error.HTTPError as exc:  # pragma: no cover - network dependent
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Feishu API 请求失败：{exc.code} {detail[:300]}") from exc
    except error.URLError as exc:  # pragma: no cover - network dependent
        raise RuntimeError(f"Feishu API 网络错误：{exc}") from exc
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        raise RuntimeError(f"Feishu API 返回非 JSON：{raw[:300]}") from exc


def get_feishu_tenant_access_token() -> str:
    credentials = get_feishu_app_credentials()
    if not credentials:
        raise RuntimeError("缺少飞书应用凭证 FEISHU_APP_ID/FEISHU_APP_SECRET。")
    app_id, app_secret = credentials
    payload = _http_json(
        "POST",
        f"{get_feishu_api_base()}/open-apis/auth/v3/tenant_access_token/internal",
        {"app_id": app_id, "app_secret": app_secret},
    )
    if payload.get("code") != 0:
        raise RuntimeError(f"获取 tenant_access_token 失败：{payload}")
    token = payload.get("tenant_access_token")
    if not token:
        raise RuntimeError("飞书返回中缺少 tenant_access_token。")
    return token


def _extract_bitable_fields(record: dict[str, Any]) -> dict[str, Any]:
    if "fields" in record and isinstance(record["fields"], dict):
        fields = deep_copy(record["fields"])
        if record.get("record_id"):
            fields["record_id"] = record["record_id"]
        return fields
    return deep_copy(record)


def fetch_bitable_records(table_name: str, view_id: str | None = None) -> list[dict[str, Any]]:
    if not is_real_feishu_bitable_enabled():
        return []
    credentials = get_feishu_app_credentials()
    if not credentials:
        return []
    table_config = load_field_mapping().get("tables", {}).get(table_name) or {}
    app_token = table_config.get("app_token")
    table_id = table_config.get("table_id")
    if not app_token or not table_id or app_token.endswith("_demo") or table_id.endswith("_demo"):
        return []
    token = get_feishu_tenant_access_token()
    query = {"page_size": "500"}
    final_view_id = view_id or table_config.get("view_id")
    if final_view_id:
        query["view_id"] = final_view_id
    url = (
        f"{get_feishu_api_base()}/open-apis/bitable/v1/apps/{parse.quote(app_token, safe='')}"
        f"/tables/{parse.quote(table_id, safe='')}/records?{parse.urlencode(query)}"
    )
    payload = _http_json("GET", url, headers={"Authorization": f"Bearer {token}"})
    if payload.get("code") != 0:
        raise RuntimeError(f"读取多维表 {table_name} 失败：{payload}")
    items = ((payload.get("data") or {}).get("items")) or []
    return [_extract_bitable_fields(item) for item in items]


def _normalize_drive_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "file_token": item.get("token") or item.get("file_token"),
        "file_name": item.get("name") or item.get("title") or item.get("file_name"),
        "type": item.get("type"),
        "parent_token": item.get("parent_token"),
        "url": item.get("url") or item.get("shortcut_info", {}).get("target_url"),
        "folder_path": item.get("folder_path") or item.get("path"),
    }


def fetch_drive_files(page_size: int = 200, folder_token: str | None = None) -> list[dict[str, Any]]:
    if not is_real_feishu_drive_enabled():
        return []
    credentials = get_feishu_app_credentials()
    if not credentials:
        return []
    token = get_feishu_tenant_access_token()
    query = {"page_size": str(page_size)}
    if folder_token:
        query["folder_token"] = folder_token
    url = f"{get_feishu_api_base()}/open-apis/drive/v1/files?{parse.urlencode(query)}"
    payload = _http_json("GET", url, headers={"Authorization": f"Bearer {token}"})
    if payload.get("code") != 0:
        raise RuntimeError(f"读取飞书 Drive 文件失败：{payload}")
    items = ((payload.get("data") or {}).get("files")) or ((payload.get("data") or {}).get("items")) or []
    return [_normalize_drive_item(item) for item in items]


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
