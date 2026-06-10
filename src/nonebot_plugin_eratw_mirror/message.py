from __future__ import annotations

from urllib.parse import urlparse

from nonebot import logger
from nonebot.adapters.onebot.v11 import Bot, Message, MessageSegment

from .config import Config
from .file_server import build_archive_download_url
from .models import UpdatePayload

DEFAULT_NODE_USER_ID = 2854196310


def build_forward_nodes(
    payload: UpdatePayload,
    config: Config,
    *,
    archive_uploaded: bool,
) -> list[MessageSegment]:
    nodes: list[MessageSegment] = []
    logger.debug(
        f"eraTW building forward nodes for {payload.target_short_sha}: "
        f"{len(payload.commits)} commits"
    )
    for index, commit in enumerate(payload.commits, start=1):
        content = "\n".join(
            item
            for item in (
                f"{index}. {commit.title}",
                f"commit: {commit.short_id}",
                f"time: {commit.committed_date}" if commit.committed_date else "",
                commit.web_url,
            )
            if item
        )
        nodes.append(_node(content, config))

    nodes.append(_node(_archive_text(payload, archive_uploaded=archive_uploaded), config))

    changelog = payload.changelog.strip() or "本次提交未更新 ADD_BANQUET_开发日志.md"
    chunks = split_text(changelog, config.eratw_message_chunk_size)
    logger.debug(f"eraTW changelog split into {len(chunks)} forward nodes")
    for index, chunk in enumerate(chunks, start=1):
        title = "本次更新的开发日志"
        if len(chunks) > 1:
            title = f"{title} {index}/{len(chunks)}"
        nodes.append(_node(f"{title}\n\n{chunk}", config))
    return nodes


async def upload_payload_archive_to_group(
    bot: Bot,
    group_id: int,
    payload: UpdatePayload,
    config: Config,
) -> None:
    upload_source = build_archive_download_url(payload.archive.path, config)
    if upload_source:
        logger.info(
            f"eraTW archive upload source for group {group_id} uses HTTP route: "
            f"{upload_source.split('?', 1)[0]}"
        )
    else:
        upload_source = str(payload.archive.path)
        logger.warning(
            "eraTW eratw_file_base_url is not configured; falling back to local archive path. "
            "This only works when the OneBot implementation can read the same filesystem."
        )
    logger.info(
        f"eraTW uploading archive to group {group_id}: "
        f"{payload.archive.name} ({payload.archive.size / 1024 / 1024:.2f} MiB)"
    )
    api_params: dict[str, object] = {
        "group_id": int(group_id),
        "file": upload_source,
        "name": payload.archive.name,
        "_timeout": config.eratw_timeout,
    }
    logger.info(
        f"eraTW upload_group_file API timeout for group {group_id}: "
        f"{config.eratw_timeout} seconds"
    )
    await bot.call_api("upload_group_file", **api_params)
    logger.info(f"eraTW archive uploaded to group {group_id}: {payload.archive.name}")


async def send_payload_forward_to_group(
    bot: Bot,
    group_id: int,
    payload: UpdatePayload,
    config: Config,
    *,
    archive_uploaded: bool,
) -> None:
    nodes = build_forward_nodes(payload, config, archive_uploaded=archive_uploaded)
    logger.info(f"eraTW sending forward message to group {group_id}: {len(nodes)} nodes")
    await bot.send_group_forward_msg(group_id=int(group_id), messages=nodes)
    logger.info(f"eraTW forward message sent to group {group_id}")


async def send_payload_to_group(bot: Bot, group_id: int, payload: UpdatePayload, config: Config) -> None:
    await upload_payload_archive_to_group(bot, group_id, payload, config)
    await send_payload_forward_to_group(
        bot,
        group_id,
        payload,
        config,
        archive_uploaded=True,
    )


async def send_payload_to_private(bot: Bot, user_id: int, payload: UpdatePayload, config: Config) -> None:
    nodes = build_forward_nodes(payload, config, archive_uploaded=False)
    logger.info(f"eraTW sending private forward message to user {user_id}: {len(nodes)} nodes")
    await bot.send_private_forward_msg(user_id=int(user_id), messages=nodes)
    logger.info(f"eraTW private forward message sent to user {user_id}")


def split_text(text: str, limit: int) -> list[str]:
    if limit <= 0:
        return [text]
    chunks: list[str] = []
    current = ""
    for line in text.splitlines(keepends=True):
        if len(line) > limit:
            if current:
                chunks.append(current.rstrip())
                current = ""
            for start in range(0, len(line), limit):
                chunks.append(line[start : start + limit].rstrip())
            continue
        if current and len(current) + len(line) > limit:
            chunks.append(current.rstrip())
            current = ""
        current += line
    if current:
        chunks.append(current.rstrip())
    return chunks or [""]


def _node(content: str, config: Config) -> MessageSegment:
    return MessageSegment.node_custom(
        user_id=DEFAULT_NODE_USER_ID,
        nickname=_repository_name(config),
        content=Message(content),
    )


def _repository_name(config: Config) -> str:
    source = (config.eratw_git_url or config.eratw_project_url).strip().rstrip("/")
    if not source:
        return "Git 更新"
    path = urlparse(source).path or source
    name = path.rsplit("/", 1)[-1]
    if ":" in name:
        name = name.rsplit(":", 1)[-1]
    if name.endswith(".git"):
        name = name[:-4]
    return name or "Git 更新"


def _archive_text(payload: UpdatePayload, *, archive_uploaded: bool) -> str:
    status = "已上传群文件" if archive_uploaded else "未上传群文件"
    size_mb = payload.archive.size / 1024 / 1024
    return "\n".join(
        [
            "加密压缩包",
            f"状态: {status}",
            f"文件名: {payload.archive.name}",
            f"大小: {size_mb:.2f} MiB",
            f"密码: {payload.archive.password}",
            f"sha256: {payload.archive.sha256}",
        ]
    )
