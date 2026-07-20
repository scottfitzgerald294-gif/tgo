# TGO本地Docker基线运行手册

## 适用范围

本手册用于当前Fork在Windows 11、WSL2和Docker Desktop上的本地开发基线。
它不包含真实拼多多接入、真实模型、生产部署或真实业务数据。

仓库官方入口是：

```bash
cp .env.dev.example .env.dev
make dev
```

当前WSL没有`make`和Docker集成，因此已使用Windows Docker Client逐项执行根
`Makefile`的等价命令。不要运行`.skills/local-services/scripts/start.sh`：
该脚本引用的`infra-up`、`migrate`、`dev-api`和`dev-ai`目标在当前
`Makefile`中不存在。

## 本地环境文件

本机存在两个被Git忽略的文件：

- `.env.dev`：官方开发Compose使用的环境文件；
- `.env`：基础Compose与开发Compose合并后仍会读取的兼容文件。

两者内容应完全相同。Postgres密码和`SECRET_KEY`必须是本机随机值。不得填入
真实PDD凭据、真实模型Key或生产配置，也不得提交这两个文件。

验证方式：

```powershell
git check-ignore -v .env.dev .env
```

不要执行`scripts/dev/summary.sh`。该脚本会把Postgres密码打印到终端。

## Compose命令前缀

以下各节中的`docker compose`均使用同一组文件：

```powershell
docker compose --env-file .env.dev -f docker-compose.yml -f docker-compose.dev.yml
```

静态检查：

```powershell
docker compose --env-file .env.dev -f docker-compose.yml -f docker-compose.dev.yml config --quiet
docker compose --env-file .env.dev -f docker-compose.yml -f docker-compose.dev.yml config --services
```

当前配置应解析出23个服务。开发流程不会启动生产`nginx`，因为它不在根
`Makefile`的`CORE_APP_SERVICES`中。

## 首次构建

```powershell
$env:COMPOSE_PARALLEL_LIMIT = "1"
$env:BUILDKIT_PROGRESS = "plain"
docker compose --env-file .env.dev -f docker-compose.yml -f docker-compose.dev.yml build `
  tgo-rag tgo-ai tgo-api tgo-plugin-runtime tgo-device-control tgo-platform tgo-workflow
```

若公开镜像源暂时不可达，先保存错误并检查网络。不要修改防火墙、系统代理或
Docker Desktop安全设置来绕过问题。同一错误最多分析和重试两轮。

## 启动顺序

### 1. 基础设施

```powershell
docker compose --env-file .env.dev -f docker-compose.yml -f docker-compose.dev.yml up -d `
  postgres redis wukongim
```

等待`postgres`、`redis`和`wukongim`均为healthy后再迁移：

```powershell
docker compose --env-file .env.dev -f docker-compose.yml -f docker-compose.dev.yml ps
```

### 2. 数据库迁移

按以下顺序分别执行；每一项必须退出码为0：

```powershell
docker compose --env-file .env.dev -f docker-compose.yml -f docker-compose.dev.yml run --rm --no-deps migrate-api
docker compose --env-file .env.dev -f docker-compose.yml -f docker-compose.dev.yml run --rm --no-deps migrate-ai
docker compose --env-file .env.dev -f docker-compose.yml -f docker-compose.dev.yml run --rm --no-deps migrate-rag
docker compose --env-file .env.dev -f docker-compose.yml -f docker-compose.dev.yml run --rm --no-deps migrate-platform
docker compose --env-file .env.dev -f docker-compose.yml -f docker-compose.dev.yml run --rm --no-deps migrate-workflow
docker compose --env-file .env.dev -f docker-compose.yml -f docker-compose.dev.yml run --rm --no-deps migrate-plugin
docker compose --env-file .env.dev -f docker-compose.yml -f docker-compose.dev.yml run --rm --no-deps migrate-device
```

### 3. 核心应用

```powershell
docker compose --env-file .env.dev -f docker-compose.yml -f docker-compose.dev.yml up -d `
  tgo-rag tgo-rag-worker tgo-rag-beat tgo-ai tgo-plugin-runtime `
  tgo-device-control tgo-platform tgo-workflow tgo-workflow-worker `
  tgo-api tgo-web tgo-widget-js
```

首次启动Web和Widget时会在命名卷中安装前端依赖。等待全部服务healthy后再
验证页面。

## 状态和健康检查

```powershell
docker compose --env-file .env.dev -f docker-compose.yml -f docker-compose.dev.yml ps
```

已验证的本地入口：

| 组件 | 地址 |
|---|---|
| 管理端 | `http://localhost:5173` |
| 首次安装 | `http://localhost:5173/setup` |
| 登录 | `http://localhost:5173/login` |
| Widget演示 | `http://localhost:5174/demo.html` |
| TGO API | `http://localhost:8000/health` |
| TGO AI | `http://localhost:8081/health` |
| TGO RAG | `http://localhost:18082/health` |
| Platform | `http://localhost:8003/health` |
| Workflow | `http://localhost:8004/health` |
| Plugin Runtime | `http://localhost:8090/health` |
| Device Control | `http://localhost:8085/health` |
| WuKongIM | `http://localhost:5001/health` |

Redis可在容器内执行`redis-cli ping`，预期返回`PONG`。Postgres只应使用
`.env.dev`中的本地用户名和数据库名进行只读验证，不在终端回显密码。

## 日志

查看单项最近日志：

```powershell
docker compose --env-file .env.dev -f docker-compose.yml -f docker-compose.dev.yml logs --since 10m <service>
```

不要直接复制或公开原始日志。当前`tgo-rag`启动日志会打印包含本地Postgres
密码的数据库URL；保存证据前必须把密码替换为`[REDACTED]`。本阶段跟踪的验证
文档没有保存该值。

首次创建数据目录时可能看到两条一次性启动错误：

- Postgres在数据库创建完成前收到一次默认数据库探测；
- WuKongIM首次启动时找不到尚未生成的`wk.yaml`。

它们只在初始化瞬间出现。若稳定窗口内重复出现、容器重启计数增长或健康状态
下降，应按失败处理，不得忽略。

## 重启、停止和数据保护

非破坏性重启：

```powershell
docker compose --env-file .env.dev -f docker-compose.yml -f docker-compose.dev.yml restart
```

停止并移除容器和网络、保留所有数据：

```powershell
docker compose --env-file .env.dev -f docker-compose.yml -f docker-compose.dev.yml down --remove-orphans
```

禁止使用：

```text
docker compose down -v
make clean
docker volume prune
docker system prune -a
```

Postgres、Redis和WuKongIM数据位于被忽略的`data/`目录；前端依赖和插件套接字
使用命名卷。不得删除这些目录或卷。

## MANUAL_PENDING：首次浏览器初始化

当前自动检查确认系统尚未安装，管理员、客服和模型配置均不存在。以下步骤必须
由用户亲自在浏览器完成：

1. 打开`http://localhost:5173/setup`。
2. 第1步使用固定用户名`admin`，设置用户自行保管的密码。密码至少8位，并包含
   小写字母、大写字母和数字。
3. 第2步点击“添加客服”，至少创建一个本地测试客服。登录名为4至50位英文字母
   或数字，填写显示名，并设置至少8位的独立密码。
4. 第3步选择不配置模型或点击“跳过”。不得输入真实模型API Key。
5. 第4步确认数据库、管理员和跳过模型的校验结果，再点击“完成”。
6. 页面转到`http://localhost:5173/login`后，以`admin`和刚才设置的密码登录。
7. 如需继续人工验收，在`/knowledge`只创建标记为`FAKE/TEST`的知识库；在
   `http://localhost:5174/demo.html`发送合成测试消息，再到`/chat`观察会话。

这些步骤尚未执行，状态为`MANUAL_PENDING`。不要在聊天、文档、提交或日志中
记录用户选择的密码。
