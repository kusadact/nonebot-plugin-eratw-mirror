from __future__ import annotations

from pydantic import BaseModel, Field
from nonebot import get_plugin_config


class Config(BaseModel):
    eratw_project_id: int = 28180
    eratw_project_url: str = "https://gitgud.io/era-games-zh/touhou/eratw-sub-modding"
    eratw_api_base: str = "https://gitgud.io/api/v4"
    eratw_branch: str = "main"

    eratw_group_ids: list[int] = Field(default_factory=list)
    eratw_poll_interval: int = 1800
    eratw_push_on_first_run: bool = False

    eratw_proxy: str | None = None
    eratw_request_timeout: float = 60.0

    eratw_archive_password: str = "eratoho"
    eratw_7z_path: str | None = None

    eratw_node_user_id: int = 2854196310
    eratw_node_nickname: str = "eraTW 更新"
    eratw_command_priority: int = 10
    eratw_message_chunk_size: int = 1800


plugin_config = get_plugin_config(Config)

