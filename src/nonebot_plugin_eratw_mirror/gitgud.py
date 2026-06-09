from __future__ import annotations

import inspect
from typing import Any
from urllib.parse import quote

import httpx
from nonebot import logger

from .config import Config
from .models import CommitInfo

PAGE_SIZE = 100
MAX_PAGES = 1000


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
            f"/projects/{self.config.eratw_project_id}/repository/branches/{_path_token(self.config.eratw_branch)}"
        )
        commit = CommitInfo.from_api(data["commit"])
        logger.info(f"eraTW branch {self.config.eratw_branch} head: {commit.short_id} {commit.title}")
        return commit

    async def get_commit(self, sha: str) -> CommitInfo:
        logger.debug(f"eraTW fetching commit: {sha}")
        data = await self._get_json(
            f"/projects/{self.config.eratw_project_id}/repository/commits/{_path_token(sha)}"
        )
        commit = CommitInfo.from_api(data)
        logger.info(f"eraTW fetched commit {commit.short_id}: {commit.title}")
        return commit

    async def compare(self, from_sha: str, to_sha: str) -> tuple[list[CommitInfo], list[dict[str, Any]]]:
        logger.info(f"eraTW comparing commits: {from_sha[:8]} -> {to_sha[:8]}")
        pages = await self._get_json_pages(
            f"/projects/{self.config.eratw_project_id}/repository/compare",
            params={"from": from_sha, "to": to_sha, "straight": "true"},
        )
        commits: list[CommitInfo] = []
        diffs: list[dict[str, Any]] = []
        compare_timeout = False
        for data in pages:
            if not isinstance(data, dict):
                raise RuntimeError("GitLab compare API returned an unexpected payload")
            commits.extend(CommitInfo.from_api(item) for item in data.get("commits", []))
            diffs.extend(list(data.get("diffs", [])))
            compare_timeout = compare_timeout or bool(data.get("compare_timeout"))
        commits = _deduplicate_commits(commits)
        if compare_timeout:
            logger.warning(
                "eraTW compare API reported incomplete diffs; fetching per-commit diffs instead"
            )
            diffs = []
            for commit in commits:
                diffs.extend(await self.get_commit_diffs(commit.id))
        logger.info(
            f"eraTW compare result: {len(commits)} commits, "
            f"{len(diffs)} diffs"
        )
        return commits, diffs

    async def get_commit_diffs(self, sha: str) -> list[dict[str, Any]]:
        logger.debug(f"eraTW fetching commit diffs: {sha}")
        pages = await self._get_json_pages(
            f"/projects/{self.config.eratw_project_id}/repository/commits/{_path_token(sha)}/diff",
        )
        data: list[dict[str, Any]] = []
        for page in pages:
            if not isinstance(page, list):
                raise RuntimeError("GitLab commit diff API returned an unexpected payload")
            data.extend(page)
        logger.info(f"eraTW fetched {len(data)} diffs for commit {sha[:8]}")
        return data

    async def _get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        response = await self._require_client().get(self._url(path), params=params)
        response.raise_for_status()
        return response.json()

    async def _get_json_pages(self, path: str, params: dict[str, Any] | None = None) -> list[Any]:
        pages: list[Any] = []
        url = self._url(path)
        request_params: dict[str, Any] | None = dict(params or {})
        request_params.setdefault("per_page", PAGE_SIZE)
        request_params.setdefault("page", 1)
        for _ in range(MAX_PAGES):
            response = await self._require_client().get(url, params=request_params)
            response.raise_for_status()
            pages.append(response.json())
            next_page = response.headers.get("X-Next-Page", "").strip()
            if next_page:
                request_params = dict(params or {})
                request_params.setdefault("per_page", PAGE_SIZE)
                request_params["page"] = next_page
                continue
            next_url = response.links.get("next", {}).get("url")
            if next_url:
                url = str(next_url)
                request_params = None
                continue
            return pages
        raise RuntimeError(f"GitLab API pagination exceeded {MAX_PAGES} pages: {path}")

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


def _path_token(value: str) -> str:
    return quote(value, safe="")


def _deduplicate_commits(commits: list[CommitInfo]) -> list[CommitInfo]:
    seen: set[str] = set()
    result: list[CommitInfo] = []
    for commit in commits:
        if commit.id in seen:
            continue
        seen.add(commit.id)
        result.append(commit)
    return result
