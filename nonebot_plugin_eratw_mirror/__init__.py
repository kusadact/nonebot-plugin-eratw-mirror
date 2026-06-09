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
from .message import send_payload_to_group, send_payload_to_private
from .mirror import MirrorService

__plugin_meta__ = PluginMetadata(
    name="eraTW Mirror",
    description="搬运 GitGud eraTW 更新归档和开发日志",
    usage="/eratw测试推送",
    type="application",
    config=Config,
    supported_adapters={"~onebot.v11"},
)

service = MirrorService(plugin_config)

logger.info(
    "eraTW mirror plugin loaded: "
    f"branch={plugin_config.eratw_branch}, "
    f"poll_interval={plugin_config.eratw_poll_interval}, "
    f"groups={plugin_config.eratw_group_ids}, "
    f"proxy={'configured' if plugin_config.eratw_proxy else 'none'}"
)

if plugin_config.eratw_poll_interval > 0:
    logger.info(
        f"eraTW scheduler registered with interval {plugin_config.eratw_poll_interval} seconds"
    )

    @scheduler.scheduled_job(
        "interval",
        seconds=plugin_config.eratw_poll_interval,
        id="eratw_mirror_poll",
        max_instances=1,
        coalesce=True,
    )
    async def _scheduled_check() -> None:
        await run_scheduled_check()


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
