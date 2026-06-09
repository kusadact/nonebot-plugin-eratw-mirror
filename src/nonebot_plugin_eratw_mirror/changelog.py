from __future__ import annotations

TARGET_CHANGELOG_PATH = "魔改版更新记录文档/补丁&readme集/ADD_BANQUET_开发日志.md"


def extract_added_markdown_from_diff(diff_text: str) -> str:
    lines: list[str] = []
    for line in diff_text.splitlines():
        if not line.startswith("+") or line.startswith("+++"):
            continue
        lines.append(line[1:])
    return _strip_outer_blank_lines("\n".join(lines))


def extract_changelog_from_diffs(diffs: list[dict]) -> str:
    chunks: list[str] = []
    for item in diffs:
        new_path = item.get("new_path")
        old_path = item.get("old_path")
        if TARGET_CHANGELOG_PATH not in {new_path, old_path}:
            continue
        text = extract_added_markdown_from_diff(str(item.get("diff") or ""))
        if text:
            chunks.append(text)
    return _strip_outer_blank_lines("\n\n".join(chunks))


def _strip_outer_blank_lines(text: str) -> str:
    lines = text.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)

