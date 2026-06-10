from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_changelog_module():
    path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "nonebot_plugin_eratw_mirror"
        / "changelog.py"
    )
    spec = importlib.util.spec_from_file_location("eratw_changelog", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_extract_added_markdown_ignores_headers():
    changelog = _load_changelog_module()
    diff = """@@ -1,2 +1,4 @@
 unchanged
+## v1
+
+- added
--- old
+++ new
"""
    assert changelog.extract_added_markdown_from_diff(diff) == "## v1\n\n- added"


def test_extract_modified_markdown_keeps_hunk_context():
    changelog = _load_changelog_module()
    diff = "\n".join(
        [
            "@@ -1,4 +1,5 @@",
            "+开头",
            " 旧段落标题",
            "-旧说明",
            "+新说明",
            " 结尾",
            "@@ -8,2 +9,3 @@",
            " another context",
            "+pure append",
        ]
    )

    assert (
        changelog.extract_added_markdown_from_diff(diff)
        == "开头\n旧段落标题\n新说明\n结尾\n\npure append"
    )
