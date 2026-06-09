from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace


def _load_archive_module():
    path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "nonebot_plugin_eratw_mirror"
        / "archive.py"
    )
    spec = importlib.util.spec_from_file_location(
        "nonebot_plugin_eratw_mirror.archive",
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
    localstore_module = types.ModuleType("nonebot_plugin_localstore")
    localstore_module.get_plugin_cache_dir = lambda: Path()
    localstore_module.get_plugin_data_dir = lambda: Path()
    sys.modules["nonebot_plugin_eratw_mirror"] = package
    sys.modules["nonebot_plugin_eratw_mirror.config"] = config_module
    sys.modules["nonebot"] = nonebot_module
    sys.modules["nonebot_plugin_localstore"] = localstore_module
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _config(password: str = "eratoho"):
    return SimpleNamespace(
        eratw_archive_password=password,
        eratw_branch="main",
        eratw_git_url=None,
        eratw_project_url="https://gitgud.io/era-games-zh/touhou/eratw-sub-modding",
    )


def test_archive_cache_requires_metadata(tmp_path: Path):
    archive = _load_archive_module()
    archive_path = tmp_path / "sample.7z"
    metadata_path = tmp_path / "sample.7z.json"
    archive_path.write_bytes(b"partial")

    assert archive._cached_archive_info(
        archive_path,
        metadata_path,
        "abc123",
        _config(),
    ) is None


def test_archive_cache_rejects_password_change(tmp_path: Path):
    archive = _load_archive_module()
    archive_path = tmp_path / "sample.7z"
    metadata_path = tmp_path / "sample.7z.json"
    archive_path.write_bytes(b"archive bytes")
    info = archive._archive_info(archive_path, "old-pass")
    archive._write_archive_metadata(metadata_path, "abc123", _config("old-pass"), info)

    assert archive._cached_archive_info(
        archive_path,
        metadata_path,
        "abc123",
        _config("new-pass"),
    ) is None


def test_archive_cache_accepts_matching_metadata(tmp_path: Path):
    archive = _load_archive_module()
    archive_path = tmp_path / "sample.7z"
    metadata_path = tmp_path / "sample.7z.json"
    archive_path.write_bytes(b"archive bytes")
    config = _config("same-pass")
    info = archive._archive_info(archive_path, config.eratw_archive_password)
    archive._write_archive_metadata(metadata_path, "abc123", config, info)

    cached = archive._cached_archive_info(archive_path, metadata_path, "abc123", config)

    assert cached is not None
    assert cached.password == "same-pass"
    assert cached.sha256 == info.sha256
