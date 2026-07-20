# 阶段4实施计划：TGO本地基线运行验证

> **执行规范：** 使用 `superpowers:executing-plans` 串行执行本计划；出现错误时使用
> `superpowers:systematic-debugging`，同一错误最多进行两轮根因分析和修复。

## 目标

在不包含任何拼多多定制、真实模型密钥或真实用户数据的前提下，验证当前
Fork中的TGO能够通过官方本地Docker Compose流程在Windows 11、WSL2和
Docker Desktop环境中启动，并验证基础设施、迁移、核心HTTP服务、日志和
重启后的数据状态。

## 基线

- 执行分支：`phase/04-tgo-baseline`
- 起点提交：`a45fddf0249e7b0e7e5ecd14b8e3d945fe5944ca`
- 隔离工作树：`.worktrees/weekend-run`
- 官方本地入口：复制 `.env.dev.example` 为被忽略的 `.env.dev`，再执行
  `make dev`
- 当前Windows Docker Client和Server版本均为`29.6.1`，上下文为
  `desktop-linux`
- TGO预定主机端口在计划创建时没有被占用
- 初始Gitleaks基线为22项既有候选；本阶段不得增加

## 已识别的执行差异

当前WSL Ubuntu缺少`make`、Poetry和Docker集成，但Windows Docker
Client/Server正常。因此本阶段从Windows PowerShell逐条执行根`Makefile`
中`make dev`的等价Docker Compose命令，不安装系统软件，不使用管理员权限，
也不修改防火墙或安全软件。

基础Compose文件为服务声明`.env`，开发Compose文件声明`.env.dev`；Compose
合并后会同时读取两者，而官方快速开始只要求创建`.env.dev`。静态校验已复现
缺少`.env`会失败，因此本阶段创建内容完全相同、同样被Git忽略的`.env`作为
本地兼容文件，不修改两个Compose源文件。

仓库的`.skills/local-services/scripts/start.sh`引用当前根`Makefile`中不存在
的`infra-up`、`migrate`、`dev-api`和`dev-ai`目标，不能作为本阶段启动入口。
`scripts/dev/summary.sh`会输出Postgres密码，本阶段禁止执行或保存其原始输出。

## 明确不做

- 不修改`repos/*`中的TGO核心代码、迁移或业务配置。
- 不实现拼多多连接器、模拟器、消息可靠性、知识或人工转接功能。
- 不访问真实拼多多、生产环境、真实模型服务、付费服务或真实买家数据。
- 不创建管理员、客服、知识库或业务会话；这些浏览器操作只记录为
  `MANUAL_PENDING`。
- 不删除Docker卷、数据库、`data/`目录或失败现场。
- 不执行`docker compose down -v`、`make clean`、`git reset --hard`、
  `git clean -fdx`或任何强制推送。
- 不运行会打印敏感值的`scripts/dev/summary.sh`。

## 准备创建或修改的文件

- 创建被Git忽略的`.env.dev`，仅用于本机基线运行。
- 创建与`.env.dev`内容一致且同样被忽略的`.env`，满足合并后的Compose
  `env_file`要求。
- 创建`docs/runbooks/tgo-local-baseline.md`。
- 创建`docs/weekend-run/phase-04-report.md`。
- 创建`docs/weekend-run/logs/phase-04-validation.md`。
- 本计划之外不应产生任何已跟踪源文件修改。

Docker运行可能在被忽略的`data/`目录中创建本地Postgres、Redis、WuKongIM
和服务上传目录，并创建Compose容器、镜像及命名卷。所有这些状态均保留，
不执行破坏性清理。

## 执行步骤

### 1. 安全生成本地环境文件

读取`.env.dev.example`，用
`System.Security.Cryptography.RandomNumberGenerator.Create()`创建生成器并向
32字节数组填充加密安全随机数，分别生成Postgres密码和`SECRET_KEY`，将二者
编码为十六进制字符串，并同步重建`DATABASE_URL`。所有模型、PDD及其他外部
凭据保持为空。将完成的`.env.dev`原样复制为`.env`。命令不得将任何值写入
标准输出。

验证：

```powershell
git check-ignore -v .env.dev .env
git status --short
```

预期：两个本地环境文件内容哈希一致且均由根`.gitignore`忽略，工作区仍只
包含本计划文档。

### 2. 验证Compose配置和依赖图

```powershell
docker compose --env-file .env.dev -f docker-compose.yml -f docker-compose.dev.yml config --quiet
docker compose --env-file .env.dev -f docker-compose.yml -f docker-compose.dev.yml config --services
```

预期：配置解析成功，服务清单包含Postgres、Redis、WuKongIM、七个迁移服务、
七个后端/worker服务、Web和Widget；不输出环境值。

### 3. 按官方顺序构建后端镜像

依次构建`tgo-rag`、`tgo-ai`、`tgo-api`、`tgo-plugin-runtime`、
`tgo-device-control`、`tgo-platform`和`tgo-workflow`。等价命令统一使用：

```powershell
docker compose --env-file .env.dev -f docker-compose.yml -f docker-compose.dev.yml build <service>
```

预期：每个镜像构建成功；任何服务构建失败都先保存完整错误，再进入最多两轮
根因分析，不跳过该服务。

### 4. 启动并验证基础设施

```powershell
docker compose --env-file .env.dev -f docker-compose.yml -f docker-compose.dev.yml up -d postgres redis wukongim
docker compose --env-file .env.dev -f docker-compose.yml -f docker-compose.dev.yml ps
```

轮询容器健康状态，并分别验证Postgres`pg_isready`、Redis`PING`和
WuKongIM`/health`。预期三个基础设施容器均为healthy。

### 5. 运行全部数据库迁移

按官方`init.sh`顺序逐个执行：

```text
migrate-api
migrate-ai
migrate-rag
migrate-platform
migrate-workflow
migrate-plugin
migrate-device
```

每项使用：

```powershell
docker compose --env-file .env.dev -f docker-compose.yml -f docker-compose.dev.yml run --rm --no-deps <migration-service>
```

预期：七项退出码均为0；Postgres可查询到迁移后的公共表。迁移失败不得通过
修改TGO业务逻辑绕过。

### 6. 启动核心应用

启动根`Makefile`定义的`CORE_APP_SERVICES`：

```text
tgo-rag
tgo-rag-worker
tgo-rag-beat
tgo-ai
tgo-plugin-runtime
tgo-device-control
tgo-platform
tgo-workflow
tgo-workflow-worker
tgo-api
tgo-web
tgo-widget-js
```

预期：必须有健康检查的容器达到healthy；worker和beat保持running且不持续
重启；Web和Widget的HTTP入口可访问。

### 7. HTTP、数据库与日志验证

- 对各服务实际声明的健康端点发起本机HTTP请求并记录状态码。
- 使用Postgres容器内`psql`只读查询连接状态和公共表数量。
- 使用Redis容器内`redis-cli ping`确认连接。
- 读取每个服务最近日志，仅记录服务名、错误等级计数和经过脱敏的错误摘要；
  不保存密码、令牌、环境变量或原始请求负载。
- 检查容器重启次数在观察窗口内不增长。

预期：核心HTTP入口成功，数据库和Redis可连接，日志中无持续崩溃循环。

### 8. 重启与状态保持验证

先记录公共表数量和容器状态，再通过以下非破坏性命令重启当前Compose服务：

```powershell
docker compose --env-file .env.dev -f docker-compose.yml -f docker-compose.dev.yml restart
```

待服务恢复后重新执行容器健康、HTTP、Postgres和Redis检查，并比较公共表数量。
预期：表数量不减少，服务恢复到原有健康/运行状态。

### 9. 人工浏览器步骤

若管理端可访问，则将以下内容记录为`MANUAL_PENDING`：

- 访问`http://localhost:5173`
- 按页面首次启动向导创建本地管理员
- 创建本地测试客服
- 创建仅含`FAKE/TEST`数据的知识库
- 通过本地Widget发送测试消息并验证人工接管

不得声称这些点击步骤已完成，也不得使用浏览器保存的账号信息代替用户操作。

### 10. 阶段验收、报告和Git

执行：

```powershell
git diff --check
git diff --name-only phase-02-complete..HEAD -- repos
git status --short
```

重新执行Gitleaks只读扫描并确认候选总数不超过22；只记录数量和路径，不记录
候选值。创建运行手册、阶段报告和脱敏验证日志。

只有以下项目全部满足才记录阶段4为`PASS`：

- 必要容器正常；
- 核心服务健康接口正常；
- 数据库连接和迁移正常；
- 非破坏性重启后状态恢复且数据结构保持；
- 日志没有持续崩溃；
- 浏览器步骤明确标为`MANUAL_PENDING`；
- `repos/*`修改为0；
- Gitleaks候选没有增加。

通过后提交`docs: record verified tgo local baseline`，创建不覆盖既有标签的
`phase-04-complete`，并推送阶段分支和标签到`origin`。若任一自动验收未通过，
阶段4记录为`FAIL`并停止阶段5至阶段8。
