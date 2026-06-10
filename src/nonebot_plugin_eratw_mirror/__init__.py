from __future__ import annotations

from nonebot import get_bots, logger, on_command, require
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageEvent
from nonebot.exception import FinishedException
from nonebot.matcher import Matcher
from nonebot.permission import SUPERUSER
from nonebot.plugin import PluginMetadata

require("nonebot_plugin_apscheduler")
require("nonebot_plugin_localstore")

from nonebot_plugin_apscheduler import scheduler

from .config import Config, plugin_config, validate_worker_config
from .message import (
    send_payload_forward_to_group,
    send_payload_to_group,
    send_payload_to_private,
    upload_payload_archive_to_group,
)
from .mirror import MirrorService
from .schedule import parse_schedule

__plugin_meta__ = PluginMetadata(
    name="eraTW Mirror",
    description="搬运 GitGud eraTW 更新归档和开发日志",
    usage="/eratw测试推送\n/拉取最新版",
    type="application",
    config=Config,
    supported_adapters={"~onebot.v11"},
)

validate_worker_config(plugin_config)

service = MirrorService(plugin_config)
schedule_spec = parse_schedule(
    plugin_config.eratw_schedule,
    plugin_config.eratw_schedule_timezone,
)

logger.info(
    "eraTW mirror plugin loaded: "
    f"branch={plugin_config.eratw_branch}, "
    f"schedule={schedule_spec.description if schedule_spec else 'disabled'}, "
    f"groups={plugin_config.eratw_group_ids}, "
    f"proxy={'configured' if plugin_config.eratw_proxy else 'none'}"
)

test_push = on_command(
    "eratw测试推送",
    permission=SUPERUSER,
    priority=plugin_config.eratw_command_priority,
    block=True,
)

pull_latest = on_command(
    "拉取最新版",
    permission=SUPERUSER,
    priority=plugin_config.eratw_command_priority,
    block=True,
)


@test_push.handle()
async def _(bot: Bot, event: MessageEvent, matcher: Matcher) -> None:
    try:
        logger.info(f"eraTW test push command triggered by user {event.user_id}")
        await matcher.send("开始准备 eraTW 测试推送")
        payload = await service.prepare_latest_payload()
        if isinstance(event, GroupMessageEvent):
            logger.info(f"eraTW test push target is group {event.group_id}")
            await send_payload_to_group(bot, int(event.group_id), payload, plugin_config)
        else:
            logger.info(f"eraTW test push target is private user {event.user_id}")
            await send_payload_to_private(bot, int(event.user_id), payload, plugin_config)
        await matcher.finish(f"eraTW 测试推送完成，已拉取最新 commit：{payload.target_short_sha}")
    except FinishedException:
        raise
    except Exception as exc:
        logger.exception("eraTW test push failed")
        await matcher.finish(f"eraTW 测试推送失败：{exc}")


@pull_latest.handle()
async def _(bot: Bot, event: MessageEvent, matcher: Matcher) -> None:
    try:
        logger.info(f"eraTW manual latest command triggered by user {event.user_id}")
        if not isinstance(event, GroupMessageEvent):
            await matcher.finish("请在目标群内使用 /拉取最新版")
        group_id = int(event.group_id)
        await matcher.send("开始拉取 eraTW 最新版")
        payload = await service.prepare_latest_payload()
        logger.info(f"eraTW manual latest push target is group {group_id}")
        await send_payload_to_group(bot, group_id, payload, plugin_config)
        service.mark_success(payload)
        await matcher.finish(
            f"eraTW 最新版推送完成，last_success_sha 已更新：{payload.target_short_sha}"
        )
    except FinishedException:
        raise
    except Exception as exc:
        logger.exception("eraTW manual latest push failed")
        await matcher.finish(f"eraTW 最新版拉取失败：{exc}")


async def run_scheduled_check() -> None:
    if not plugin_config.eratw_group_ids:
        logger.debug("eraTW scheduled check skipped: group whitelist is empty")
        return
    bots = get_bots()
    if not bots:
        logger.warning("eraTW mirror skipped: no bot is connected")
        return

    bot = next(iter(bots.values()))
    try:
        payload = await service.check_once()
        if payload is None:
            return
        logger.info(
            f"eraTW scheduled payload ready for {payload.target_short_sha}; "
            f"pushing to {len(plugin_config.eratw_group_ids)} groups"
        )
        target_groups = [int(group_id) for group_id in plugin_config.eratw_group_ids]
        uploaded_groups = service.uploaded_groups(payload)
        successful_groups = service.successful_groups(payload)
        pending_groups = [group_id for group_id in target_groups if group_id not in successful_groups]
        if not pending_groups:
            logger.info(
                f"eraTW all groups already received {payload.target_short_sha}; marking success"
            )
            service.mark_success(payload)
            return
        failed_groups: list[int] = []
        for group_id in pending_groups:
            logger.info(f"eraTW scheduled push started for group {group_id}")
            archive = None
            try:
                archive_uploaded = group_id in uploaded_groups
                if not archive_uploaded:
                    archive = await upload_payload_archive_to_group(
                        bot,
                        group_id,
                        payload,
                        plugin_config,
                    )
                    service.mark_group_uploaded(payload, group_id, archive=archive)
                    archive_uploaded = True
                else:
                    logger.info(
                        f"eraTW archive already uploaded to group {group_id}; "
                        "skipping upload and retrying forward message"
                    )
                await send_payload_forward_to_group(
                    bot,
                    group_id,
                    payload,
                    plugin_config,
                    archive_uploaded=archive_uploaded,
                    archive=archive,
                )
            except Exception:
                failed_groups.append(group_id)
                logger.exception(f"eraTW scheduled push failed for group {group_id}")
                continue
            service.mark_group_success(payload, group_id)
            logger.info(f"eraTW scheduled push completed for group {group_id}")
        if failed_groups:
            logger.warning(
                f"eraTW scheduled push left {len(failed_groups)} failed groups for retry: "
                f"{failed_groups}"
            )
            return
        service.mark_success(payload)
    except Exception:
        logger.exception("eraTW scheduled push failed")


if schedule_spec is None:
    logger.info("eraTW scheduled push disabled because eratw_schedule is empty")
else:
    scheduler.add_job(
        run_scheduled_check,
        schedule_spec.trigger,
        id="eratw_mirror_schedule",
        max_instances=1,
        coalesce=True,
        **schedule_spec.trigger_kwargs,
    )
    logger.info(f"eraTW scheduler registered: {schedule_spec.description}")
