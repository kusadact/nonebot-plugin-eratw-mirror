from __future__ import annotations

import os
from pathlib import Path
import stat

from dulwich.object_store import iter_tree_contents
from dulwich.repo import Repo


def is_valid_git_repo(repo_dir: Path) -> bool:
    try:
        repo = Repo(str(repo_dir))
    except Exception:
        return False
    repo.close()
    return True


def get_commit_tree_id(repo_dir: Path, sha: str) -> bytes:
    repo = Repo(str(repo_dir))
    try:
        commit = repo[sha.encode()]
        return commit.tree
    finally:
        repo.close()


def export_commit_tree(repo_dir: Path, destination: Path, sha: str) -> None:
    repo = Repo(str(repo_dir))
    try:
        commit = repo[sha.encode()]
        root = destination.resolve()
        for entry in iter_tree_contents(repo.object_store, commit.tree, include_trees=False):
            target = safe_git_path(root, entry.path)
            target.parent.mkdir(parents=True, exist_ok=True)
            obj = repo[entry.sha]
            if stat.S_ISLNK(entry.mode):
                os.symlink(os.fsdecode(obj.data), target)
                continue
            if not stat.S_ISREG(entry.mode):
                raise RuntimeError(f"Unsupported git entry mode {entry.mode:o}: {entry.path!r}")
            target.write_bytes(obj.data)
            if entry.mode & 0o111:
                target.chmod(0o755)
    finally:
        repo.close()


def safe_git_path(root: Path, raw_path: bytes) -> Path:
    parts = os.fsdecode(raw_path).split("/")
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise RuntimeError(f"Unsafe git path: {raw_path!r}")
    target = (root / Path(*parts)).resolve()
    target.relative_to(root)
    return target
