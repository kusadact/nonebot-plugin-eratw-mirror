from __future__ import annotations

import hashlib
import hmac
from pathlib import Path
from secrets import token_urlsafe
import time
from urllib.parse import quote, urlencode

from nonebot import get_driver, logger
from nonebot_plugin_localstore import get_plugin_data_dir

from .config import Config

_runtime_file_token = token_urlsafe(24)


def register_archive_file_route(config: Config) -> bool:
    driver = get_driver()
    server_app = getattr(driver, "server_app", None)
    if server_app is None or not hasattr(server_app, "add_api_route"):
        message = "eraTW archive HTTP route is unavailable: current driver has no server_app"
        if config.eratw_file_base_url:
            raise RuntimeError(f"{message}, but eratw_file_base_url is configured")
        logger.warning(message)
        return False

    from starlette.responses import FileResponse, Response

    route_prefix = normalize_route_prefix(config.eratw_file_route_prefix)

    async def serve_archive(
        filename: str,
        expires: str | None = None,
        token: str | None = None,
    ) -> Response:
        if not valid_archive_download_token(filename, expires, token, config):
            logger.warning(f"eraTW archive download rejected for {filename}: invalid token")
            return Response(status_code=403)
        if "/" in filename or "\\" in filename:
            logger.warning(f"eraTW archive download rejected for unsafe filename: {filename}")
            return Response(status_code=404)

        archive_dir = (get_plugin_data_dir() / "archives").resolve()
        archive_path = (archive_dir / filename).resolve()
        try:
            archive_path.relative_to(archive_dir)
        except ValueError:
            return Response(status_code=404)

        if not archive_path.is_file():
            logger.warning(f"eraTW archive download not found: {archive_path}")
            return Response(status_code=404)

        logger.info(f"eraTW serving archive download: {archive_path}")
        return FileResponse(
            archive_path,
            media_type="application/x-7z-compressed",
            filename=filename,
        )

    server_app.add_api_route(
        f"{route_prefix}/{{filename}}",
        serve_archive,
        methods=["GET"],
    )
    logger.info(f"eraTW archive HTTP route registered: {route_prefix}/{{filename}}")
    return True


def build_archive_download_url(path: Path, config: Config) -> str | None:
    if not config.eratw_file_base_url:
        return None
    base_url = config.eratw_file_base_url.rstrip("/")
    route_prefix = normalize_route_prefix(config.eratw_file_route_prefix)
    filename = quote(path.name)
    expires_at = int(time.time()) + max(60, int(config.eratw_file_token_ttl))
    query = urlencode(
        {
            "expires": str(expires_at),
            "token": archive_download_token(path.name, expires_at, config),
        }
    )
    return f"{base_url}{route_prefix}/{filename}?{query}"


def archive_file_token(config: Config) -> str:
    return (config.eratw_file_token or "").strip() or _runtime_file_token


def valid_archive_download_token(
    filename: str,
    expires: str | None,
    token: str | None,
    config: Config,
) -> bool:
    if not expires or not token:
        return False
    try:
        expires_at = int(expires)
    except ValueError:
        return False
    if expires_at < int(time.time()):
        return False
    expected = archive_download_token(filename, expires_at, config)
    return hmac.compare_digest(token, expected)


def archive_download_token(filename: str, expires_at: int, config: Config) -> str:
    message = f"{filename}\0{expires_at}".encode("utf-8")
    secret = archive_file_token(config).encode("utf-8")
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def normalize_route_prefix(prefix: str) -> str:
    normalized = "/" + prefix.strip("/")
    return normalized.rstrip("/") or "/eratw/files"
