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
