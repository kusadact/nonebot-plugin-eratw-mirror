from __future__ import annotations

from pathlib import Path
from secrets import token_urlsafe
from urllib.parse import quote, urlencode

from nonebot import get_driver, logger
from nonebot_plugin_localstore import get_plugin_data_dir

from .config import Config

_runtime_file_token = token_urlsafe(24)


def register_archive_file_route(config: Config) -> None:
    driver = get_driver()
    server_app = getattr(driver, "server_app", None)
    if server_app is None or not hasattr(server_app, "add_api_route"):
        logger.warning("eraTW archive HTTP route is unavailable: current driver has no server_app")
        return

    from starlette.responses import FileResponse, Response

    route_prefix = normalize_route_prefix(config.eratw_file_route_prefix)

    async def serve_archive(filename: str, token: str | None = None) -> Response:
        if token != archive_file_token(config):
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


def build_archive_download_url(path: Path, config: Config) -> str | None:
    if not config.eratw_file_base_url:
        return None
    base_url = config.eratw_file_base_url.rstrip("/")
    route_prefix = normalize_route_prefix(config.eratw_file_route_prefix)
    filename = quote(path.name)
    query = urlencode({"token": archive_file_token(config)})
    return f"{base_url}{route_prefix}/{filename}?{query}"


def archive_file_token(config: Config) -> str:
    return (config.eratw_file_token or "").strip() or _runtime_file_token


def normalize_route_prefix(prefix: str) -> str:
    normalized = "/" + prefix.strip("/")
    return normalized.rstrip("/") or "/eratw/files"
