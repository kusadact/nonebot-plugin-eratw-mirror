from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CommitInfo:
    id: str
    short_id: str
    title: str
    committed_date: str
    web_url: str

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "CommitInfo":
        commit_id = str(data["id"])
        return cls(
            id=commit_id,
            short_id=str(data.get("short_id") or commit_id[:8]),
            title=str(data.get("title") or data.get("message") or commit_id[:8]).strip(),
            committed_date=str(data.get("committed_date") or data.get("created_at") or ""),
            web_url=str(data.get("web_url") or ""),
        )

    def to_json(self) -> dict[str, str]:
        return {
            "id": self.id,
            "short_id": self.short_id,
            "title": self.title,
            "committed_date": self.committed_date,
            "web_url": self.web_url,
        }


@dataclass(frozen=True)
class ArchiveInfo:
    path: Path
    name: str
    size: int
    sha256: str
    password: str

    def to_json(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "name": self.name,
            "size": self.size,
            "sha256": self.sha256,
            "password": self.password,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "ArchiveInfo":
        return cls(
            path=Path(str(data["path"])),
            name=str(data["name"]),
            size=int(data["size"]),
            sha256=str(data["sha256"]),
            password=str(data["password"]),
        )


@dataclass(frozen=True)
class UpdatePayload:
    target_sha: str
    target_short_sha: str
    generated_at: str
    commits: list[CommitInfo]
    archive: ArchiveInfo
    changelog: str

    def to_json(self) -> dict[str, Any]:
        return {
            "target_sha": self.target_sha,
            "target_short_sha": self.target_short_sha,
            "generated_at": self.generated_at,
            "commits": [commit.to_json() for commit in self.commits],
            "archive": self.archive.to_json(),
            "changelog": self.changelog,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "UpdatePayload":
        return cls(
            target_sha=str(data["target_sha"]),
            target_short_sha=str(data["target_short_sha"]),
            generated_at=str(data["generated_at"]),
            commits=[CommitInfo.from_api(item) for item in data.get("commits", [])],
            archive=ArchiveInfo.from_json(data["archive"]),
            changelog=str(data.get("changelog") or ""),
        )

