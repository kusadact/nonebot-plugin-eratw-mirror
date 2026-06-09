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
            logger.info("eraTW scheduled check started")
            async with GitGudClient(self.config) as client:
                head = await client.get_branch_head()
                state = self.state.read_state()
                last_sha = state.get("last_success_sha")
                logger.info(
                    f"eraTW state check: last_success={str(last_sha)[:8] if last_sha else '<empty>'}, "
                    f"remote={head.short_id}"
                )

                if not last_sha:
                    if not self.config.eratw_push_on_first_run:
                        logger.info(
                            "eraTW first run detected; storing current head without pushing "
                            f"because eratw_push_on_first_run is false: {head.short_id}"
                        )
                        self.state.set_initial_sha(head.id)
                        return None
                    logger.info("eraTW first run push is enabled; preparing single commit payload")
                    payload = await self._build_single_commit_payload(client, head.id)
                    self.state.write_last_payload(payload)
                    return payload

                if last_sha == head.id:
                    logger.info(f"eraTW no update found: {head.short_id}")
                    return None

                commits, diffs = await client.compare(str(last_sha), head.id)
                if not commits:
                    logger.warning("eraTW compare returned no commits; falling back to branch head")
                    commits = [head]
                archive = await build_encrypted_archive(head.id, head.short_id, self.config)
                changelog = extract_changelog_from_diffs(diffs)
                payload = UpdatePayload(
                    target_sha=head.id,
                    target_short_sha=head.short_id,
                    generated_at=_now_iso(),
                    commits=commits,
                    archive=archive,
                    changelog=changelog,
                )
                self.state.write_last_payload(payload)
                logger.info(
                    f"eraTW prepared payload for {head.short_id}: "
                    f"{len(commits)} commits, changelog={'yes' if changelog else 'no'}"
                )
                return payload

    async def prepare_test_payload(self) -> tuple[UpdatePayload, bool]:
        logger.info("eraTW test payload requested")
        cached = self.state.read_last_payload()
        if cached is not None:
            logger.info(f"eraTW using cached test payload: {cached.target_short_sha}")
            return cached, True
        async with self._lock:
            async with GitGudClient(self.config) as client:
                head = await client.get_branch_head()
                logger.info(f"eraTW no cached payload; preparing latest commit payload: {head.short_id}")
                payload = await self._build_single_commit_payload(client, head.id)
                self.state.write_last_payload(payload)
                return payload, False

    def mark_success(self, payload: UpdatePayload) -> None:
        logger.info(f"eraTW marking push success: {payload.target_short_sha}")
        self.state.set_last_success(payload.target_sha, _now_iso())

    def successful_groups(self, payload: UpdatePayload) -> set[int]:
        return self.state.read_successful_groups(payload.target_sha)

    def mark_group_success(self, payload: UpdatePayload, group_id: int) -> None:
        self.state.add_successful_group(payload.target_sha, group_id)

    async def _build_single_commit_payload(self, client: GitGudClient, sha: str) -> UpdatePayload:
        logger.info(f"eraTW preparing single commit payload: {sha[:8]}")
        commit = await client.get_commit(sha)
        diffs = await client.get_commit_diffs(sha)
        archive = await build_encrypted_archive(commit.id, commit.short_id, self.config)
        changelog = extract_changelog_from_diffs(diffs)
        logger.info(
            f"eraTW single payload ready for {commit.short_id}: "
            f"{len(diffs)} diffs, changelog={'yes' if changelog else 'no'}"
        )
        return UpdatePayload(
            target_sha=commit.id,
            target_short_sha=commit.short_id,
            generated_at=_now_iso(),
            commits=[commit],
            archive=archive,
            changelog=changelog,
        )


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
