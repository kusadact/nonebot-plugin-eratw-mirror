# nonebot-plugin-eratw-mirror

GitGud eraTW 魔改仓库更新搬运插件。

插件会定时轮询 GitGud 项目 `era-games-zh/touhou/eratw-sub-modding` 的指定分支：

1. 比较当前 commit 和本地保存的 `last_success_sha`。
2. 用 GitLab compare API 补齐轮询间隔内的所有 commit。
3. 下载当前 commit 的官方源码 zip 归档。
4. 本地重新打包为仅存储、带密码、隐藏文件列表的 7z。
5. 提取 `魔改版更新记录文档/补丁&readme集/ADD_BANQUET_开发日志.md` 在本次更新中的新增内容。
6. 上传 7z 群文件，并发送合并转发消息。

## 配置

在 NoneBot `.env` 中配置：

```bash
# 自动推送群白名单。为空时不会自动推送。
eratw_group_ids=[123456789]

# 轮询间隔，单位秒。<=0 时关闭自动轮询。
eratw_poll_interval=1800

# 可选代理，例如 http://127.0.0.1:7890
eratw_proxy=""

# 7z 密码，默认 eratoho
eratw_archive_password="eratoho"

# 7z/7zz/7za 路径。为空时自动查找。
eratw_7z_path=""

# 合并转发节点展示 QQ 和昵称
eratw_node_user_id=2854196310
eratw_node_nickname="eraTW 更新"
```

## 指令

```text
/eratw测试推送
```

仅限 SuperUser。优先重发最近一次已生成的推送；如果没有历史推送，就拉取最新 commit，生成压缩包，并发送测试合并转发消息。测试命令不会更新 `last_success_sha`。

## 消息结构

合并转发消息按如下节点构造：

```text
消息1: commit 标题 1
消息2: commit 标题 2
...
消息x: 加密压缩包信息
消息x+1: 本次更新的开发日志
```

压缩包会先作为群文件上传。合并转发中的压缩包节点包含文件名、大小、SHA256 和密码。

