# 双分支工作流（main vs publish）

> botgroup 维护两个永久分支：
> - **`main`**：实际跑生产用的业务分支。含 .env / data/ / 真实密钥 / 全部开发文档。
> - **`publish`**：专门给 GitHub 用的镜像分支。**只含代码、配置模板、纯结构**。
> 平时所有开发在 `main` 上做，定期把代码 cherry-pick 到 `publish` 推送。

---

## 1. 为什么需要 publish 分支

| 风险 | main（业务） | publish（GitHub） |
| --- | --- | --- |
| .env / 真实 API Key | ✅ 必要 | ❌ 绝不入仓 |
| `data/uploads/` 真实业务文档 | ✅ 必要 | ❌ 绝不入仓 |
| `data/postgres/` PGDATA 备份 | ✅ 必要 | ❌ 绝不入仓 |
| `.trae/documents/` 内审 / 内部 SOP / 联系人 | ✅ 必要（脱敏版已能 publish，但谨慎起见不放） | ❌ 暂不放（评估后再决定） |
| 代码 / 配置模板 / .env.example / Dockerfile | ✅ | ✅ |
| README / INTRO / LICENSE / CONTRIBUTING / SECURITY | ✅ | ✅ |
| 公开发布的 feature 文档（`history/` 归档的过期方案） | ✅ | ✅（已脱敏） |

> publish 分支**只 git push 到 GitHub**；main 分支只本地 / 内网仓库使用。

---

## 2. 日常开发流程

```bash
# 1) 切到业务分支
git checkout main

# 2) 正常开发（.env + data/ 都靠 .gitignore 挡着）
#    写代码 → 跑测试 → commit 到 main

# 3) 当准备好发版时：
git checkout publish

# 4) 把 main 的新提交 pick 过来
#    推荐：rebase 保持线性
git rebase main
#    或者（如果 main 含 publish 不能要的提交）：
git cherry-pick <sha>          # 一个一个选
#    或者：直接 reset --soft
git reset --soft main
git commit -m "publish: 同步 main HEAD"

# 5) 推送前必跑 sanity-check
./scripts/publish-preflight.sh

# 6) 推送
git push -u github-publish publish:main
```

---

## 3. 推送前自动检查（preflight）

`scripts/publish-preflight.sh` 在 push 前跑：

1. 验证 `.env` / `data/` / `.env.local` / `*.key` **没有被 git 跟踪**
2. 在所有已跟踪文件里 grep 真实 IP / 真实 key 前缀 / 真实邮箱
3. 检查 commit message 是否含敏感关键字（debug log 中常见的 `Bearer sk-...`）
4. 检查 `.env.example` 没有真实 key 残留

任一项失败 → **拒绝 push**，告诉你哪行哪列有问题。

---

## 4. 危险操作黑名单

publish 分支**禁止**做的事：

- ❌ 在 publish 分支上 commit `.env` / `data/` / 任何含真实 key 的文件
- ❌ `git add .`（永远用 `git add <具体文件>`）
- ❌ `git commit --amend` 一个本来干净的 commit 时把工作树里未跟踪的 `.env` 一起包含
- ❌ 把别人 PR merge 进来时 squash → 失去单 commit 审查机会

---

## 5. 文件结构差异（main vs publish）

```
main 分支独有（本地 + 内网仓库）:
  .env                          ← 真实 key
  .env.local                    ← 个人设置
  data/                         ← 上传文件 + PGDATA
  .trae/documents/01-initiation/project-charter.md   ← 内部 charter
  .trae/documents/04-architecture/data-flow.txt      ← 之前脱敏的 ASCII 备份
  .trae/documents/06-implementation/*.md            ← 实现记录（含公司内部细节）
  .trae/documents/07-testing/audit-fixes-*.md       ← 内部审计修复记录
  .trae/documents/09-operations/on-call.md          ← 真实 On-call 轮值
  .trae/documents/appendix/联系人登记.md            ← 真实联系人
  .trae/documents/appendix/进度追踪表.md            ← 含内部 commit 注释

publish 分支独有（GitHub）:
  GitHub-only docs（待加）:
    INTRO.md                    ← 已经在 publish（不敏感）
    INTRO 项目介绍可放在 GitHub README
```

> **简单原则**：你看到这份文档就明白了—— main 是"完整真实工作目录"，publish 是"对陌生人能展示的快照"。

---

## 6. 初始化发布（首次）

```bash
# 在 publish 分支 HEAD 上：
git remote add github-publish git@github.com:<your-org>/botgroup.git
git push -u github-publish publish:main
#   ↑ 推 publish 分支到 GitHub 的 main（GitHub 默认分支名）
```

以后每次更新：
```bash
git checkout publish
git rebase main                       # 或者 cherry-pick
./scripts/publish-preflight.sh         # 必须通过
git push github-publish publish:main
```

---

## 7. 出错应急

| 情况 | 补救 |
| --- | --- |
| 推了含 key 的 commit 到 GitHub | 立刻去 GitHub → Settings → Danger Zone → Delete repository，并轮换所有 key |
| 推了含业务文档的 commit | `git reset HEAD~1 && git push --force-with-lease` 撤回，然后从历史中 `git filter-repo` 清掉 |
| 怀疑有泄漏 | 用 `git log --all -p \| grep -E 'sk-[A-Za-z0-9]{20,}\|[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}'` 扫一遍 |

---

## 8. 相关脚本

| 脚本 | 用途 |
| --- | --- |
| `scripts/publish-preflight.sh` | 推送前 9 项检查 |
| `scripts/backup.sh` | main 分支专用（生产备份） |

---

**TL;DR**：两个分支，main 干活，publish 发版；中间用 rebase / cherry-pick 同步，preflight 脚本兜底。