from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from nonebot import logger
from nonebot_plugin_localstore import get_plugin_data_dir

from .models import UpdatePayload


class StateStore:
    def __init__(self) -> None:
        self.data_dir = get_plugin_data_dir()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.data_dir / "state.json"
        self.payload_path = self.data_dir / "last_payload.json"

    def read_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            logger.debug(f"eraTW state file does not exist yet: {self.state_path}")
            return {}
        logger.debug(f"eraTW reading state file: {self.state_path}")
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def write_state(self, state: dict[str, Any]) -> None:
        self._write_json(self.state_path, state)

    def set_last_success(self, sha: str, pushed_at: str) -> None:
        state = self.read_state()
        state["last_success_sha"] = sha
        state["last_push_time"] = pushed_at
        state.pop("group_push_success", None)
        logger.info(f"eraTW state last_success_sha updated to {sha[:8]}")
        self.write_state(state)

    def set_initial_sha(self, sha: str) -> None:
        state = self.read_state()
        state["last_success_sha"] = sha
        logger.info(f"eraTW state initialized with sha {sha[:8]}")
        self.write_state(state)

    def read_last_payload(self) -> UpdatePayload | None:
        if not self.payload_path.exists():
            logger.debug(f"eraTW payload cache does not exist yet: {self.payload_path}")
            return None
        logger.debug(f"eraTW reading payload cache: {self.payload_path}")
        data = json.loads(self.payload_path.read_text(encoding="utf-8"))
        payload = UpdatePayload.from_json(data)
        if not payload.archive.path.exists():
            logger.warning(
                f"eraTW cached payload archive is missing; ignoring cache: {payload.archive.path}"
            )
            return None
        archive_dir = (self.data_dir / "archives").resolve()
        try:
            payload.archive.path.resolve().relative_to(archive_dir)
        except ValueError:
            logger.warning(
                "eraTW cached payload archive is outside current data archive dir; "
                f"ignoring cache: {payload.archive.path}"
            )
            return None
        return payload

    def write_last_payload(self, payload: UpdatePayload) -> None:
        logger.info(f"eraTW writing payload cache for {payload.target_short_sha}: {self.payload_path}")
        self._write_json(self.payload_path, payload.to_json())

    def read_successful_groups(self, sha: str) -> set[int]:
        data = self.read_state().get("group_push_success")
        if not isinstance(data, dict) or data.get("sha") != sha:
            return set()
        groups = data.get("groups")
        if not isinstance(groups, list):
            return set()
        result: set[int] = set()
        for group_id in groups:
            try:
                result.add(int(group_id))
            except (TypeError, ValueError):
                continue
        return result

    def add_successful_group(self, sha: str, group_id: int) -> None:
        state = self.read_state()
        data = state.get("group_push_success")
        if not isinstance(data, dict) or data.get("sha") != sha:
            data = {"sha": sha, "groups": []}
        groups = data.get("groups")
        if not isinstance(groups, list):
            groups = []
        group_text = str(int(group_id))
        if group_text not in {str(item) for item in groups}:
            groups.append(group_text)
        data["groups"] = groups
        state["group_push_success"] = data
        logger.info(f"eraTW recorded successful group push for {sha[:8]}: {group_id}")
        self.write_state(state)

    @staticmethod
    def _write_json(path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(f"{path.suffix}.tmp")
        tmp_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp_path.replace(path)
