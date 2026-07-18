# 本地开发环境检查报告

- 检查时间：2026-07-18 14:24:19 +08:00
- 检查阶段：阶段 0
- 目标环境：Windows 11 + WSL2 + Ubuntu + Docker Desktop + Git + Codex 桌面应用 + GitHub
- 检查原则：不修改业务代码，不安装软件，不修改系统安全设置，不执行管理员权限绕过

## 结论

**当前为“部分通过”，尚未满足全部通过条件。**

基础系统、Git、Codex、计算资源、磁盘以及 GitHub/依赖源网络均正常。以下两项未通过：

1. Docker Desktop 已安装，Windows Docker Engine 可响应，但 Docker Desktop 状态接口显示 `stopped`；Ubuntu 中没有活动的 Docker Desktop WSL 集成挂载，无法运行 `docker` 和 `docker compose`。
2. Ubuntu 当前默认用户为 `root`，系统中没有 UID 1000 的普通 Linux 用户。因此，本次无法证明普通用户可以在不使用管理员权限的情况下运行 Docker。

本阶段没有自动修复上述问题。

## 组件状态与版本

| 组件 | 检查结果 | 状态 |
|---|---|---|
| Windows | Windows 11 专业版，版本 `10.0.26200`，Build `26200`，64 位 | 通过 |
| Windows Hypervisor | `HyperVisorPresent=True`，`CsHypervisorPresent=True` | 通过 |
| WSL | WSL `2.7.10.0`；WSL 内核组件 `6.18.33.2-2` | 通过 |
| 默认 WSL 发行版 | `Ubuntu-26.04`，WSL 版本 2 | 通过 |
| Ubuntu | Ubuntu `26.04 LTS`（Resolute Raccoon），`x86_64` | 通过 |
| Ubuntu 内核 | `6.18.33.2-microsoft-standard-WSL2` | 通过 |
| Codex 桌面应用 | `OpenAI.Codex 26.715.3651.0`，包状态 `Ok` | 通过 |
| Windows Git | `2.55.0.windows.2` | 通过 |
| Ubuntu Git | `2.53.0` | 通过 |
| Docker Desktop | `4.82.0 (233772)`；状态接口显示 `stopped` | 未通过 |
| Docker Client | Windows Client `29.6.1` | 通过 |
| Docker Engine | Linux Engine `29.6.1`，Windows 端 API 可响应 | 通过 |
| Docker Compose | Windows `v5.3.0` | 通过 |
| Ubuntu Docker | WSL 集成挂载不存在，`docker` 不可用 | 未通过 |
| Ubuntu Compose | 因 Ubuntu Docker 集成不可用而不可用 | 未通过 |

## Docker Desktop 与 WSL2 集成

Docker Desktop 用户设置中：

- `EnableIntegrationWithDefaultWslDistro=True`
- `AutoStart=False`
- 默认 WSL 发行版为 `Ubuntu-26.04`

运行时检查中：

- `/mnt/wsl/docker-desktop` 不存在；
- Ubuntu 的 `PATH` 只能找到 Windows Docker 路径；
- 从 Ubuntu 调用 Docker 时返回“Docker command could not be found in this WSL 2 distro”；
- Windows Docker Engine API 仍可响应，并报告 Linux/x86_64 Engine `29.6.1`。

因此，设置值虽然已启用，但 Docker Desktop 当前未完整运行，WSL 集成没有在 Ubuntu 运行时生效。

## 当前用户与权限

### Windows

- 当前 Windows 身份：`DESKTOP-MMBC8P9\Administrator`
- 当前 Codex 进程处于提升权限状态：`IsElevatedAdministrator=True`
- 该 Windows 用户属于本地 `docker-users` 组

本次没有请求或执行额外提权，但由于 Codex 当前进程本身已提升，无法用本次结果证明普通、非提升 PowerShell 会话可以运行 Docker。应在普通 PowerShell 窗口中单独复核。

### Ubuntu

- 当前默认用户：`root`
- 当前身份：`uid=0(root) gid=0(root)`
- 系统中不存在 UID 1000 的普通用户

这不符合日常开发应使用普通 Linux 用户的建议，也不满足“不依赖管理员权限运行 Docker”的验证条件。

## CPU、内存与磁盘

### Windows 主机

| 项目 | 结果 |
|---|---|
| CPU | Intel Core i7-14700K |
| 物理核心 | 20 |
| 逻辑线程 | 28 |
| 总内存 | 63.69 GiB |
| 当前可用内存 | 38.59 GiB |
| C 盘总空间 | 200 GiB |
| C 盘可用空间 | 51.63 GiB（25.8%） |

### WSL / Docker

| 项目 | 结果 |
|---|---|
| WSL 可用线程 | 28 |
| WSL 总内存 | 31 GiB |
| WSL 可用内存 | 约 30 GiB |
| WSL Swap | 8 GiB，当前未使用 |
| Ubuntu 根文件系统可用空间 | 约 955 GiB |
| `/mnt/c` 可用空间 | 约 52 GiB |
| Docker 可见 CPU | 28 |
| Docker 可见内存 | 约 31.19 GiB |

资源不存在明显不足。

## 网络与依赖源

Ubuntu 使用 WSL 自动代理：

- HTTP/HTTPS 代理：`http://127.0.0.1:7897`
- WSL 网络模式：mirrored

| 目标 | 检查方式 | 结果 | 状态 |
|---|---|---|---|
| GitHub Fork | GitHub 连接器读取 `scottfitzgerald294-gif/tgo` | 可访问，当前账号有完整权限 | 通过 |
| GitHub Git HTTPS | `git ls-remote` | 返回 `995da4577f6f91edb87d0f56fc9ea4c129f1a4eb` | 通过 |
| PyPI | `https://pypi.org/pypi/pip/json` | HTTP 200 | 通过 |
| npm Registry | `https://registry.npmjs.org/react/latest` | HTTP 200 | 通过 |
| Docker Registry | `https://registry-1.docker.io/v2/` | HTTP 401（未认证探测的预期响应） | 通过 |
| Go Proxy | `https://proxy.golang.org/github.com/stretchr/testify/@v/list` | HTTP 200 | 通过 |

备注：首次对 PyPI 完整 `/simple/` 索引执行 GET 时，由于响应体约 44 MB，在检查超时窗口内未完成。随后通过 HEAD 请求和小型 JSON 元数据请求确认 DNS、代理、TLS 及 PyPI 访问均正常。

## Git 与当前工作区

- 当前分支：`main`
- 检查开始时工作区干净：`main...origin/main`
- `origin`：`https://github.com/scottfitzgerald294-gif/tgo.git`
- `upstream`：`https://github.com/tgoai/tgo.git`
- 当前目录位于 Windows C 盘，并通过 WSL `v9fs` 挂载

当前项目目录和 TGO 代码是在本阶段之前，根据用户上一阶段的指令创建并克隆的。由于目录与代码已存在，本阶段没有重复创建工作目录，也没有再次克隆、删除或覆盖代码。

## 最安全的处理步骤

以下步骤仅作为建议，本阶段没有执行。

### 1. 恢复 Docker Desktop 的 Ubuntu WSL 集成

1. 使用普通方式启动 Docker Desktop，不选择“以管理员身份运行”。
2. 等待 Docker Desktop 显示 Engine 已运行。
3. 打开 **Settings → General**，确认 **Use the WSL 2 based engine** 已启用。
4. 打开 **Settings → Resources → WSL Integration**：
   - 启用 **Enable integration with my default WSL distro**；
   - 明确启用 `Ubuntu-26.04`。
5. 选择 **Apply & Restart**。
6. 如集成仍未刷新，在普通 PowerShell 中执行 `wsl --shutdown`，再重新打开 Docker Desktop 和 Ubuntu。
7. 在 Ubuntu 中复核：

   ```bash
   docker version
   docker compose version
   docker run --rm hello-world
   ```

不建议同时在 Ubuntu 中另行安装一套 Docker Engine；这可能与 Docker Desktop 的 WSL 集成冲突。

### 2. 创建普通 Ubuntu 用户

先确定希望使用的 Linux 用户名，再进行一次性的正式用户初始化。该操作需要 Ubuntu 的现有 root 身份完成，但它是建立普通用户的必要系统配置，不应作为日常开发绕过权限的手段。

建议由用户手动执行：

```bash
wsl -d Ubuntu-26.04 -u root
adduser <linux-user>
usermod -aG sudo,docker <linux-user>
```

随后在 `/etc/wsl.conf` 中保留现有 `[boot]` 配置，并增加：

```ini
[user]
default=<linux-user>
```

退出 Ubuntu，在普通 PowerShell 中执行：

```powershell
wsl --shutdown
wsl -d Ubuntu-26.04 -- id
```

最后确认输出中的 UID 不为 0，再以该普通用户运行 Docker 验证命令。

### 3. 非提升 Windows 会话复核

在普通、未提升的 PowerShell 窗口中执行：

```powershell
docker version
docker compose version
```

当前 Windows 用户已属于 `docker-users` 组，因此通常不需要管理员权限。如果刚修改过组成员关系，应先注销并重新登录，而不是持续使用提升权限窗口。

## 本阶段变更范围

- 新增本报告：`docs/local-environment-check.md`
- 未修改业务代码
- 未安装软件
- 未修改防火墙、安全软件或系统安全设置
- 未创建新的项目工作目录
- 未克隆或重新克隆代码
