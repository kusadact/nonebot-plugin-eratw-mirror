from __future__ import annotations

TARGET_CHANGELOG_PATH = "魔改版更新记录文档/补丁&readme集/ADD_BANQUET_开发日志.md"


def extract_added_markdown_from_diff(diff_text: str) -> str:
    chunks: list[str] = []
    hunk_lines: list[tuple[str, str]] = []
    has_addition = False
    has_removal = False

    def flush_hunk() -> None:
        nonlocal has_addition, has_removal
        if not has_addition:
            hunk_lines.clear()
            has_removal = False
            return
        selected = [
            text
            for kind, text in hunk_lines
            if kind == "added" or (has_removal and kind == "context")
        ]
        text = _strip_outer_blank_lines("\n".join(selected))
        if text:
            chunks.append(text)
        hunk_lines.clear()
        has_addition = False
        has_removal = False

    for line in diff_text.splitlines():
        if line.startswith("@@"):
            flush_hunk()
            continue
        if line.startswith("+++") or line.startswith("---") or line.startswith("\\"):
            continue
        if line.startswith("+"):
            hunk_lines.append(("added", line[1:]))
            has_addition = True
            continue
        if line.startswith("-"):
            has_removal = True
            continue
        if line.startswith(" "):
            hunk_lines.append(("context", line[1:]))
            continue
        hunk_lines.append(("context", line))
    flush_hunk()
    return _strip_outer_blank_lines("\n\n".join(chunks))


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
