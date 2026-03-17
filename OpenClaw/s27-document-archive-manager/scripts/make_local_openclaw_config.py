from __future__ import annotations

import json
from pathlib import Path


ROOT = Path("/Users/zsy/Desktop/openclaw/BeeClaw")
SOURCE = ROOT / "test" / "openclaw.json"
TARGET = ROOT / "test" / "openclaw.local.json"
RUNTIME_ROOT = ROOT / "test" / "openclaw-runtime-local"


def rewrite_path(value: str) -> str:
    replacements = {
        "/Users/anthonyf/Desktop/Personal/code_study/claws/openclaw-runtime-online": str(RUNTIME_ROOT),
        "/Users/anthonyf/.openclaw/sandboxes": str(RUNTIME_ROOT / "sandboxes"),
        "/Users/anthonyf/Desktop/Personal/code_study/claws/metainflow-studio-cli-local/metainflow-skills": str(
            ROOT / "metainflow-studio-cli" / "metainflow-skills"
        ),
        "/Users/anthonyf/projects/metainflow/metainflow-skills/OpenClaw": str(ROOT / "metainflow-skills" / "OpenClaw"),
    }
    result = value
    for src, dst in replacements.items():
        result = result.replace(src, dst)
    result = result.replace("/Users/anthonyf", "/Users/zsy")
    return result


def rewrite_node(node):
    if isinstance(node, dict):
        return {key: rewrite_node(value) for key, value in node.items()}
    if isinstance(node, list):
        return [rewrite_node(item) for item in node]
    if isinstance(node, str):
        return rewrite_path(node)
    return node


def main() -> None:
    config = json.loads(SOURCE.read_text(encoding="utf-8"))
    config = rewrite_node(config)
    config["agents"]["defaults"]["model"]["primary"] = "volcengine-plan/kimi-k2.5"
    for directory in [
        RUNTIME_ROOT,
        RUNTIME_ROOT / "workspace",
        RUNTIME_ROOT / "workspace-main",
        RUNTIME_ROOT / "workspace-s4",
        RUNTIME_ROOT / "workspace-s5",
        RUNTIME_ROOT / "workspace-s11",
        RUNTIME_ROOT / "workspace-s27",
        RUNTIME_ROOT / "workspace-s28",
        RUNTIME_ROOT / "kb" / "policies",
        RUNTIME_ROOT / "kb" / "companies",
        RUNTIME_ROOT / "kb" / "templates",
        RUNTIME_ROOT / "memory",
        RUNTIME_ROOT / "sandboxes",
        RUNTIME_ROOT / "qmd-sessions",
    ]:
        directory.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(str(TARGET))


if __name__ == "__main__":
    main()
