<div align="center">
  <a href="https://v2.nonebot.dev/store">
    <img src="https://raw.githubusercontent.com/fllesser/nonebot-plugin-template/refs/heads/resource/.docs/NoneBotPlugin.svg" width="310" alt="logo">
  </a>

## ✨ nonebot-plugin-eratw-mirror ✨

</div>

GitGud eraTW 魔改仓库更新搬运插件。

插件会按定时计划检查 GitGud 项目 `era-games-zh/touhou/eratw-sub-modding` 的主仓库：

1. 比较当前 commit 和本地保存的 `last_success_sha`。
2. 用 GitLab compare API 补齐两次推送间隔内的所有 commit。
3. 使用 dulwich 在插件 data 目录维护本地 Git 缓存，fetch 最新 commit，并导出到临时工作目录。
4. 使用 py7zr 本地重新打包为仅存储、带密码、隐藏文件列表的 7z。
5. 提取 `魔改版更新记录文档/补丁&readme集/ADD_BANQUET_开发日志.md` 在本次更新中的新增内容。
6. 上传 7z 群文件，并发送合并转发消息。

## 分支选择

主分支适合由 Bot 服务器本地完成拉取源码和打包压缩的部署方式。

如果你希望把拉取源码、打包压缩放到另一台机器或容器上，可以使用 [worker 分支](https://github.com/kusadact/nonebot-plugin-eratw-mirror/tree/feat/pack-worker)。

## 安装

在 NoneBot 项目目录中安装插件：

```bash
uv add git+https://github.com/kusadact/nonebot-plugin-eratw-mirror.git --branch main
```

在 `pyproject.toml` 中加载插件：

```toml
[tool.nonebot]
plugins = ["nonebot_plugin_eratw_mirror"]
```

## 配置

在 NoneBot `.env` 中配置：

| 配置项 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `eratw_group_ids` | 否 | `[]` | 自动推送群白名单；为空时不会自动推送。 |
| `eratw_schedule` | 否 | `daily@04:00` | 定时检查规则；留空关闭自动推送。支持 `daily@HH:MM`、`weekly@mon,thu@HH:MM`、`interval_days@2@HH:MM`。 |
| `eratw_schedule_timezone` | 否 | `Asia/Shanghai` | 定时任务时区。 |
| `eratw_proxy` | 否 | 空 | GitGud API 和 Git 拉取使用的代理，例如 `http://127.0.0.1:7890`。 |
| `eratw_archive_password` | 否 | `eratoho` | 生成 7z 压缩包时使用的密码。 |
| `eratw_timeout` | 否 | `3600` | 超时时间，单位秒；用于 Git 拉取/导出和群文件上传 API 等长耗时操作。 |
| `API_TIMEOUT` | 建议 | `3600` | NoneBot/适配器全局 API 超时，不是本插件配置项；建议填写并与 `eratw_timeout` 保持一致，不填写时大文件上传容易被默认超时提前中断。 |
| `eratw_file_base_url` | 条件 | 空 | 群文件上传使用的临时 HTTP 下载基址；Bot 和 OneBot/NapCat 不在同一个文件系统时必须配置，例如 `http://nonebot:8088`。 |

`example.env`:

```dotenv
eratw_group_ids=[123456789, 987654321]
eratw_schedule="daily@04:00"
eratw_proxy="http://your.proxy.address:port"
eratw_archive_password="eratoho"
eratw_timeout=3600
API_TIMEOUT=3600
eratw_file_base_url="http://nonebot:8088"
```

## 指令

```text
/eratw测试推送
```

仅限 SuperUser 使用。优先重发最近一次已生成的推送；如果没有历史推送，就拉取最新 commit，生成压缩包，并发送测试合并转发消息。测试命令不会更新 `last_success_sha`。

## 部署注意

大文件上传时，OneBot API 调用会长时间不返回。插件默认用 `eratw_timeout=3600` 等待 Git 操作和 `upload_group_file`；同时建议在 `.env` 里填写 `API_TIMEOUT=3600`，否则 NoneBot 或适配器的全局 API 超时可能先断开，导致上传失败。

## 使用

<img src="./.docs/usage-push.jpeg" width="420" alt="测试推送与群文件上传">

<img src="./.docs/usage-forward.png" width="420" alt="合并转发消息内容">
