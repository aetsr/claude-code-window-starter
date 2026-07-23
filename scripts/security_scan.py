#!/usr/bin/env python3
from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {".py", ".swift", ".sh", ".json", ".toml", ".yml", ".yaml", ".md", ".plist"}
SECRET_PATTERNS = {
    "Anthropic key": re.compile(r"sk-ant-[A-Za-z0-9_-]{16,}"),
    "Telegram token": re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{25,}\b"),
    "Private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
}
IGNORED_PARTS = {".git", ".build", "__pycache__", ".venv"}


def files() -> list[Path]:
    process = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
        shell=False,
    )
    candidates = (
        [ROOT / line for line in process.stdout.splitlines()]
        if process.returncode == 0 and process.stdout.strip()
        else list(ROOT.rglob("*"))
    )
    return [
        path
        for path in candidates
        if path.is_file() and path.suffix in TEXT_SUFFIXES and not IGNORED_PARTS.intersection(path.parts)
    ]


def main() -> int:
    findings: list[str] = []
    for path in files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        relative = path.relative_to(ROOT)
        for name, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                findings.append(f"{relative}: possible {name}")
        if path.suffix == ".py":
            try:
                tree = ast.parse(text, filename=str(relative))
            except SyntaxError as exc:
                findings.append(f"{relative}: syntax error: {exc}")
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    for keyword in node.keywords:
                        if keyword.arg == "shell" and isinstance(keyword.value, ast.Constant) and keyword.value.value is True:
                            findings.append(f"{relative}:{node.lineno}: shell=True is forbidden")
                if isinstance(node, ast.Attribute) and node.attr in {"system", "popen"}:
                    if isinstance(node.value, ast.Name) and node.value.id == "os":
                        findings.append(f"{relative}:{node.lineno}: os.{node.attr} is forbidden")
    if findings:
        print("\n".join(findings), file=sys.stderr)
        return 1
    print(f"Security scan passed for {len(files())} files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
