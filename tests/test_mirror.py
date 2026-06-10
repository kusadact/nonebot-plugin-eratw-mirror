from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import sys
import types
from types import SimpleNamespace


def _load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _load_mirror_module():
    package_dir = Path(__file__).resolve().parents[1] / "src" / "nonebot_plugin_eratw_mirror"
    package = types.ModuleType("nonebot_plugin_eratw_mirror")
    package.__path__ = [str(package_dir)]
    package.__spec__ = importlib.util.spec_from_loader(
        "nonebot_plugin_eratw_mirror",
        loader=None,
        is_package=True,
    )

    nonebot_module = types.ModuleType("nonebot")
    nonebot_module.logger = SimpleNamespace(
        debug=lambda *args, **kwargs: None,
        info=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: None,
    )
    config_module = types.ModuleType("nonebot_plugin_eratw_mirror.config")
    config_module.Config = object
    models = _load_module(
        "nonebot_plugin_eratw_mirror.models",
        package_dir / "models.py",
    )

    class FakeStateStore:
        instances: list["FakeStateStore"] = []

        def __init__(self) -> None:
            self.written_payloads: list[object] = []
            self.instances.append(self)

        def read_last_payload(self):
            raise AssertionError("test push must not reuse the cached payload")

        def write_last_payload(self, payload: object) -> None:
            self.written_payloads.append(payload)

    state_module = types.ModuleType("nonebot_plugin_eratw_mirror.state")
    state_module.StateStore = FakeStateStore

    archive_module = types.ModuleType("nonebot_plugin_eratw_mirror.archive")

    async def build_encrypted_archive(sha: str, short_sha: str, config: object):
        return models.ArchiveInfo(
            path=Path(f"{short_sha}.7z"),
            name=f"{short_sha}.7z",
            size=1024,
            sha256=f"sha256-{short_sha}",
            password="pass",
        )

    archive_module.build_encrypted_archive = build_encrypted_archive

    class FakeGitGudClient:
        instances: list["FakeGitGudClient"] = []

        def __init__(self, config: object) -> None:
            self.calls: list[str] = []
            self.instances.append(self)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def get_branch_head(self):
            self.calls.append("get_branch_head")
            return models.CommitInfo(
                id="newsha123456",
                short_id="newsha12",
                title="latest head",
                committed_date="2026-06-10T04:00:00+08:00",
                web_url="https://example.test/newsha123456",
            )

        async def get_commit(self, sha: str):
            self.calls.append(f"get_commit:{sha}")
            return models.CommitInfo(
                id=sha,
                short_id="newsha12",
                title="latest commit",
                committed_date="2026-06-10T04:00:00+08:00",
                web_url="https://example.test/newsha123456",
            )

        async def get_commit_diffs(self, sha: str):
            self.calls.append(f"get_commit_diffs:{sha}")
            return []

    gitgud_module = types.ModuleType("nonebot_plugin_eratw_mirror.gitgud")
    gitgud_module.GitGudClient = FakeGitGudClient

    sys.modules["nonebot_plugin_eratw_mirror"] = package
    sys.modules["nonebot"] = nonebot_module
    sys.modules["nonebot_plugin_eratw_mirror.config"] = config_module
    sys.modules["nonebot_plugin_eratw_mirror.state"] = state_module
    sys.modules["nonebot_plugin_eratw_mirror.archive"] = archive_module
    sys.modules["nonebot_plugin_eratw_mirror.gitgud"] = gitgud_module

    mirror = _load_module(
        "nonebot_plugin_eratw_mirror.mirror",
        package_dir / "mirror.py",
    )
    return mirror, FakeGitGudClient, FakeStateStore


def test_prepare_latest_payload_fetches_latest_even_when_payload_cache_exists():
    mirror, fake_client, fake_state = _load_mirror_module()
    service = mirror.MirrorService(SimpleNamespace())

    payload = asyncio.run(service.prepare_latest_payload())

    assert payload.target_sha == "newsha123456"
    assert payload.target_short_sha == "newsha12"
    assert fake_client.instances[0].calls == [
        "get_branch_head",
        "get_commit:newsha123456",
        "get_commit_diffs:newsha123456",
    ]
    assert fake_state.instances[0].written_payloads == [payload]
