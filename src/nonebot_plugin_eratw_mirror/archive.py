from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Callable, TypeVar

from dulwich import porcelain
from nonebot import logger
from nonebot_plugin_localstore import get_plugin_cache_dir, get_plugin_data_dir
import py7zr

from .config import Config
from .git_store import export_commit_tree, get_commit_tree_id, is_valid_git_repo
from .models import ArchiveInfo

T = TypeVar("T")
GIT_FETCH_DEPTH = 1
ARCHIVE_CACHE_VERSION = 1


async def build_encrypted_archive(
    sha: str,
    short_sha: str,
    config: Config,
) -> ArchiveInfo:
    data_dir = get_plugin_data_dir()
    work_dir = get_plugin_cache_dir() / "work" / sha
    output_dir = data_dir / "archives"

    archive_path = output_dir / f"eratw-sub-modding-{short_sha}.7z"
    metadata_path = _archive_metadata_path(archive_path)

    cached_archive = _cached_archive_info(archive_path, metadata_path, sha, config)
    if cached_archive is not None:
        logger.info(f"eraTW archive cache hit: {archive_path}")
        return cached_archive

    output_dir.mkdir(parents=True, exist_ok=True)
    source = await _prepare_git_source(sha, short_sha, config, work_dir)
    tmp_archive = _archive_tmp_path(archive_path)
    if tmp_archive.exists():
        tmp_archive.unlink()
    logger.info(f"eraTW building encrypted 7z archive for {short_sha}: {archive_path}")
    try:
        await _run_7z(source, tmp_archive, config)
        tmp_archive_info = _archive_info(tmp_archive, config.eratw_archive_password)
        tmp_archive.replace(archive_path)
    finally:
        if tmp_archive.exists():
            tmp_archive.unlink()
    archive_info = ArchiveInfo(
        path=archive_path,
        name=archive_path.name,
        size=tmp_archive_info.size,
        sha256=tmp_archive_info.sha256,
        password=tmp_archive_info.password,
    )
    _write_archive_metadata(metadata_path, sha, config, archive_info)
    logger.info(
        f"eraTW built archive {archive_info.name}: "
        f"{archive_info.size / 1024 / 1024:.2f} MiB, sha256={archive_info.sha256}"
    )
    return archive_info


async def _prepare_git_source(
    sha: str,
    short_sha: str,
    config: Config,
    work_dir: Path,
) -> Path:
    repo_dir = get_plugin_data_dir() / "git" / "source.git"
    source = work_dir / f"eratw-sub-modding-{short_sha}"

    await _ensure_git_repo(repo_dir, config)
    await _fetch_git_branch(repo_dir, config)
    await _verify_git_commit(repo_dir, sha, config)

    if work_dir.exists():
        logger.debug(f"eraTW removing previous work directory: {work_dir}")
        shutil.rmtree(work_dir)
    source.mkdir(parents=True, exist_ok=True)
    logger.info(f"eraTW checking out source {short_sha} from git cache to {source}")
    await _checkout_git_worktree(repo_dir, source, sha, config)
    return source


async def _ensure_git_repo(repo_dir: Path, config: Config) -> None:
    git_url = _git_url(config)
    if repo_dir.exists() and not is_valid_git_repo(repo_dir):
        logger.warning(f"eraTW git cache is not a valid clone; rebuilding: {repo_dir}")
        shutil.rmtree(repo_dir)

    if not repo_dir.exists():
        repo_dir.parent.mkdir(parents=True, exist_ok=True)
        logger.info(f"eraTW cloning git repository to {repo_dir}: {git_url}")
        await _run_git_operation(
            f"clone {git_url}",
            config,
            _clone_git_repo,
            git_url,
            repo_dir,
            config,
        )
        return

    logger.debug(f"eraTW git cache hit: {repo_dir}")


def _clone_git_repo(git_url: str, repo_dir: Path, config: Config) -> None:
    repo = porcelain.clone(
        git_url,
        target=str(repo_dir),
        bare=True,
        checkout=False,
        depth=GIT_FETCH_DEPTH,
        branch=config.eratw_branch,
        errstream=_NullBinaryWriter(),
    )
    repo.close()


async def _fetch_git_branch(repo_dir: Path, config: Config) -> None:
    logger.info(
        f"eraTW fetching git branch {config.eratw_branch} "
        f"(depth={GIT_FETCH_DEPTH})"
    )
    await _run_git_operation(
        f"fetch {config.eratw_branch}",
        config,
        _fetch_git_repo,
        repo_dir,
        config,
    )


def _fetch_git_repo(repo_dir: Path, config: Config) -> None:
    repo = None
    try:
        from dulwich.repo import Repo

        repo = Repo(str(repo_dir))
        porcelain.fetch(
            repo,
            remote_location=_git_url(config),
            depth=GIT_FETCH_DEPTH,
            prune=True,
            force=True,
            quiet=True,
            errstream=_NullBinaryWriter(),
        )
    finally:
        if repo is not None:
            repo.close()


async def _verify_git_commit(repo_dir: Path, sha: str, config: Config) -> None:
    await _run_git_operation(
        f"verify commit {sha[:8]}",
        config,
        get_commit_tree_id,
        repo_dir,
        sha,
    )


async def _checkout_git_worktree(
    repo_dir: Path,
    source: Path,
    sha: str,
    config: Config,
) -> None:
    await _run_git_operation(
        f"export commit {sha[:8]}",
        config,
        export_commit_tree,
        repo_dir,
        source,
        sha,
    )


async def _run_7z(source: Path, output: Path, config: Config) -> None:
    logger.debug("eraTW using py7zr archive writer")
    await asyncio.to_thread(_write_py7zr_archive, source, output, config)
    if not output.exists() or output.stat().st_size <= 0:
        raise RuntimeError(f"py7zr did not create archive: {output}")


def _write_py7zr_archive(source: Path, output: Path, config: Config) -> None:
    filters = [{"id": py7zr.FILTER_COPY}]
    with py7zr.SevenZipFile(
        output,
        "w",
        filters=filters,
        password=config.eratw_archive_password,
        header_encryption=True,
        dereference=False,
    ) as archive:
        archive.writeall(source, arcname=source.name)


async def _run_git_operation(
    label: str,
    config: Config,
    func: Callable[..., T],
    *args: object,
    **kwargs: object,
) -> T:
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_run_with_git_env, config, func, *args, **kwargs),
            timeout=config.eratw_timeout,
        )
    except asyncio.TimeoutError:
        raise RuntimeError(
            f"Git operation timed out after {config.eratw_timeout} seconds: {label}"
        ) from None


def _run_with_git_env(
    config: Config,
    func: Callable[..., T],
    *args: object,
    **kwargs: object,
) -> T:
    previous = _apply_git_env(config)
    try:
        return func(*args, **kwargs)
    finally:
        _restore_env(previous)


def _git_url(config: Config) -> str:
    if config.eratw_git_url and config.eratw_git_url.strip():
        return config.eratw_git_url.strip()
    return f"{config.eratw_project_url.rstrip('/')}.git"


def _apply_git_env(config: Config) -> dict[str, str | None]:
    updates = {"GIT_TERMINAL_PROMPT": "0"}
    proxy = config.eratw_proxy.strip() if config.eratw_proxy else ""
    if proxy:
        updates.update(
            {
                "http_proxy": proxy,
                "https_proxy": proxy,
                "all_proxy": proxy,
                "HTTP_PROXY": proxy,
                "HTTPS_PROXY": proxy,
                "ALL_PROXY": proxy,
            }
        )
    previous = {key: os.environ.get(key) for key in updates}
    os.environ.update(updates)
    return previous


def _restore_env(previous: dict[str, str | None]) -> None:
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


class _NullBinaryWriter:
    def write(self, data: bytes) -> int:
        return len(data)

    def flush(self) -> None:
        return None


def _archive_info(path: Path, password: str) -> ArchiveInfo:
    return ArchiveInfo(
        path=path,
        name=path.name,
        size=path.stat().st_size,
        sha256=_sha256(path),
        password=password,
    )


def _cached_archive_info(
    archive_path: Path,
    metadata_path: Path,
    sha: str,
    config: Config,
) -> ArchiveInfo | None:
    if not archive_path.exists() or archive_path.stat().st_size <= 0:
        return None
    metadata = _read_archive_metadata(metadata_path)
    if metadata is None:
        logger.info(f"eraTW archive cache metadata missing; rebuilding: {archive_path}")
        return None
    expected = _archive_cache_key(sha, config)
    for key, value in expected.items():
        if metadata.get(key) != value:
            logger.info(f"eraTW archive cache metadata mismatch on {key}; rebuilding: {archive_path}")
            return None
    archive_info = _archive_info(archive_path, config.eratw_archive_password)
    if int(metadata.get("archive_size") or -1) != archive_info.size:
        logger.info(f"eraTW archive cache size mismatch; rebuilding: {archive_path}")
        return None
    if str(metadata.get("archive_sha256") or "") != archive_info.sha256:
        logger.info(f"eraTW archive cache sha256 mismatch; rebuilding: {archive_path}")
        return None
    return archive_info


def _archive_cache_key(sha: str, config: Config) -> dict[str, object]:
    return {
        "version": ARCHIVE_CACHE_VERSION,
        "commit_sha": sha,
        "git_url": _git_url(config),
        "branch": config.eratw_branch,
        "password_sha256": _text_sha256(config.eratw_archive_password),
    }


def _read_archive_metadata(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning(f"eraTW archive cache metadata is unreadable; rebuilding: {path}: {exc}")
        return None
    if not isinstance(data, dict):
        logger.warning(f"eraTW archive cache metadata is invalid; rebuilding: {path}")
        return None
    return data


def _write_archive_metadata(path: Path, sha: str, config: Config, archive_info: ArchiveInfo) -> None:
    data = {
        **_archive_cache_key(sha, config),
        "archive_name": archive_info.name,
        "archive_size": archive_info.size,
        "archive_sha256": archive_info.sha256,
    }
    tmp_path = path.with_suffix(f"{path.suffix}.tmp")
    tmp_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp_path.replace(path)


def _archive_metadata_path(path: Path) -> Path:
    return path.with_suffix(f"{path.suffix}.json")


def _archive_tmp_path(path: Path) -> Path:
    return path.with_suffix(f"{path.suffix}.tmp")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
