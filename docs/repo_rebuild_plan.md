# 仓库重建方案（待拍板）

> 背景：本地 + 远端 git 对象损坏（git fsck 报大量 missing commit/tree/blob，`git status` 无法解析 ref）。
> 经恢复，6 处 git 事故丢失代码已全部重建并验证通过。本文件给出"如何把当前干净工作树重建成可信仓库"的三条路径，供你拍板后执行。

---

## 0. 安全备份（已执行 ✅）

- 路径：`/e/newai/_bkp_recovery_20260828/`（57M）
- 范围：当前工作树全量，**排除** `.git/` `venv/` `data/`（2.8G，gitignored，部署时原地保留）`__pycache__/` `*.pyc` `*.log`
- 校验：6 处重建文件齐全（intent 147 / memory_profiles 163 / mcp_client 88 / harness 2091 / llm 464 / 50q 226 行），且目录内无 `.git`
- 作用：**任何重建操作前已有可还原副本**，呼应事故教训"执行 git 操作前先 cp 备份"

---

## 1. 现状确认

| 项 | 结果 |
|---|---|
| `git fsck --full` | 多个 missing commit/tree/blob（本地历史损坏不可逆） |
| `git status` | `fatal: bad revision` —— ref 无法解析 |
| remote | `git@github.com:henryguo017/huawei-cloud-solution-matcher.git`（分支 `main`） |
| `users.db` | 被 `.gitignore` 覆盖（line 238 "All SQLite database files"）→ 不进仓库 |
| `api/data/`（含 92M 嵌入模型） | 被 `.gitignore` 覆盖（line 245 `api/data/`）→ 不进仓库 |
| `data/`（2.8G 向量库） | 被 `.gitignore` 覆盖 → 不进仓库 |
| 6 处重建代码 | 已验证：intent 路由 50/50、`_need_clarify` 判定正确、`api.main:app` 98 routes |

**结论**：当前工作树（排除 `.git`）本身就是一份"干净源码状态"，重建出的新仓库体积小、不含大文件与敏感库。

---

## 2. 三条重建路径（推荐 A）

### A. 以干净工作树为基线重建新仓库【推荐 · 最干净 · 可逆】

步骤（全部可逆，最后一步才涉及强推）：
1. 新建干净目录 `E:/newai/hcsm_rebuilt/`
2. 从备份 `/e/newai/_bkp_recovery_20260828/` 复制工作树
3. `git init` → `git add -A`（`.gitignore` 自动排除 venv/data/api/data/*.db/__pycache__）
4. `git commit -m "chore: rebuild from clean working tree (recovered from corrupt repo)"`
5. `git remote add origin git@github.com:henryguo017/huawei-cloud-solution-matcher.git`
6. `git push -u origin rebuilt-main`  ← **先推到新分支，不覆盖 main**
7. GitHub 网页核对无误后，再 `git push --force origin rebuilt-main:main`（覆盖，需你授权）

优点：彻底摆脱 corrupt 对象；P0-B（users.db 泄露历史）天然解决（未纳入仓库）；过程全程可回滚。
缺点：旧 commit 历史丢失（代码全在，无功能损失；如需历史可走 B）。

### B. 从 dangling 对象抢救部分历史【不推荐 · 复杂】

- `git fsck` 显示有 dangling blob/tree/commit 仍可读取
- 用 `git cat-file` 逐个拼回最近若干 clean commit
- 复杂、不确定、耗时长；仅当旧历史有合规/审计价值才考虑

### C. 从外部干净副本恢复【最稳 · 若你有其他副本】

- 生产服务器 `/var/www/huawei-cloud-solution-matcher` 是 wget zip 部署，**无 `.git`**
- 若你本地其他机器 / 旧硬盘有 pre-corruption 的干净 clone，以其为基线最稳
- 需你提供路径

---

## 3. P0-B（users.db 泄露历史清洗）

- 已确认 `users.db` 被 `.gitignore` 覆盖（line 238）
- `git log --all -- users.db` 因 corrupt 无法查询，但路径 A 天然不纳入 `users.db`
- **结论**：走 A 即等于完成 P0-B，无需额外 `git filter-repo`

---

## 4. 执行前核对清单

- [ ] 你选 **A / B / C**
- [ ] 若选 A：是否授权第 7 步 force-push（建议先走第 6 步推 `rebuilt-main` 验证）
- [ ] 3 个重建文件（intent / memory_profiles / mcp_client）若有原版，先覆盖再重建
- [ ] 重建后 `git status --ignored` 核对 `data/`、`api/data/`、`*.db` 确实被忽略

---

## 5. 风险与回滚

- 备份 `/e/newai/_bkp_recovery_20260828/` 可随时 `tar` 还原
- force-push 前可先在 GitHub 把旧 `main` 存档为分支/归档，避免误覆盖
- 生产部署不受影响（部署走 `wget main.zip`，不依赖本地 `.git`）
