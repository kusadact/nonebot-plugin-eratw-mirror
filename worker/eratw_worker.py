from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from secrets import token_urlsafe
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import shutil
import stat
import sys
import time
from threading import Lock
from urllib.parse import parse_qs, quote, unquote, urlencode, urlparse

from dulwich import porcelain
from dulwich.object_store import iter_tree_contents
from dulwich.repo import Repo
import py7zr


BUILD_LOCK = Lock()
ARCHIVE_CACHE_VERSION = 1
DEFAULT_GIT_RETRIES = 5
DEFAULT_GIT_RETRY_DELAY = 3.0
DEFAULT_FILE_TOKEN_TTL = 3600


def _env_int(name: str, default: int, *, minimum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return max(minimum, value)


def _env_float(name: str, default: float, *, minimum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        return default
    return max(minimum, value)


def _load_file_token(data_dir: Path) -> str:
    token_path = data_dir / "file_download_token"
    try:
        if token_path.exists():
            token = token_path.read_text(encoding="utf-8").strip()
            if token:
                return token
        data_dir.mkdir(parents=True, exist_ok=True)
        token = token_urlsafe(32)
        token_path.write_text(token, encoding="utf-8")
        token_path.chmod(0o600)
        return token
    except OSError:
        return token_urlsafe(32)


class WorkerConfig:
    def __init__(self) -> None:
        self.host = os.getenv("ERATW_WORKER_HOST", "0.0.0.0")
        self.port = int(os.getenv("ERATW_WORKER_PORT", "18721"))
        self.public_base_url = os.getenv("ERATW_WORKER_PUBLIC_BASE_URL", "").rstrip("/")
        self.token = os.getenv("ERATW_WORKER_TOKEN", "")
        self.data_dir = Path(os.getenv("ERATW_WORKER_DATA_DIR", "/opt/eratw-worker/data"))
        self.cache_dir = Path(os.getenv("ERATW_WORKER_CACHE_DIR", "/opt/eratw-worker/cache"))
        self.file_token = os.getenv("ERATW_WORKER_FILE_TOKEN", "").strip()
        self.file_token_ttl = _env_int(
            "ERATW_WORKER_FILE_TOKEN_TTL",
            DEFAULT_FILE_TOKEN_TTL,
            minimum=60,
        )
        self.git_retries = _env_int("ERATW_WORKER_GIT_RETRIES", DEFAULT_GIT_RETRIES, minimum=1)
        self.git_retry_delay = _env_float(
            "ERATW_WORKER_GIT_RETRY_DELAY",
            DEFAULT_GIT_RETRY_DELAY,
            minimum=0.0,
        )


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
        message = _format_log_message(format, args)
        sys.stderr.write(
            "%s - - [%s] %s\n"
            % (self.address_string(), self.log_date_time_string(), message)
        )

    def _serve_file(self, raw_path: str, query: dict[str, list[str]]) -> None:
        parts = [unquote(part) for part in raw_path.split("/") if part]
        if len(parts) != 2:
            self.send_error(404)
            return
        repo_key, filename = parts
        if not _safe_name(repo_key) or not _safe_name(filename) or not filename.endswith(".7z"):
            self.send_error(404)
            return
        if not _valid_download_token(repo_key, filename, query):
            self.send_error(403)
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
            return False
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
    metadata_path = _archive_metadata_path(archive_path)

    cached_archive = _cached_archive_response(
        archive_path,
        metadata_path,
        sha,
        git_url,
        branch,
        password,
        base_url,
        repo_key,
    )
    if cached_archive is not None:
        return cached_archive

    output_dir.mkdir(parents=True, exist_ok=True)
    _sync_git_repo(repo_dir, git_url, branch, git_depth, proxy, sha)

    if work_dir.exists():
        shutil.rmtree(work_dir)
    source.mkdir(parents=True, exist_ok=True)
    _export_commit_tree(repo_dir, source, sha)

    tmp_archive = archive_path.with_suffix(".7z.tmp")
    if tmp_archive.exists():
        tmp_archive.unlink()
    try:
        _write_7z(source, tmp_archive, password)
        tmp_archive.replace(archive_path)
    finally:
        if tmp_archive.exists():
            tmp_archive.unlink()
    response = _archive_response(archive_path, repo_key, password, base_url)
    _write_archive_metadata(metadata_path, sha, git_url, branch, password, response)
    return response


def _sync_git_repo(repo_dir: Path, git_url: str, branch: str, depth: int, proxy: str, sha: str) -> None:
    _run_git_step(
        f"git clone {git_url}",
        repo_dir,
        lambda: _ensure_git_repo(repo_dir, git_url, branch, depth, proxy),
    )
    _run_git_step(
        f"git fetch {branch}",
        repo_dir,
        lambda: _fetch_git_repo(repo_dir, git_url, depth, proxy),
    )
    _run_git_step(
        f"git verify {sha[:8]}",
        repo_dir,
        lambda: _verify_commit(repo_dir, sha),
    )


def _run_git_step(label: str, repo_dir: Path, operation) -> None:
    attempts = max(1, CONFIG.git_retries)
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            operation()
            return
        except Exception as exc:
            last_error = exc
            _remove_invalid_git_repo(repo_dir)
            if attempt >= attempts:
                break
            delay = _git_retry_delay(attempt)
            _log_worker(
                f"{label} failed on attempt {attempt}/{attempts}: {exc}; "
                f"retrying in {delay:.1f}s"
            )
            time.sleep(delay)
    raise RuntimeError(f"{label} failed after {attempts} attempts: {last_error}") from last_error


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
                link_target = os.fsdecode(obj.data)
                resolved = (target.parent / link_target).resolve()
                if not str(resolved).startswith(str(root) + os.sep) and resolved != root:
                    raise RuntimeError(
                        f"Symlink escapes export root: {entry.path!r} -> {link_target!r}"
                    )
                os.symlink(link_target, target)
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
    download_expires_at = int(time.time()) + CONFIG.file_token_ttl
    query = _download_url_query(repo_key, path.name, download_expires_at)
    return {
        "name": path.name,
        "size": path.stat().st_size,
        "sha256": _sha256(path),
        "password": password,
        "path": str(path),
        "download_url": f"{base_url}/files/{quote(repo_key)}/{quote(path.name)}?{query}",
        "download_expires_at": download_expires_at,
    }


def _cached_archive_response(
    archive_path: Path,
    metadata_path: Path,
    sha: str,
    git_url: str,
    branch: str,
    password: str,
    base_url: str,
    repo_key: str,
) -> dict | None:
    if not archive_path.exists() or archive_path.stat().st_size <= 0:
        return None
    metadata = _read_archive_metadata(metadata_path)
    if metadata is None:
        return None
    expected = _archive_cache_key(sha, git_url, branch, password)
    for key, value in expected.items():
        if metadata.get(key) != value:
            return None
    response = _archive_response(archive_path, repo_key, password, base_url)
    if int(metadata.get("archive_size") or -1) != response["size"]:
        return None
    if str(metadata.get("archive_sha256") or "") != response["sha256"]:
        return None
    return response


def _archive_cache_key(sha: str, git_url: str, branch: str, password: str) -> dict[str, object]:
    return {
        "version": ARCHIVE_CACHE_VERSION,
        "commit_sha": sha,
        "git_url": git_url,
        "branch": branch,
        "password_sha256": _text_sha256(password),
    }


def _read_archive_metadata(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    return data


def _write_archive_metadata(
    path: Path,
    sha: str,
    git_url: str,
    branch: str,
    password: str,
    response: dict,
) -> None:
    data = {
        **_archive_cache_key(sha, git_url, branch, password),
        "archive_name": response["name"],
        "archive_size": response["size"],
        "archive_sha256": response["sha256"],
    }
    tmp_path = path.with_suffix(f"{path.suffix}.tmp")
    tmp_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp_path.replace(path)


def _archive_metadata_path(path: Path) -> Path:
    return path.with_suffix(f"{path.suffix}.json")


_git_env_lock = Lock()


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
    with _git_env_lock:
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


def _remove_invalid_git_repo(repo_dir: Path) -> None:
    if repo_dir.exists() and not _is_valid_git_repo(repo_dir):
        shutil.rmtree(repo_dir)


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


def _download_url_query(repo_key: str, filename: str, expires_at: int) -> str:
    token = _download_token(repo_key, filename, expires_at)
    return urlencode({"expires": str(expires_at), "token": token})


def _valid_download_token(repo_key: str, filename: str, query: dict[str, list[str]]) -> bool:
    token = (query.get("token") or [""])[0]
    expires_text = (query.get("expires") or [""])[0]
    try:
        expires_at = int(expires_text)
    except ValueError:
        return False
    if expires_at < int(time.time()):
        return False
    expected = _download_token(repo_key, filename, expires_at)
    return hmac.compare_digest(token, expected)


def _download_token(repo_key: str, filename: str, expires_at: int) -> str:
    message = f"{repo_key}\0{filename}\0{expires_at}".encode("utf-8")
    secret = _download_secret().encode("utf-8")
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def _download_secret() -> str:
    if not CONFIG.file_token:
        CONFIG.file_token = _load_file_token(CONFIG.data_dir)
    return CONFIG.file_token


def _format_log_message(format: str, args: tuple[object, ...]) -> str:
    try:
        message = format % args
    except Exception:
        message = " ".join([format, *(str(arg) for arg in args)])
    return _redact_log_value(str(message))


def _redact_log_value(value: str) -> str:
    return re.sub(r"([?&]token=)[^\s&\"]+", r"\1<redacted>", value)


def _git_depth(depth: int) -> int | None:
    return depth if depth > 0 else None


def _git_retry_delay(failed_attempt: int) -> float:
    return CONFIG.git_retry_delay * (2 ** max(0, failed_attempt - 1))


def _log_worker(message: str) -> None:
    sys.stderr.write(f"{_redact_log_value(message)}\n")
    sys.stderr.flush()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class _NullBinaryWriter:
    def write(self, data: bytes) -> int:
        return len(data)

    def flush(self) -> None:
        return None


def main() -> None:
    if not CONFIG.token:
        raise RuntimeError("ERATW_WORKER_TOKEN is required")
    CONFIG.data_dir.mkdir(parents=True, exist_ok=True)
    CONFIG.cache_dir.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((CONFIG.host, CONFIG.port), Handler)
    print(f"eraTW worker listening on {CONFIG.host}:{CONFIG.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
