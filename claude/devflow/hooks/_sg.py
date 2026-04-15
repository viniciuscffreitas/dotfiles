"""ast-grep integration primitives for devflow hooks.

Thin wrapper over the `sg` CLI. Responsibilities:
  - detect the `sg` binary (cached per process)
  - load YAML rules from global + project dirs, validate, merge
  - run rules against a file and parse findings
  - graceful degradation: missing binary / broken rule / sg crash -> []

Hooks call into this module; they must never see an exception from here.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

GLOBAL_RULES_DIR = Path.home() / ".claude" / "devflow" / "sg-rules"
PROJECT_RULES_SUBDIR = Path(".claude") / "sg-rules"

_binary_cache: Optional[object] = None  # None = not probed; False = probed-missing; str = probed-found
_rules_cache: dict[tuple[Optional[str], str], list["LoadedRule"]] = {}

_EXT_TO_LANGUAGE: dict[str, str] = {
    ".dart": "dart",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".js": "javascript",
    ".jsx": "jsx",
    ".py": "python",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".hpp": "cpp",
    ".c": "c",
    ".h": "c",
    ".rb": "ruby",
    ".kt": "kotlin",
    ".swift": "swift",
}


@dataclass
class LoadedRule:
    id: str
    language: str
    path: Path
    severity: str
    message: str


@dataclass
class SgFinding:
    rule_id: str
    file: Path
    line: int
    column: int
    message: str
    severity: str


# ---------------------------------------------------------------------------
# Binary detection
# ---------------------------------------------------------------------------

def detect_binary() -> Optional[str]:
    """Return path to `sg` binary, or None if missing. Cached per process."""
    global _binary_cache
    if _binary_cache is None:
        found = shutil.which("sg") or shutil.which("ast-grep")
        _binary_cache = found if found else False
    return _binary_cache if isinstance(_binary_cache, str) else None


# ---------------------------------------------------------------------------
# Rule loading
# ---------------------------------------------------------------------------

_TOP_LEVEL_FIELD_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*)\s*:\s*(.*)$")


def _extract_top_level_fields(text: str) -> Optional[dict[str, str]]:
    """Pull flat top-level `key: value` fields from a YAML file.

    Ignores nested mappings (indented lines) and sequence entries. Used to read
    rule metadata (id, language, severity, message) without a YAML dependency.
    Returns None if the file is clearly malformed (e.g. no valid top-level keys).
    """
    fields: dict[str, str] = {}
    saw_any_line = False
    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        saw_any_line = True
        if raw_line[0] in (" ", "\t", "-"):
            continue  # nested or sequence — skip
        m = _TOP_LEVEL_FIELD_RE.match(raw_line)
        if not m:
            return None  # top-level line that's not a key: value
        key, value = m.group(1), m.group(2).strip()
        # strip inline comments, surrounding quotes
        if value and value[0] not in ("'", '"'):
            hash_idx = value.find(" #")
            if hash_idx >= 0:
                value = value[:hash_idx].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        fields[key] = value
    if not saw_any_line:
        return None
    return fields


def _parse_rule_file(path: Path) -> Optional[LoadedRule]:
    try:
        text = path.read_text()
    except OSError as e:
        print(f"[devflow sg] skipping {path.name}: read error: {e}", file=sys.stderr)
        return None

    fields = _extract_top_level_fields(text)
    if fields is None:
        print(f"[devflow sg] skipping {path.name}: malformed yaml", file=sys.stderr)
        return None

    rule_id = fields.get("id")
    language = fields.get("language")
    if not rule_id or not language:
        print(f"[devflow sg] skipping {path.name}: missing id or language", file=sys.stderr)
        return None

    return LoadedRule(
        id=rule_id,
        language=language,
        path=path,
        severity=fields.get("severity") or "warning",
        message=fields.get("message") or rule_id,
    )


def _collect_dir(dir_: Path) -> list[LoadedRule]:
    if not dir_.is_dir():
        return []
    rules: list[LoadedRule] = []
    for path in sorted(dir_.glob("*.yml")):
        parsed = _parse_rule_file(path)
        if parsed:
            rules.append(parsed)
    for path in sorted(dir_.glob("*.yaml")):
        parsed = _parse_rule_file(path)
        if parsed:
            rules.append(parsed)
    return rules


def load_rules(project_root: Optional[Path]) -> list[LoadedRule]:
    """Load and merge global + project rules. Project overrides by `id`.

    Cached by (project_root, global_dir) key. Call `clear_rules_cache()` in tests.
    """
    cache_key = (str(project_root) if project_root else None, str(GLOBAL_RULES_DIR))
    if cache_key in _rules_cache:
        return _rules_cache[cache_key]

    by_id: dict[str, LoadedRule] = {}
    for rule in _collect_dir(GLOBAL_RULES_DIR):
        by_id[rule.id] = rule
    if project_root:
        for rule in _collect_dir(project_root / PROJECT_RULES_SUBDIR):
            by_id[rule.id] = rule  # project wins

    merged = list(by_id.values())
    _rules_cache[cache_key] = merged
    return merged


def clear_rules_cache() -> None:
    _rules_cache.clear()


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def _language_for(path: Path) -> Optional[str]:
    return _EXT_TO_LANGUAGE.get(path.suffix.lower())


def run_for_file(file_path: Path, rules: list[LoadedRule]) -> list[SgFinding]:
    """Run applicable rules against `file_path`. Returns empty list on any failure."""
    binary = detect_binary()
    if not binary or not rules:
        return []

    lang = _language_for(file_path)
    if not lang:
        return []

    applicable = [r for r in rules if r.language == lang]
    if not applicable:
        return []

    findings: list[SgFinding] = []
    for rule in applicable:
        findings.extend(_run_single_rule(binary, rule, file_path))
    return findings


def _run_single_rule(binary: str, rule: LoadedRule, file_path: Path) -> list[SgFinding]:
    try:
        result = subprocess.run(
            [binary, "scan", "--rule", str(rule.path), "--json=compact", str(file_path)],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as e:
        print(f"[devflow sg] {rule.id}: sg invocation failed: {e}", file=sys.stderr)
        return []

    if result.returncode not in (0, 1):  # sg uses exit code 1 when findings exist in some versions
        if result.stderr:
            print(f"[devflow sg] {rule.id}: {result.stderr.strip()[:200]}", file=sys.stderr)
        return []

    output = (result.stdout or "").strip()
    if not output:
        return []

    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        return []

    items = payload if isinstance(payload, list) else [payload]
    findings: list[SgFinding] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        rng = item.get("range") or {}
        start = rng.get("start") or {}
        line_0 = start.get("line")
        col_0 = start.get("column", 0)
        if not isinstance(line_0, int):
            continue
        findings.append(SgFinding(
            rule_id=rule.id,
            file=file_path,
            line=line_0 + 1,  # normalize 0-indexed to 1-indexed
            column=int(col_0) + 1,
            message=rule.message,
            severity=rule.severity,
        ))
    return findings
