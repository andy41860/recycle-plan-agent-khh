"""Agent Skills：掃描、載入、受限地執行腳本。"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from langchain_core.tools import tool

from .. import config

SCRIPT_TIMEOUT = 10
STDERR_LIMIT = 1000
_FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?", re.DOTALL)


def _split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    meta: dict[str, str] = {}
    for line in m.group(1).splitlines():
        key, sep, value = line.partition(":")
        if sep:
            meta[key.strip()] = value.strip()
    return meta, text[m.end():]


def list_skills(skills_dir: Path | None = None) -> list[dict[str, str]]:
    skills_dir = skills_dir or config.SKILLS_DIR
    found = []
    if not skills_dir.is_dir():
        return found
    for md in sorted(skills_dir.glob("*/SKILL.md")):
        meta, _ = _split_frontmatter(md.read_text(encoding="utf-8"))
        found.append({"name": meta.get("name") or md.parent.name, "description": meta.get("description", "")})
    return found


def skills_prompt(skills_dir: Path | None = None) -> str:
    return "\n".join(f"- {s['name']}：{s['description']}" for s in list_skills(skills_dir))


def load_skill_text(name: str, skills_dir: Path | None = None) -> str:
    skills_dir = skills_dir or config.SKILLS_DIR
    for md in sorted(skills_dir.glob("*/SKILL.md")) if skills_dir.is_dir() else []:
        meta, body = _split_frontmatter(md.read_text(encoding="utf-8"))
        if (meta.get("name") or md.parent.name) == name:
            return body.strip()
    names = ", ".join(s["name"] for s in list_skills(skills_dir)) or "（無）"
    return f"找不到 skill「{name}」。可用的 skills：{names}"


def _resolve_script(skill: str, script: str, skills_dir: Path) -> Path:
    base = skills_dir.resolve()
    skill_dir = (base / skill).resolve()
    if skill_dir.parent != base:
        raise ValueError(f"不合法的 skill 名稱：{skill!r}")
    scripts_dir = skill_dir / "scripts"
    path = (scripts_dir / script).resolve()
    if not path.is_relative_to(scripts_dir.resolve()):
        raise ValueError(f"腳本必須位於 skills/{skill}/scripts/ 內：{script!r}")
    if path.suffix != ".py":
        raise ValueError("只能執行 .py 腳本")
    if not path.is_file():
        raise ValueError(f"找不到腳本：{skill}/scripts/{script}")
    return path


def run_script(
    skill: str,
    script: str,
    input_json: str,
    skills_dir: Path | None = None,
    timeout: float = SCRIPT_TIMEOUT,
) -> str:
    """執行 skill 腳本，回傳 stdout（JSON 字串）；任何失敗都回傳錯誤訊息而不丟例外。"""
    skills_dir = skills_dir or config.SKILLS_DIR
    try:
        json.loads(input_json)
    except (TypeError, ValueError) as e:
        return f"錯誤：input_json 不是合法 JSON，未執行腳本。{e}"
    try:
        path = _resolve_script(skill, script, skills_dir)
    except (ValueError, OSError) as e:
        return f"錯誤：{e}"
    try:
        proc = subprocess.run(
            [sys.executable, str(path)],
            input=input_json,
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=path.parent.parent,
            env={**os.environ, "PYTHONUTF8": "1"},
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return f"錯誤：腳本執行逾時（{timeout:g} 秒）"
    except OSError as e:
        return f"錯誤：無法執行腳本：{e}"
    if proc.returncode != 0:
        return f"錯誤：腳本結束碼 {proc.returncode}。stderr：{proc.stderr.strip()[:STDERR_LIMIT]}"
    out = proc.stdout.strip()
    try:
        json.loads(out)
    except ValueError:
        return f"錯誤：腳本輸出不是 JSON。stderr：{proc.stderr.strip()[:STDERR_LIMIT]}"
    return out


@tool
def load_skill(name: str) -> str:
    """載入指定 skill 的完整操作說明（SKILL.md）。name 為 system prompt 中列出的 skill 名稱。"""
    return load_skill_text(name)


@tool
def run_skill_script(skill: str, script: str, input_json: str) -> str:
    """執行 skill 的 scripts/ 內的 .py 腳本。input_json 為傳給腳本 stdin 的合法 JSON 字串；回傳腳本 stdout 的 JSON。"""
    return run_script(skill, script, input_json)
