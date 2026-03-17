from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a local OpenClaw config from a template without hardcoded machine paths."
    )
    parser.add_argument("--source", required=True, help="Template config path (e.g. openclaw.json)")
    parser.add_argument("--target", required=True, help="Output config path (e.g. openclaw.local.json)")
    parser.add_argument(
        "--runtime-root",
        required=True,
        help="Runtime root to create (workspaces/memory/sandboxes will be created under this path).",
    )
    parser.add_argument(
        "--replace",
        action="append",
        default=[],
        help="String replacement rule in form old=new, can be provided multiple times.",
    )
    parser.add_argument(
        "--default-model",
        default="volcengine-plan/kimi-k2.5",
        help="Value for agents.defaults.model.primary.",
    )
    return parser.parse_args()


def parse_replace_rules(raw_rules: list[str]) -> list[tuple[str, str]]:
    parsed: list[tuple[str, str]] = []
    for raw in raw_rules:
        if "=" not in raw:
            raise ValueError(f"Invalid --replace rule: {raw!r}. Expected format old=new.")
        old, new = raw.split("=", 1)
        parsed.append((old, new))
    return parsed


def rewrite_path(value: str, replacements: list[tuple[str, str]]) -> str:
    result = value
    for src, dst in replacements:
        result = result.replace(src, dst)
    return result


def rewrite_node(node: Any, replacements: list[tuple[str, str]]) -> Any:
    if isinstance(node, dict):
        return {key: rewrite_node(value, replacements) for key, value in node.items()}
    if isinstance(node, list):
        return [rewrite_node(item, replacements) for item in node]
    if isinstance(node, str):
        return rewrite_path(node, replacements)
    return node


def main() -> None:
    args = parse_args()
    source = Path(args.source).expanduser().resolve()
    target = Path(args.target).expanduser().resolve()
    runtime_root = Path(args.runtime_root).expanduser().resolve()
    replacements = parse_replace_rules(args.replace)

    config = json.loads(source.read_text(encoding="utf-8"))
    config = rewrite_node(config, replacements)
    config["agents"]["defaults"]["model"]["primary"] = args.default_model

    for directory in [
        runtime_root,
        runtime_root / "workspace",
        runtime_root / "workspace-main",
        runtime_root / "workspace-s4",
        runtime_root / "workspace-s5",
        runtime_root / "workspace-s11",
        runtime_root / "workspace-s27",
        runtime_root / "workspace-s28",
        runtime_root / "kb" / "policies",
        runtime_root / "kb" / "companies",
        runtime_root / "kb" / "templates",
        runtime_root / "memory",
        runtime_root / "sandboxes",
        runtime_root / "qmd-sessions",
    ]:
        directory.mkdir(parents=True, exist_ok=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(str(target))


if __name__ == "__main__":
    main()
