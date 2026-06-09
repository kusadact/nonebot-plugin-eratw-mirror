from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys

from dulwich import porcelain


def _load_archive_module():
    path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "nonebot_plugin_eratw_mirror"
        / "git_store.py"
    )
    spec = importlib.util.spec_from_file_location("eratw_git_store", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_export_commit_tree_writes_clean_worktree(tmp_path: Path):
    git_store = _load_archive_module()
    repo_dir = tmp_path / "repo"
    repo = porcelain.init(str(repo_dir))
    source_file = repo_dir / "dir" / "run.sh"
    source_file.parent.mkdir()
    source_file.write_text("#!/bin/sh\necho ok\n", encoding="utf-8")
    source_file.chmod(0o755)
    porcelain.add(str(repo_dir), paths=[str(source_file)])
    commit_id = porcelain.commit(
        str(repo_dir),
        message=b"init",
        author=b"tester <tester@example.com>",
        committer=b"tester <tester@example.com>",
    )
    repo.close()

    destination = tmp_path / "export"
    destination.mkdir()
    git_store.export_commit_tree(repo_dir, destination, commit_id.decode())

    exported = destination / "dir" / "run.sh"
    assert exported.read_text(encoding="utf-8") == "#!/bin/sh\necho ok\n"
    assert os.access(exported, os.X_OK)
    assert not (destination / ".git").exists()
