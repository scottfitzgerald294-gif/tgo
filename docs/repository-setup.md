# 仓库与分支设置

- 设置日期：2026-07-18
- 官方仓库：`tgoai/tgo`
- 用户 Fork：`scottfitzgerald294-gif/tgo`
- 阶段：阶段 1（安全仓库与分支结构）
- 基线提交：`995da4577f6f91edb87d0f56fc9ea4c129f1a4eb`

## 远程仓库职责

| 名称 | 地址 | 用途 | 写入策略 |
|---|---|---|---|
| `origin` | `https://github.com/scottfitzgerald294-gif/tgo.git` | 用户 Fork，用于保存项目分支和阶段标签 | 允许推送项目分支和标签 |
| `upstream` | `https://github.com/tgoai/tgo.git` | 官方 TGO 仓库，用于获取官方更新 | 只读取，不推送 |

核对命令：

```bash
git remote -v
git remote get-url origin
git remote get-url upstream
```

## 分支策略

```text
upstream/main
  └─ pdd-customer-service
       └─ phase/01-repository-setup
            ├─ docs: record phase 0 environment check
            └─ chore: establish phase 01 repository setup
       └─ merge: complete phase 01 repository setup
            └─ phase-01-complete
```

- `main`：保留官方默认分支内容，不直接提交阶段变更。
- `pdd-customer-service`：项目集成分支，只接收已经检查的阶段分支。
- `phase/01-repository-setup`：阶段 1 工作分支，仅包含环境报告、仓库文档和安全忽略规则。
- `phase-01-complete`：阶段 1 完成后，在集成分支合并提交上创建的附注标签。
- 项目分支和标签只推送到 `origin`，绝不推送到 `upstream`。
- 禁止对共享分支和已发布标签使用强制推送或强制替换。

## 提交与合并流程

阶段分支使用明确路径暂存，避免误收录其他文件：

```bash
git switch phase/01-repository-setup
git add docs/local-environment-check.md
git commit -m "docs: record phase 0 environment check"

git add .gitignore docs/repository-setup.md
git commit -m "chore: establish phase 01 repository setup"
git push origin phase/01-repository-setup
```

合并到项目集成分支时保留阶段边界：

```bash
git switch pdd-customer-service
git merge --no-ff phase/01-repository-setup -m "merge: complete phase 01 repository setup"
git push origin pdd-customer-service
git tag -a phase-01-complete -m "Phase 01 repository setup complete"
git push origin phase-01-complete
```

## 获取并合并官方更新

先获取远程引用并查看差异，不直接修改官方分支：

```bash
git fetch --prune origin
git fetch --prune upstream
git log --oneline --left-right pdd-customer-service...upstream/main
```

确认更新范围后，在集成分支合并官方更新：

```bash
git switch pdd-customer-service
git status --short --branch
git merge --no-ff upstream/main -m "merge: sync upstream main"
git push origin pdd-customer-service
```

如果合并发生冲突且尚未提交，使用下面的命令退出本次合并，再分析冲突：

```bash
git merge --abort
```

## 安全回滚

优先使用保留历史的回滚方式，不改写共享历史。

保存当前未提交工作后再排查：

```bash
git stash push --include-untracked -m "safety snapshot before rollback"
git stash list
```

撤销尚未提交的暂存操作但保留文件内容：

```bash
git restore --staged <path>
```

撤销已经提交并推送的普通提交：

```bash
git switch pdd-customer-service
git revert <commit>
git push origin pdd-customer-service
```

撤销已经提交并推送的阶段合并：

```bash
git switch pdd-customer-service
git revert -m 1 <merge-commit>
git push origin pdd-customer-service
```

从阶段标签创建恢复分支，不移动现有分支或标签：

```bash
git switch -c recovery/phase-01 phase-01-complete
```

不要使用 `git reset --hard`、强制推送或覆盖已有标签作为共享仓库的回滚方式。

## 敏感文件保护

根目录 `.gitignore` 覆盖以下本地文件：

- `.env` 及 `.env.*` 本地环境文件，同时保留 `*.example` 模板；
- 私钥、证书、密钥库和常见凭据文件或目录；
- 日志、轮转日志、缓存和依赖目录；
- SQLite、本地数据库及其 journal、WAL、SHM 辅助文件。

提交前仍需检查暂存区，防止已经被 Git 跟踪的文件绕过忽略规则：

```bash
git status --short
git diff --cached --name-only
git diff --cached
```

## 验收命令

```bash
git remote -v
git branch --all --list
git show-ref --verify refs/tags/phase-01-complete
git log --oneline --decorate --graph -10
git status --short --branch
```
