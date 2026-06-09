from __future__ import annotations

import inspect
from typing import Any

import httpx
from nonebot import logger

from .config import Config
from .models import CommitInfo


class GitGudClient:
    def __init__(self, config: Config):
        self.config = config
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "GitGudClient":
        kwargs: dict[str, Any] = {
            "timeout": httpx.Timeout(self.config.eratw_request_timeout),
            "follow_redirects": True,
        }
        proxy = _normalize_proxy(self.config.eratw_proxy)
        if proxy:
            logger.info(f"eraTW GitGud client using proxy: {proxy}")
            if "proxy" in inspect.signature(httpx.AsyncClient).parameters:
                kwargs["proxy"] = proxy
            else:
                kwargs["proxies"] = proxy
        else:
            logger.debug("eraTW GitGud client using direct connection")
        self._client = httpx.AsyncClient(**kwargs)
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._client is not None:
            await self._client.aclose()
        self._client = None

    async def get_branch_head(self) -> CommitInfo:
        logger.debug(f"eraTW fetching branch head: {self.config.eratw_branch}")
        data = await self._get_json(
            f"/projects/{self.config.eratw_project_id}/repository/branches/{self.config.eratw_branch}"
        )
        commit = CommitInfo.from_api(data["commit"])
        logger.info(f"eraTW branch {self.config.eratw_branch} head: {commit.short_id} {commit.title}")
        return commit

    async def get_commit(self, sha: str) -> CommitInfo:
        logger.debug(f"eraTW fetching commit: {sha}")
        data = await self._get_json(
            f"/projects/{self.config.eratw_project_id}/repository/commits/{sha}"
        )
        commit = CommitInfo.from_api(data)
        logger.info(f"eraTW fetched commit {commit.short_id}: {commit.title}")
        return commit

    async def compare(self, from_sha: str, to_sha: str) -> tuple[list[CommitInfo], list[dict[str, Any]]]:
        logger.info(f"eraTW comparing commits: {from_sha[:8]} -> {to_sha[:8]}")
        data = await self._get_json(
            f"/projects/{self.config.eratw_project_id}/repository/compare",
            params={"from": from_sha, "to": to_sha, "straight": "true"},
        )
        commits = [CommitInfo.from_api(item) for item in data.get("commits", [])]
        logger.info(
            f"eraTW compare result: {len(commits)} commits, "
            f"{len(data.get('diffs', []))} diffs"
        )
        return commits, list(data.get("diffs", []))

    async def get_commit_diffs(self, sha: str) -> list[dict[str, Any]]:
        logger.debug(f"eraTW fetching commit diffs: {sha}")
        data = await self._get_json(
            f"/projects/{self.config.eratw_project_id}/repository/commits/{sha}/diff",
            params={"per_page": 100},
        )
        logger.info(f"eraTW fetched {len(data)} diffs for commit {sha[:8]}")
        return list(data)

    async def _get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        response = await self._require_client().get(self._url(path), params=params)
        response.raise_for_status()
        return response.json()

    def _url(self, path: str) -> str:
        return f"{self.config.eratw_api_base.rstrip('/')}{path}"

    def _require_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("GitGudClient must be used as an async context manager")
        return self._client


def _normalize_proxy(proxy: str | None) -> str | None:
    if proxy is None:
        return None
    proxy = proxy.strip()
    return proxy or None
