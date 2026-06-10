from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
from types import SimpleNamespace


def _load_remote_worker_module():
    path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "nonebot_plugin_eratw_mirror"
        / "remote_worker.py"
    )
    spec = importlib.util.spec_from_file_location(
        "nonebot_plugin_eratw_mirror.remote_worker",
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
    models_module = types.ModuleType("nonebot_plugin_eratw_mirror.models")
    models_module.ArchiveInfo = object
    nonebot_module = types.ModuleType("nonebot")
    nonebot_module.logger = SimpleNamespace(info=lambda *args, **kwargs: None)
    sys.modules["nonebot_plugin_eratw_mirror"] = package
    sys.modules["nonebot_plugin_eratw_mirror.config"] = config_module
    sys.modules["nonebot_plugin_eratw_mirror.models"] = models_module
    sys.modules["nonebot"] = nonebot_module
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _config(proxy: str | None, worker_proxy: str | None):
    return SimpleNamespace(
        eratw_proxy=proxy,
        eratw_worker_proxy=worker_proxy,
    )


def test_worker_proxy_does_not_fall_back_to_bot_proxy():
    remote_worker = _load_remote_worker_module()

    assert (
        remote_worker._worker_proxy(
            _config(" http://bot-proxy.example:7890 ", None)
        )
        is None
    )


def test_worker_proxy_overrides_bot_proxy():
    remote_worker = _load_remote_worker_module()

    assert (
        remote_worker._worker_proxy(
            _config(
                "http://bot-proxy.example:7890",
                " http://worker-proxy.example:7890 ",
            )
        )
        == "http://worker-proxy.example:7890"
    )


def test_empty_worker_proxy_disables_worker_proxy():
    remote_worker = _load_remote_worker_module()

    assert (
        remote_worker._worker_proxy(
            _config("http://bot-proxy.example:7890", "")
        )
        is None
    )
