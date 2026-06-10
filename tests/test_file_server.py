from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
from types import SimpleNamespace

import pytest


def _load_file_server_module(driver: object):
    path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "nonebot_plugin_eratw_mirror"
        / "file_server.py"
    )
    spec = importlib.util.spec_from_file_location(
        "nonebot_plugin_eratw_mirror.file_server",
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
    nonebot_module = types.ModuleType("nonebot")
    nonebot_module.get_driver = lambda: driver
    nonebot_module.logger = SimpleNamespace(
        info=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: None,
    )
    localstore_module = types.ModuleType("nonebot_plugin_localstore")
    localstore_module.get_plugin_data_dir = lambda: Path()
    sys.modules["nonebot_plugin_eratw_mirror"] = package
    sys.modules["nonebot"] = nonebot_module
    sys.modules["nonebot_plugin_localstore"] = localstore_module
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_configured_file_base_url_requires_http_route():
    file_server = _load_file_server_module(SimpleNamespace())
    config = SimpleNamespace(
        eratw_file_base_url="http://bot.example",
        eratw_file_route_prefix="/eratw/files",
    )

    with pytest.raises(RuntimeError, match="eratw_file_base_url is configured"):
        file_server.register_archive_file_route(config)


def test_missing_http_route_is_allowed_without_file_base_url():
    file_server = _load_file_server_module(SimpleNamespace())
    config = SimpleNamespace(
        eratw_file_base_url=None,
        eratw_file_route_prefix="/eratw/files",
    )

    assert file_server.register_archive_file_route(config) is False
