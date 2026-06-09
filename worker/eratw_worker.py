from __future__ import annotations

import hashlib
import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import shutil
import stat
import sys
from threading import Lock
from urllib.parse import parse_qs, quote, unquote, urlparse

from dulwich import porcelain
from dulwich.object_store import iter_tree_contents
from dulwich.repo import Repo
import py7zr


BUILD_LOCK = Lock()


class WorkerConfig:
    def __init__(self) -> None:
        self.host = os.getenv("ERATW_WORKER_HOST", "0.0.0.0")
        self.port = int(os.getenv("ERATW_WORKER_PORT", "18721"))
        self.public_base_url = os.getenv("ERATW_WORKER_PUBLIC_BASE_URL", "").rstrip("/")
        self.token = os.getenv("ERATW_WORKER_TOKEN", "")
        self.data_dir = Path(os.getenv("ERATW_WORKER_DATA_DIR", "/opt/eratw-worker/data"))
        self.cache_dir = Path(os.getenv("ERATW_WORKER_CACHE_DIR", "/opt/eratw-worker/cache"))


CONFIG = WorkerConfig()


class Handler(BaseHTTPRequestHandler):
    server_version = "EraTWWorker/0.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/healthz":
            self._send_json({"ok": True})
            return
        if parsed.path.startswith("/files/"):
            self._serve_file(parsed.path[len("/files/") :], parse_qs(parsed.query))
            return
        self.send_error(404)

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/build":
            self.send_error(404)
            return
        if not self._authorized():
            self.send_error(403)
            return
        try:
            length = int(self.headers.get("Content-Length") or "0")
            if length <= 0 or length > 1024 * 1024:
                self.send_error(400, "invalid request body size")
                return
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            with BUILD_LOCK:
                result = build_archive(payload, self._request_base_url())
            self._send_json(result)
        except Exception as exc:
            self.log_error("build failed: %s", exc)
            self._send_json({"error": str(exc)}, status=500)

    def log_message(self, format: str, *args: object) -> None:
        message = format % tuple(_redact_log_value(str(arg)) for arg in args)
        sys.stderr.write(
            "%s - - [%s] %s\n"
            % (self.address_string(), self.log_date_time_string(), message)
        )

    def _serve_file(self, raw_path: str, query: dict[str, list[str]]) -> None:
        if CONFIG.token and (query.get("token") or [""])[0] != CONFIG.token:
            self.send_error(403)
            return
        parts = [unquote(part) for part in raw_path.split("/") if part]
        if len(parts) != 2:
            self.send_error(404)
            return
        repo_key, filename = parts
        if not _safe_name(repo_key) or not _safe_name(filename) or not filename.endswith(".7z"):
            self.send_error(404)
            return
        archive_dir = (CONFIG.data_dir / "archives" / repo_key).resolve()
        archive_path = (archive_dir / filename).resolve()
        try:
            archive_path.relative_to(archive_dir)
        except ValueError:
            self.send_error(404)
            return
        if not archive_path.is_file():
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/x-7z-compressed")
        self.send_header("Content-Length", str(archive_path.stat().st_size))
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        with archive_path.open("rb") as file:
            shutil.copyfileobj(file, self.wfile)

    def _authorized(self) -> bool:
        if not CONFIG.token:
            return True
        auth = self.headers.get("Authorization", "")
        token = self.headers.get("X-EraTW-Token", "")
        return auth == f"Bearer {CONFIG.token}" or token == CONFIG.token

    def _request_base_url(self) -> str:
        if CONFIG.public_base_url:
            return CONFIG.public_base_url
        host = self.headers.get("Host") or f"127.0.0.1:{CONFIG.port}"
        return f"http://{host}".rstrip("/")

    def _send_json(self, data: dict, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def build_archive(payload: dict, base_url: str) -> dict:
    sha = _required_text(payload, "sha")
    short_sha = _clean_short_sha(str(payload.get("short_sha") or sha[:8]))
    git_url = _required_text(payload, "git_url")
    branch = str(payload.get("branch") or "main")
    password = str(payload.get("archive_password") or "eratoho")
    git_depth = int(payload.get("git_depth") or 1)
    proxy = str(payload.get("proxy") or "").strip()

    repo_key = hashlib.sha256(f"{git_url}\0{branch}".encode("utf-8")).hexdigest()[:16]
    repo_dir = CONFIG.data_dir / "git" / f"{repo_key}.git"
    output_dir = CONFIG.data_dir / "archives" / repo_key
    work_dir = CONFIG.cache_dir / "work" / repo_key / sha
    source = work_dir / f"eratw-sub-modding-{short_sha}"
    archive_path = output_dir / f"eratw-sub-modding-{short_sha}.7z"

    if archive_path.exists() and archive_path.stat().st_size > 0:
        return _archive_response(archive_path, repo_key, password, base_url)

    output_dir.mkdir(parents=True, exist_ok=True)
    _ensure_git_repo(repo_dir, git_url, branch, git_depth, proxy)
    _fetch_git_repo(repo_dir, git_url, git_depth, proxy)
    _verify_commit(repo_dir, sha)

    if work_dir.exists():
        shutil.rmtree(work_dir)
    source.mkdir(parents=True, exist_ok=True)
    _export_commit_tree(repo_dir, source, sha)

    tmp_archive = archive_path.with_suffix(".7z.tmp")
    if tmp_archive.exists():
        tmp_archive.unlink()
    _write_7z(source, tmp_archive, password)
    tmp_archive.replace(archive_path)
    return _archive_response(archive_path, repo_key, password, base_url)


def _ensure_git_repo(repo_dir: Path, git_url: str, branch: str, depth: int, proxy: str) -> None:
    if repo_dir.exists() and not _is_valid_git_repo(repo_dir):
        shutil.rmtree(repo_dir)
    if repo_dir.exists():
        return
    repo_dir.parent.mkdir(parents=True, exist_ok=True)
    try:
        repo = _with_git_env(
            proxy,
            porcelain.clone,
            git_url,
            target=str(repo_dir),
            bare=True,
            checkout=False,
            depth=_git_depth(depth),
            branch=branch,
            errstream=_NullBinaryWriter(),
        )
        repo.close()
    except Exception:
        if repo_dir.exists():
            shutil.rmtree(repo_dir)
        raise


def _fetch_git_repo(repo_dir: Path, git_url: str, depth: int, proxy: str) -> None:
    repo = Repo(str(repo_dir))
    try:
        _with_git_env(
            proxy,
            porcelain.fetch,
            repo,
            remote_location=git_url,
            depth=_git_depth(depth),
            prune=True,
            force=True,
            quiet=True,
            errstream=_NullBinaryWriter(),
        )
    finally:
        repo.close()


def _verify_commit(repo_dir: Path, sha: str) -> None:
    repo = Repo(str(repo_dir))
    try:
        repo[sha.encode()]
    finally:
        repo.close()


def _export_commit_tree(repo_dir: Path, destination: Path, sha: str) -> None:
    repo = Repo(str(repo_dir))
    try:
        commit = repo[sha.encode()]
        root = destination.resolve()
        for entry in iter_tree_contents(repo.object_store, commit.tree, include_trees=False):
            target = _safe_git_path(root, entry.path)
            target.parent.mkdir(parents=True, exist_ok=True)
            obj = repo[entry.sha]
            if stat.S_ISLNK(entry.mode):
                os.symlink(os.fsdecode(obj.data), target)
                continue
            if not stat.S_ISREG(entry.mode):
                raise RuntimeError(f"Unsupported git entry mode {entry.mode:o}: {entry.path!r}")
            target.write_bytes(obj.data)
            if entry.mode & 0o111:
                target.chmod(0o755)
    finally:
        repo.close()


def _write_7z(source: Path, output: Path, password: str) -> None:
    with py7zr.SevenZipFile(
        output,
        "w",
        filters=[{"id": py7zr.FILTER_COPY}],
        password=password,
        header_encryption=True,
        dereference=False,
    ) as archive:
        archive.writeall(source, arcname=source.name)


def _archive_response(path: Path, repo_key: str, password: str, base_url: str) -> dict:
    token_query = f"?token={quote(CONFIG.token)}" if CONFIG.token else ""
    return {
        "name": path.name,
        "size": path.stat().st_size,
        "sha256": _sha256(path),
        "password": password,
        "path": str(path),
        "download_url": f"{base_url}/files/{quote(repo_key)}/{quote(path.name)}{token_query}",
    }


def _with_git_env(proxy: str, func, *args, **kwargs):
    updates = {"GIT_TERMINAL_PROMPT": "0"}
    if proxy:
        updates.update(
            {
                "http_proxy": proxy,
                "https_proxy": proxy,
                "all_proxy": proxy,
                "HTTP_PROXY": proxy,
                "HTTPS_PROXY": proxy,
                "ALL_PROXY": proxy,
            }
        )
    previous = {key: os.environ.get(key) for key in updates}
    os.environ.update(updates)
    try:
        return func(*args, **kwargs)
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _is_valid_git_repo(repo_dir: Path) -> bool:
    try:
        repo = Repo(str(repo_dir))
    except Exception:
        return False
    repo.close()
    return True


def _safe_git_path(root: Path, raw_path: bytes) -> Path:
    parts = os.fsdecode(raw_path).split("/")
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise RuntimeError(f"Unsafe git path: {raw_path!r}")
    target = (root / Path(*parts)).resolve()
    target.relative_to(root)
    return target


def _required_text(payload: dict, key: str) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise RuntimeError(f"missing required field: {key}")
    return value


def _clean_short_sha(value: str) -> str:
    cleaned = "".join(char for char in value if char.isalnum() or char in {"-", "_"})
    return cleaned[:32] or "unknown"


def _safe_name(value: str) -> bool:
    return bool(value) and all(char.isalnum() or char in {"-", "_", "."} for char in value)


def _redact_log_value(value: str) -> str:
    return re.sub(r"([?&]token=)[^\\s&\"]+", r"\\1<redacted>", value)


def _git_depth(depth: int) -> int | None:
    return depth if depth > 0 else None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class _NullBinaryWriter:
    def write(self, data: bytes) -> int:
        return len(data)

    def flush(self) -> None:
        return None


def main() -> None:
    CONFIG.data_dir.mkdir(parents=True, exist_ok=True)
    CONFIG.cache_dir.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((CONFIG.host, CONFIG.port), Handler)
    print(f"eraTW worker listening on {CONFIG.host}:{CONFIG.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
