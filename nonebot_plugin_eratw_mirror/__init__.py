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

from .config import Config, plugin_config
from .file_server import register_archive_file_route
from .message import send_payload_to_group, send_payload_to_private
from .mirror import MirrorService
from .schedule import parse_schedule

__plugin_meta__ = PluginMetadata(
    name="eraTW Mirror",
    description="搬运 GitGud eraTW 更新归档和开发日志",
    usage="/eratw测试推送",
    type="application",
    config=Config,
    supported_adapters={"~onebot.v11"},
)

service = MirrorService(plugin_config)
register_archive_file_route(plugin_config)
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


@test_push.handle()
async def _(bot: Bot, event: MessageEvent, matcher: Matcher) -> None:
    try:
        logger.info(f"eraTW test push command triggered by user {event.user_id}")
        await matcher.send("开始准备 eraTW 测试推送")
        payload, from_cache = await service.prepare_test_payload()
        if isinstance(event, GroupMessageEvent):
            logger.info(f"eraTW test push target is group {event.group_id}")
            await send_payload_to_group(bot, int(event.group_id), payload, plugin_config)
        else:
            logger.info(f"eraTW test push target is private user {event.user_id}")
            await send_payload_to_private(bot, int(event.user_id), payload, plugin_config)
        source = "历史缓存" if from_cache else "最新 commit"
        await matcher.finish(f"eraTW 测试推送完成，来源：{source}")
    except FinishedException:
        raise
    except Exception as exc:
        logger.exception("eraTW test push failed")
        await matcher.finish(f"eraTW 测试推送失败：{exc}")


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
        for group_id in plugin_config.eratw_group_ids:
            logger.info(f"eraTW scheduled push started for group {group_id}")
            await send_payload_to_group(bot, int(group_id), payload, plugin_config)
            logger.info(f"eraTW scheduled push completed for group {group_id}")
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
