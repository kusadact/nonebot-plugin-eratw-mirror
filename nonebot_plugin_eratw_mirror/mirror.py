from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from nonebot import logger

from .archive import build_encrypted_archive
from .changelog import extract_changelog_from_diffs
from .config import Config
from .gitgud import GitGudClient
from .models import UpdatePayload
from .state import StateStore


class MirrorService:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.state = StateStore()
        self._lock = asyncio.Lock()

    async def check_once(self) -> UpdatePayload | None:
        async with self._lock:
            async with GitGudClient(self.config) as client:
                head = await client.get_branch_head()
                state = self.state.read_state()
                last_sha = state.get("last_success_sha")

                if not last_sha:
                    if not self.config.eratw_push_on_first_run:
                        self.state.set_initial_sha(head.id)
                        return None
                    payload = await self._build_single_commit_payload(client, head.id)
                    self.state.write_last_payload(payload)
                    return payload

                if last_sha == head.id:
                    return None

                commits, diffs = await client.compare(str(last_sha), head.id)
                if not commits:
                    commits = [head]
                archive = await build_encrypted_archive(client, head.id, head.short_id, self.config)
                payload = UpdatePayload(
                    target_sha=head.id,
                    target_short_sha=head.short_id,
                    generated_at=_now_iso(),
                    commits=commits,
                    archive=archive,
                    changelog=extract_changelog_from_diffs(diffs),
                )
                self.state.write_last_payload(payload)
                return payload

    async def prepare_test_payload(self) -> tuple[UpdatePayload, bool]:
        cached = self.state.read_last_payload()
        if cached is not None:
            return cached, True
        async with self._lock:
            async with GitGudClient(self.config) as client:
                head = await client.get_branch_head()
                payload = await self._build_single_commit_payload(client, head.id)
                self.state.write_last_payload(payload)
                return payload, False

    def mark_success(self, payload: UpdatePayload) -> None:
        self.state.set_last_success(payload.target_sha, _now_iso())

    async def _build_single_commit_payload(self, client: GitGudClient, sha: str) -> UpdatePayload:
        commit = await client.get_commit(sha)
        diffs = await client.get_commit_diffs(sha)
        archive = await build_encrypted_archive(client, commit.id, commit.short_id, self.config)
        return UpdatePayload(
            target_sha=commit.id,
            target_short_sha=commit.short_id,
            generated_at=_now_iso(),
            commits=[commit],
            archive=archive,
            changelog=extract_changelog_from_diffs(diffs),
        )


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

