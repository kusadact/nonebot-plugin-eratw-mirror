from __future__ import annotations

import asyncio
import hashlib
import shutil
import zipfile
from pathlib import Path

from nonebot import logger
from nonebot_plugin_localstore import get_plugin_cache_dir

from .config import Config
from .gitgud import GitGudClient
from .models import ArchiveInfo


async def build_encrypted_archive(
    client: GitGudClient,
    sha: str,
    short_sha: str,
    config: Config,
) -> ArchiveInfo:
    cache_dir = get_plugin_cache_dir()
    downloads_dir = cache_dir / "downloads"
    work_dir = cache_dir / "work" / sha
    output_dir = cache_dir / "archives"

    zip_path = downloads_dir / f"eratw-sub-modding-{short_sha}.zip"
    archive_path = output_dir / f"eratw-sub-modding-{short_sha}.7z"

    if archive_path.exists() and archive_path.stat().st_size > 0:
        logger.info(f"eraTW archive cache hit: {archive_path}")
        return _archive_info(archive_path, config.eratw_archive_password)

    output_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"eraTW downloading source archive for {short_sha} to {zip_path}")
    await client.download_archive(sha, zip_path)
    logger.info(
        f"eraTW downloaded source archive for {short_sha}: "
        f"{zip_path.stat().st_size / 1024 / 1024:.2f} MiB"
    )

    if work_dir.exists():
        logger.debug(f"eraTW removing previous work directory: {work_dir}")
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"eraTW extracting source archive for {short_sha} to {work_dir}")
    _safe_extract_zip(zip_path, work_dir)

    source = _single_child_or_self(work_dir)
    if archive_path.exists():
        archive_path.unlink()
    logger.info(f"eraTW building encrypted 7z archive for {short_sha}: {archive_path}")
    await _run_7z(source, archive_path, config)
    archive_info = _archive_info(archive_path, config.eratw_archive_password)
    logger.info(
        f"eraTW built archive {archive_info.name}: "
        f"{archive_info.size / 1024 / 1024:.2f} MiB, sha256={archive_info.sha256}"
    )
    return archive_info


def _safe_extract_zip(zip_path: Path, destination: Path) -> None:
    destination_root = destination.resolve()
    with zipfile.ZipFile(zip_path) as zip_file:
        logger.debug(f"eraTW zip contains {len(zip_file.infolist())} entries")
        for member in zip_file.infolist():
            target = (destination / member.filename).resolve()
            target.relative_to(destination_root)
        zip_file.extractall(destination)


def _single_child_or_self(path: Path) -> Path:
    children = [child for child in path.iterdir()]
    if len(children) == 1:
        logger.debug(f"eraTW archive source root resolved to single child: {children[0]}")
        return children[0]
    logger.debug(f"eraTW archive source root uses work directory with {len(children)} children: {path}")
    return path


async def _run_7z(source: Path, output: Path, config: Config) -> None:
    seven_zip = _find_7z(config.eratw_7z_path)
    logger.debug(f"eraTW using 7z executable: {seven_zip}")
    command = [
        seven_zip,
        "a",
        "-t7z",
        "-mx=0",
        "-mhe=on",
        f"-p{config.eratw_archive_password}",
        str(output),
        source.name,
    ]
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=str(source.parent),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await process.communicate()
    if process.returncode != 0:
        output_text = stdout.decode("utf-8", errors="replace") if stdout else ""
        logger.error(f"eraTW 7z failed for {output}: {output_text}")
        raise RuntimeError(f"7z failed with exit code {process.returncode}: {output_text}")
    if not output.exists() or output.stat().st_size <= 0:
        raise RuntimeError(f"7z did not create archive: {output}")
    if stdout:
        logger.debug(stdout.decode("utf-8", errors="replace").strip())


def _find_7z(configured_path: str | None) -> str:
    if configured_path and configured_path.strip():
        return configured_path.strip()
    for candidate in ("7zz", "7z", "7za"):
        found = shutil.which(candidate)
        if found:
            return found
    raise RuntimeError("7z executable not found. Set eratw_7z_path or install 7zz/7z/7za.")


def _archive_info(path: Path, password: str) -> ArchiveInfo:
    return ArchiveInfo(
        path=path,
        name=path.name,
        size=path.stat().st_size,
        sha256=_sha256(path),
        password=password,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
