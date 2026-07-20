# 阶段4验证日志

- 日期：2026-07-18
- 时区：Asia/Shanghai
- 分支：`phase/04-tgo-baseline`
- 起点提交：`a45fddf0249e7b0e7e5ecd14b8e3d945fe5944ca`
- Docker上下文：`desktop-linux`

## 起始审计

| 检查 | 结果 |
|---|---|
| 隔离工作树 | PASS：`.worktrees/weekend-run` |
| 当前分支 | PASS：`phase/04-tgo-baseline` |
| 起始跟踪工作区 | PASS：干净 |
| 阶段3测试 | PASS：2项通过 |
| 阶段3后`repos/*`修改 | PASS：0个文件 |
| 潜在真实用户数据文件 | PASS：0个 |
| Gitleaks起始基线 | PASS：22项既有候选 |

直接执行`poetry run pytest`时出现`ModuleNotFoundError: app`；项目统一命令实际
使用`poetry run python -m pytest`。使用官方入口后2项测试通过，因此该问题
属于测试入口差异，不是代码回归，没有修改代码。

## 本地环境和Compose

| 检查 | 结果 |
|---|---|
| Docker Client | PASS：`29.6.1` |
| Docker Server | PASS：`29.6.1` |
| Docker Compose | PASS：`v5.3.0` |
| `.env.dev` | PASS：随机本地密码和密钥，不输出值 |
| `.env` | PASS：与`.env.dev`哈希一致 |
| Git忽略 | PASS：两个环境文件均被忽略 |
| Compose静态配置 | PASS：退出码0 |
| Compose服务清单 | PASS：23个服务 |

首次仅创建`.env.dev`时，Compose静态检查报告缺少`.env`。原因是基础Compose
与开发Compose合并后保留两个`env_file`。创建内容相同且被忽略的`.env`后，
静态检查通过；没有修改Compose源文件。

## 构建

| 检查 | 结果 |
|---|---|
| 第一次构建 | FAIL：Docker Hub认证服务IPv6连接超时 |
| 网络根因检查 | Windows使用`127.0.0.1:7897`代理；Docker使用内部代理 |
| 安全处理 | 未修改系统或Docker Desktop设置 |
| 基础镜像单次重试 | PASS：`python:3.11-slim`拉取成功 |
| 第二次完整构建 | PASS：7个后端镜像全部构建 |
| 第二次构建失败行 | PASS：0行 |

首轮和第二轮完整日志保存在被忽略的`data/weekend-run/phase-04/`。

## 基础设施

| 服务 | 容器状态 | 实际检查 |
|---|---|---|
| Postgres | healthy | `pg_isready`接受连接 |
| Redis | healthy | `PONG` |
| WuKongIM | healthy | `GET /health`返回200 |

## 迁移

| 迁移服务 | 退出码 |
|---|---|
| `migrate-api` | 0 |
| `migrate-ai` | 0 |
| `migrate-rag` | 0 |
| `migrate-platform` | 0 |
| `migrate-workflow` | 0 |
| `migrate-plugin` | 0 |
| `migrate-device` | 0 |

迁移日志先替换随机本地密码和`SECRET_KEY`，再保存到被忽略的本地日志目录。

## 容器和HTTP

15个已启动容器均为healthy，重启计数均为0。

| 入口 | 启动后 | 重启后 |
|---|---:|---:|
| WuKongIM | 200 | 200 |
| TGO API | 200 | 200 |
| TGO AI | 200 | 200 |
| TGO RAG | 200 | 200 |
| TGO Platform | 200 | 200 |
| TGO Workflow | 200 | 200 |
| TGO Plugin Runtime | 200 | 200 |
| TGO Device Control | 200 | 200 |
| TGO Web | 200 | 200 |
| TGO Widget | 200 | 200 |

## 重启和状态保持

| 检查 | 重启前 | 重启后 |
|---|---|---|
| Compose命令退出码 | 不适用 | 0 |
| healthy容器 | 15 | 15 |
| Postgres公共表数 | 72 | 72 |
| 表名集合指纹 | `8f8b4c44fc9ae82d6a808bfb7e335a19` | `8f8b4c44fc9ae82d6a808bfb7e335a19` |
| Redis | `PONG` | `PONG` |

没有停止或删除数据卷、数据库或`data/`目录。

## 日志和敏感数据

| 检查 | 结果 |
|---|---|
| 首次启动错误行 | 2项一次性初始化错误 |
| 稳定窗口错误行 | 0 |
| 重启后稳定窗口错误行 | 0 |
| 持续崩溃 | 0个容器 |
| 原始日志本地密码匹配 | 1处，位于`tgo-rag`启动摘要 |
| 保存的日志副本 | 已脱敏为`[REDACTED]` |
| 真实PDD/模型/用户凭据 | 0 |

没有运行会直接打印Postgres密码的`scripts/dev/summary.sh`。

## Gitleaks最终门禁

直接扫描整个工作目录得到63项候选，因为`--no-git`把被Git忽略的`.env`、
`.env.dev`和Redis AOF运行数据也纳入扫描。没有删除这些运行现场。

随后从`HEAD`受控文件创建只读快照，并加入本阶段4份待提交文档后重新扫描：

- 候选总数：22
- 与阶段起点基线差异：0
- 本阶段新增候选：0
- 候选值输出：0

该快照和扫描现场保存在被忽略的`data/weekend-run/phase-04/`。

## MANUAL_PENDING

`GET /v1/setup/status`返回：

- `is_installed=false`
- `has_admin=false`
- `has_user_staff=false`
- `has_llm_config=false`

`/setup`、`/login`和Widget`/demo.html`均返回200。管理员、客服、知识库、聊天
和人工接管的浏览器操作尚未执行，详细步骤见
`docs/runbooks/tgo-local-baseline.md`。
