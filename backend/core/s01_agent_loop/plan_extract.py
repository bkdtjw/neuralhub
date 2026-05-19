from __future__ import annotations

import json
import re
import shlex
from typing import Any

OUTPUT_SUMMARY_LIMIT = 4000
SUMMARY_DISPLAY_LIMIT = 200
KEY_FINDING_LIMIT = 200
MAX_KEY_FINDINGS = 5
_PATH_COMMANDS = {"cat", "head", "tail", "less", "more", "nl"}
_JSON_BLOCK_RE = re.compile(r"```json\s*(.*?)```", re.IGNORECASE | re.DOTALL)


def _extract_output_summary(messages: list[object]) -> str:
    for message in reversed(messages):
        if getattr(message, "role", "") == "assistant":
            content = str(getattr(message, "content", "")).strip()
            if content:
                return content[:OUTPUT_SUMMARY_LIMIT]
    return ""


def _extract_files_touched(messages: list[object]) -> list[str]:
    files: set[str] = set()
    for message in messages:
        for call in getattr(message, "tool_calls", None) or []:
            arguments = getattr(call, "arguments", {}) or {}
            _collect_path_values(arguments, files)
            command = arguments.get("command")
            if isinstance(command, str):
                files.update(_extract_paths_from_command(command))
        for result in getattr(message, "tool_results", None) or []:
            for diff in getattr(result, "diffs", []) or []:
                path = getattr(diff, "path", "")
                if path:
                    files.add(str(path))
    return sorted(files)


def _extract_key_findings(messages: list[object]) -> list[str]:
    findings: list[str] = []
    for message in messages:
        for result in getattr(message, "tool_results", None) or []:
            if getattr(result, "is_error", False):
                continue
            first_line = _first_nonempty_line(str(getattr(result, "output", "")))
            if first_line:
                findings.append(first_line[:KEY_FINDING_LIMIT])
            if len(findings) >= MAX_KEY_FINDINGS:
                return findings
    return findings


def _extract_key_data(messages: list[object]) -> dict[str, Any]:
    data = _key_data_from_last_assistant(messages)
    if data:
        return data
    return _key_data_from_last_tool_results(messages)


def _key_data_from_last_assistant(messages: list[object]) -> dict[str, Any]:
    for message in reversed(messages):
        if getattr(message, "role", "") != "assistant":
            continue
        content = str(getattr(message, "content", ""))
        for match in _JSON_BLOCK_RE.finditer(content):
            data = _json_dict(match.group(1))
            if data is not None:
                return data
        return {}
    return {}


def _key_data_from_last_tool_results(messages: list[object]) -> dict[str, Any]:
    for message in reversed(messages):
        results = getattr(message, "tool_results", None) or []
        if not results:
            continue
        for result in results:
            data = _json_dict(str(getattr(result, "output", "")))
            if data is not None:
                return data
        return {}
    return {}


def _json_dict(raw: str) -> dict[str, Any] | None:
    try:
        value = json.loads(raw.strip())
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _collect_path_values(value: object, files: set[str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "path" and isinstance(item, str) and item.strip():
                files.add(item.strip())
            else:
                _collect_path_values(item, files)
    elif isinstance(value, list):
        for item in value:
            _collect_path_values(item, files)


def _extract_paths_from_command(command: str) -> list[str]:
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()
    paths: list[str] = []
    for index, token in enumerate(tokens):
        if token not in _PATH_COMMANDS:
            continue
        paths.extend(_command_paths_after(tokens[index + 1 :]))
    return paths


def _command_paths_after(tokens: list[str]) -> list[str]:
    paths: list[str] = []
    for token in tokens:
        if token in {"|", "&&", ";"}:
            break
        if token.startswith("-"):
            continue
        paths.append(token)
        if len(paths) >= 2:
            break
    return paths


def _first_nonempty_line(text: str) -> str:
    return next((line.strip() for line in text.splitlines() if line.strip()), "")


__all__ = [
    "KEY_FINDING_LIMIT",
    "MAX_KEY_FINDINGS",
    "OUTPUT_SUMMARY_LIMIT",
    "SUMMARY_DISPLAY_LIMIT",
    "_extract_files_touched",
    "_extract_key_data",
    "_extract_key_findings",
    "_extract_output_summary",
]
