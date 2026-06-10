from __future__ import annotations

from pathlib import Path

import httpx
from nonebot import logger

from .config import Config
from .models import ArchiveInfo


async def build_remote_archive(
    sha: str,
    short_sha: str,
    config: Config,
) -> ArchiveInfo:
    base_url = str(config.eratw_worker_base_url or "").strip().rstrip("/")
    if not base_url:
        raise RuntimeError("eratw_worker_base_url is required in worker mode")

    payload = {
        "sha": sha,
        "short_sha": short_sha,
        "git_url": _git_url(config),
        "branch": config.eratw_branch,
        "archive_password": config.eratw_archive_password,
        "git_depth": 1,
        "proxy": _worker_proxy(config),
    }
    headers = _worker_headers(config)
    logger.info(f"eraTW requesting archive worker for {short_sha}: {base_url}")
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(config.eratw_timeout),
        follow_redirects=True,
    ) as client:
        response = await client.post(f"{base_url}/build", json=payload, headers=headers)
    if response.status_code >= 400:
        raise RuntimeError(
            f"eraTW archive worker failed with HTTP {response.status_code}: {response.text[:500]}"
        )
    data = response.json()
    archive = ArchiveInfo(
        path=Path(str(data.get("path") or data["name"])),
        name=str(data["name"]),
        size=int(data["size"]),
        sha256=str(data["sha256"]),
        password=str(data.get("password") or config.eratw_archive_password),
        download_url=str(data["download_url"]),
    )
    logger.info(
        f"eraTW worker archive ready {archive.name}: "
        f"{archive.size / 1024 / 1024:.2f} MiB, sha256={archive.sha256}"
    )
    return archive


def _worker_headers(config: Config) -> dict[str, str]:
    token = str(config.eratw_worker_token or "").strip()
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}", "X-EraTW-Token": token}


def _git_url(config: Config) -> str:
    value = config.eratw_git_url.strip() if config.eratw_git_url else ""
    if value:
        return value
    return f"{config.eratw_project_url.rstrip('/')}.git"


def _worker_proxy(config: Config) -> str | None:
    return _clean_optional_text(config.eratw_worker_proxy)


def _clean_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None
