from __future__ import annotations

import re
import shlex

# 只读放行的可执行名白名单：默认拒绝，未列出的一律视为写操作被拦截。
# 覆盖 文件/目录查看、查找定位、文本处理(输出 stdout)、摘要编码、系统信息，git 见下。
READONLY_ALLOWED_PREFIXES: frozenset[str] = frozenset({
    "ls", "dir", "cat", "head", "tail", "wc", "stat", "file", "tree", "pwd",
    "readlink", "realpath", "basename", "dirname", "du", "df", "grep", "egrep",
    "fgrep", "findstr", "rg", "ag", "ack", "find", "locate", "which", "whereis",
    "type", "echo", "printf", "diff", "comm", "cmp", "sort", "uniq", "cut", "tr",
    "column", "fold", "nl", "tac", "rev", "paste", "join", "expand", "unexpand",
    "awk", "gawk", "mawk", "nawk", "sed", "jq", "md5sum", "sha1sum", "sha256sum",
    "sha512sum", "cksum", "base64", "od", "hexdump", "xxd", "strings", "date",
    "printenv", "whoami", "id", "hostname", "uname", "uptime", "ps", "pgrep",
    "free", "arch", "git",
})

# git 只读子命令白名单（写盘/改工作区/改 .git 的子命令一律拒绝）。
READONLY_GIT_SUBCOMMANDS: frozenset[str] = frozenset({
    "status", "log", "diff", "show", "blame", "rev-parse", "branch", "tag",
    "describe", "ls-files", "ls-tree", "cat-file", "reflog", "shortlog", "grep",
    "name-rev", "symbolic-ref", "for-each-ref", "rev-list", "show-ref",
    "merge-base", "diff-tree", "diff-index", "whatchanged", "cherry",
    "count-objects", "version",
})

# 与 bash.py 一致的 wrapper：跳过后取真正的可执行名再校验。
_EXEC_WRAPPERS: frozenset[str] = frozenset({"env", "nice", "nohup", "setsid", "sudo", "time"})
_ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=.*$")
# 重定向写盘：保留既有的 > 与 >> 拦截。
_REDIRECT_PATTERNS: tuple[str, ...] = (r"(^|[^|])>(?![>&])", r">>")
_SEGMENT_SPLIT = re.compile(r"\|\||&&|[;\n|&]")
_FIND_WRITE_ACTIONS: frozenset[str] = frozenset(
    {"-delete", "-exec", "-execdir", "-ok", "-okdir", "-fls", "-fprint", "-fprintf", "-fprint0"}
)


def _normalize_token(token: str) -> str:
    stripped = token.strip().strip("\"'")
    return stripped.rsplit("/", maxsplit=1)[-1].rsplit("\\", maxsplit=1)[-1].lower()


def _shlex_tokens(segment: str) -> list[str]:
    text = segment.strip()
    if not text:
        return []
    try:
        return shlex.split(text, posix=True)
    except ValueError:
        return text.split()


def split_all_segments(command: str) -> list[str]:
    """按 ; \\n & 与 | || && 全量切分为独立命令段（空段丢弃）。"""
    return [segment for segment in _SEGMENT_SPLIT.split(command) if segment.strip()]


def _exec_tokens(tokens: list[str]) -> list[str]:
    """跳过 env/nohup/sudo 等 wrapper，返回真正可执行名起的 token 列表。"""
    index = 0
    while index < len(tokens):
        current = _normalize_token(tokens[index])
        if current in _EXEC_WRAPPERS:
            index += 1
            if current == "env":
                while index < len(tokens) and _ENV_ASSIGNMENT.match(tokens[index]):
                    index += 1
            continue
        return tokens[index:]
    return []


def _skip_balanced(text: str, open_index: int) -> int:
    """text[open_index] == '('，返回配对 ')' 之后的下标。"""
    depth = 0
    position = open_index
    while position < len(text):
        if text[position] == "(":
            depth += 1
        elif text[position] == ")":
            depth -= 1
            if depth == 0:
                return position + 1
        position += 1
    return len(text)


def _command_substitutions(text: str) -> list[str]:
    """抽取 $(...) 与反引号内层命令；$((...)) 算术展开忽略。"""
    subs: list[str] = []
    index = 0
    while index < len(text):
        if text[index] == "$" and index + 1 < len(text) and text[index + 1] == "(":
            if index + 2 < len(text) and text[index + 2] == "(":
                index = _skip_balanced(text, index + 2)
                continue
            end = _skip_balanced(text, index + 1)
            subs.append(text[index + 2 : end - 1])
            index = end
            continue
        index += 1
    parts = text.split("`")
    for inner in range(1, len(parts), 2):
        subs.append(parts[inner])
    return subs


def _git_subcommand(exec_tokens: list[str]) -> str:
    index = 1
    while index < len(exec_tokens):
        raw = exec_tokens[index].strip().strip("\"'")
        lowered = raw.lower()
        if lowered == "-c":  # -c / -C 携带一个取值参数
            index += 2
            continue
        if raw.startswith("-"):
            index += 1
            continue
        return lowered
    return ""


def _guard_find(exec_tokens: list[str]) -> bool:
    for token in exec_tokens[1:]:
        lowered = _normalize_token(token)
        if lowered in _FIND_WRITE_ACTIONS or lowered.startswith("-fprint"):
            return True
    return False


def _guard_sed(exec_tokens: list[str]) -> bool:
    for token in exec_tokens[1:]:
        cleaned = token.strip().strip("\"'")
        if cleaned == "-i" or cleaned.startswith("--in-place"):
            return True
        if cleaned.startswith("-") and not cleaned.startswith("--") and "i" in cleaned[1:]:
            return True
    return False


def _guard_sort(exec_tokens: list[str]) -> bool:
    for token in exec_tokens[1:]:
        cleaned = token.strip().strip("\"'")
        if cleaned.startswith("--output"):
            return True
        if cleaned.startswith("-") and not cleaned.startswith("--") and "o" in cleaned[1:]:
            return True
    return False


def _guard_awk(exec_tokens: list[str]) -> bool:
    return any("system(" in token for token in exec_tokens[1:])


_ARG_GUARDS = {
    "find": _guard_find,
    "sed": _guard_sed,
    "sort": _guard_sort,
    "awk": _guard_awk,
    "gawk": _guard_awk,
    "mawk": _guard_awk,
    "nawk": _guard_awk,
}


def _segment_blocked(segment: str) -> bool:
    exec_tokens = _exec_tokens(_shlex_tokens(segment))
    if not exec_tokens:
        return True
    name = _normalize_token(exec_tokens[0])
    if name not in READONLY_ALLOWED_PREFIXES:
        return True
    if name == "git":
        return _git_subcommand(exec_tokens) not in READONLY_GIT_SUBCOMMANDS
    guard = _ARG_GUARDS.get(name)
    return guard(exec_tokens) if guard else False


def is_readonly_blocked(command: str) -> bool:
    """只读模式下命令是否触碰写操作（白名单外一律拦截）。"""
    normalized = command.strip()
    if not normalized:
        return True
    if any(re.search(pattern, normalized) for pattern in _REDIRECT_PATTERNS):
        return True
    if any(is_readonly_blocked(sub) for sub in _command_substitutions(normalized)):
        return True
    return any(_segment_blocked(segment) for segment in split_all_segments(normalized))


__all__ = [
    "READONLY_ALLOWED_PREFIXES",
    "READONLY_GIT_SUBCOMMANDS",
    "is_readonly_blocked",
    "split_all_segments",
]
