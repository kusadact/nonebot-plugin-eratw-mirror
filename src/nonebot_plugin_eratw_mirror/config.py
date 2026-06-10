from __future__ import annotations

from pydantic import BaseModel, Field
from nonebot import get_plugin_config


class Config(BaseModel):
    eratw_project_id: int = 28180
    eratw_project_url: str = "https://gitgud.io/era-games-zh/touhou/eratw-sub-modding"
    eratw_git_url: str | None = None
    eratw_api_base: str = "https://gitgud.io/api/v4"
    eratw_branch: str = "main"

    eratw_group_ids: list[int] = Field(default_factory=list)
    eratw_schedule: str = "daily@04:00"
    eratw_schedule_timezone: str = "Asia/Shanghai"
    eratw_push_on_first_run: bool = False

    eratw_proxy: str | None = None
    eratw_request_timeout: float = 60.0

    eratw_archive_password: str = "eratoho"
    eratw_timeout: float = 3600.0
    eratw_git_retries: int = 5
    eratw_git_retry_delay: float = 3.0
    eratw_file_base_url: str | None = None
    eratw_file_route_prefix: str = "/eratw/files"
    eratw_file_token: str | None = None
    eratw_file_token_ttl: int = 3600

    eratw_command_priority: int = 10
    eratw_message_chunk_size: int = 1800


plugin_config = get_plugin_config(Config)
