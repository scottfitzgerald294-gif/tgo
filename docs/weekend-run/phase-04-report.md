# 阶段4报告：TGO本地基线

## 状态

`PASS`，浏览器首次初始化与登录人工验收已完成。

未经拼多多定制的TGO已在当前Windows Docker Desktop环境中完成构建、迁移、
启动、HTTP验证和非破坏性重启验证。自动化基线满足进入阶段5的门禁。

## Git

- 起点分支：`phase/03-governance`
- 起点提交：`a45fddf0249e7b0e7e5ecd14b8e3d945fe5944ca`
- 阶段分支：`phase/04-tgo-baseline`
- 预计提交：`docs: record verified tgo local baseline`
- 预计标签：`phase-04-complete`
- `main`、`master`和上游稳定分支未修改

## 本地运行方式

- Docker Client/Server：`29.6.1`
- Docker Compose：`v5.3.0`
- Docker上下文：`desktop-linux`
- Compose服务数：23
- 后端镜像：7个本地构建成功
- 当前运行容器：15个，全部healthy
- 当前容器重启计数：全部为0

当前WSL缺少`make`和Docker集成，因此使用Windows Docker Client逐项执行
根`Makefile`的等价流程。没有安装系统软件，没有使用管理员权限，也没有修改
防火墙、安全软件、系统代理或Docker Desktop设置。

## 环境文件

- `.env.dev`使用随机本地Postgres密码和随机`SECRET_KEY`。
- `.env`与`.env.dev`内容一致，用于满足Compose合并后的基础`env_file`。
- 两个文件均被Git忽略。
- 没有配置真实PDD、模型或生产凭据。

## 构建

第一次构建在访问Docker Hub认证服务时遇到暂时性IPv6连接超时。Windows通过
本机代理访问外网，而Docker守护进程使用Docker Desktop内部代理。没有修改
任何系统设置；保存首轮日志后，单独重试拉取`python:3.11-slim`成功，第二轮
完整构建成功。

成功构建：

- `tgo-rag`
- `tgo-ai`
- `tgo-api`
- `tgo-plugin-runtime`
- `tgo-device-control`
- `tgo-platform`
- `tgo-workflow`

## 迁移

以下7项迁移退出码均为0：

- `migrate-api`
- `migrate-ai`
- `migrate-rag`
- `migrate-platform`
- `migrate-workflow`
- `migrate-plugin`
- `migrate-device`

迁移后Postgres公共表数量为72。

## 运行和HTTP验证

以下入口在启动后及非破坏性重启后均返回HTTP 200：

- WuKongIM
- TGO API
- TGO AI
- TGO RAG
- TGO Platform
- TGO Workflow
- TGO Plugin Runtime
- TGO Device Control
- TGO Web
- TGO Widget

Redis在两次检查中均返回`PONG`。重启前后Postgres公共表数量均为72，表名集合
指纹均为`8f8b4c44fc9ae82d6a808bfb7e335a19`，数据库结构状态得到保持。

## 日志审计

- 首次启动出现2条一次性错误：数据库创建前的Postgres探测，以及WuKongIM
  首次没有`wk.yaml`。
- 稳定窗口内错误行数为0。
- 非破坏性重启后的稳定窗口内错误行数为0。
- 所有容器重启计数均为0，没有持续崩溃循环。
- `tgo-rag`原始启动日志出现1处本地随机Postgres密码。保存到项目的日志副本
  已替换为`[REDACTED]`，跟踪文档没有包含该值。
- `scripts/dev/summary.sh`会主动打印Postgres密码，本阶段没有执行。

日志中的本地随机值不是生产或用户凭据，但它证明上游运行日志存在敏感配置
回显风险。阶段4禁止修改TGO核心，故将其记录为后续最小化核心修复候选，不在
本阶段绕过。

## 人工验收结果

`PASS`

用户已在 `http://localhost:5173/setup` 完成以下人工验收：

- 完成TGO首次初始化；
- 创建本地管理员 `admin` 并成功登录；
- 创建本地测试客服 `agent01`（显示名：测试客服01）并成功登录；
- 在模型配置步骤选择“跳过”，未填写模型密钥；
- 确认本地工作台可以正常访问；
- 确认测试客服权限隔离正常；
- 确认暂停接待、状态持久化和恢复接待正常；
- 确认15个TGO核心容器均为 `healthy`。

初始化前自动状态接口记录的
`is_installed=false`、`has_admin=false`、`has_user_staff=false` 和
`has_llm_config=false` 属于人工初始化前的历史状态。

## 核心代码、依赖和数据

- `repos/*`业务代码修改：0个文件
- 新增项目依赖：无
- 新增数据库迁移：无
- 真实PDD调用：无
- 真实模型调用：无
- 真实用户数据：无
- Docker数据删除：无

Docker创建的本地镜像、容器、网络、`data/`内容和命名卷均保留。

## 安全

- 阶段起点Gitleaks基线：22项既有候选
- 受控源码快照最终扫描：22项既有候选，新增0项
- 整个工作目录扫描：63项；增加项来自被忽略的`.env`、`.env.dev`和Redis
  运行数据，不属于可提交源码，现场已保留
- 候选值从未输出到对话或跟踪文档
- `.env`和`.env.dev`保持忽略
- 本阶段跟踪文件不包含真实密钥或用户数据

## 回滚

代码和文档回滚应在阶段提交产生后使用：

```bash
git revert <phase-04-commit>
```

仅停止本地容器且保留数据：

```powershell
docker compose --env-file .env.dev -f docker-compose.yml -f docker-compose.dev.yml down --remove-orphans
```

禁止添加`-v`，禁止删除`data/`。

## 下一阶段门禁

允许进入阶段5。阶段5只实现本地PDD模拟器、合成消息和固定回复，不得调用真实
拼多多、真实模型或生产服务。
