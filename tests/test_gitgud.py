from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import sys
import types
from types import SimpleNamespace

import httpx


def _load_gitgud_module():
    path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "nonebot_plugin_eratw_mirror"
        / "gitgud.py"
    )
    spec = importlib.util.spec_from_file_location(
        "nonebot_plugin_eratw_mirror.gitgud",
        path,
    )
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    package = types.ModuleType("nonebot_plugin_eratw_mirror")
    package.__path__ = [str(path.parent)]
    package.__spec__ = importlib.util.spec_from_loader(
        "nonebot_plugin_eratw_mirror",
        loader=None,
        is_package=True,
    )
    config_module = types.ModuleType("nonebot_plugin_eratw_mirror.config")
    config_module.Config = object
    nonebot_module = types.ModuleType("nonebot")
    nonebot_module.logger = SimpleNamespace(
        debug=lambda *args, **kwargs: None,
        info=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: None,
    )
    sys.modules["nonebot_plugin_eratw_mirror"] = package
    sys.modules["nonebot_plugin_eratw_mirror.config"] = config_module
    sys.modules["nonebot"] = nonebot_module
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _config():
    return SimpleNamespace(
        eratw_api_base="https://gitgud.io/api/v4",
        eratw_project_id=28180,
        eratw_branch="feature/test",
        eratw_proxy=None,
        eratw_request_timeout=60,
    )


def test_branch_name_is_url_encoded():
    gitgud = _load_gitgud_module()
    seen_paths: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.raw_path)
        return httpx.Response(
            200,
            json={
                "commit": {
                    "id": "abcdef123456",
                    "short_id": "abcdef12",
                    "title": "head",
                },
            },
        )

    async def run():
        client = gitgud.GitGudClient(_config())
        client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            await client.get_branch_head()
        finally:
            await client._client.aclose()

    asyncio.run(run())

    assert seen_paths == [b"/api/v4/projects/28180/repository/branches/feature%2Ftest"]


def test_commit_diffs_fetches_all_pages():
    gitgud = _load_gitgud_module()
    seen_pages: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = request.url.params.get("page")
        seen_pages.append(page)
        if page == "1":
            return httpx.Response(
                200,
                headers={"X-Next-Page": "2"},
                json=[{"new_path": "a", "diff": "+one"}],
            )
        return httpx.Response(
            200,
            json=[{"new_path": "b", "diff": "+two"}],
        )

    async def run():
        client = gitgud.GitGudClient(_config())
        client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await client.get_commit_diffs("abc123")
        finally:
            await client._client.aclose()

    diffs = asyncio.run(run())

    assert seen_pages == ["1", "2"]
    assert [item["diff"] for item in diffs] == ["+one", "+two"]


def test_compare_fetches_all_pages_and_deduplicates_commits():
    gitgud = _load_gitgud_module()

    def handler(request: httpx.Request) -> httpx.Response:
        page = request.url.params.get("page")
        if page == "1":
            return httpx.Response(
                200,
                headers={"X-Next-Page": "2"},
                json={
                    "commits": [{"id": "a1", "short_id": "a1", "title": "one"}],
                    "diffs": [{"diff": "+one"}],
                },
            )
        return httpx.Response(
            200,
            json={
                "commits": [
                    {"id": "a1", "short_id": "a1", "title": "one"},
                    {"id": "b2", "short_id": "b2", "title": "two"},
                ],
                "diffs": [{"diff": "+two"}],
            },
        )

    async def run():
        client = gitgud.GitGudClient(_config())
        client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await client.compare("a", "b")
        finally:
            await client._client.aclose()

    commits, diffs = asyncio.run(run())

    assert [commit.id for commit in commits] == ["a1", "b2"]
    assert [item["diff"] for item in diffs] == ["+one", "+two"]
