# 方案：代码审计 — 安全与权限边界

## 摘要

BotGroup 81 个 Python 文件 + 36 个 TS/TSX 文件的安全审计。聚焦**安全与权限边界**：API 权限矩阵、SSRF、SQL 注入、路径穿越、session/Cookie、文件上传与预览、第三方 API 凭据处理、log 重放。

本文档**只产出审计报告**——不修代码。审计完后再和用户决定修哪些、按什么优先级。

---

## 调研结论：业内常见审计范围

| 维度 | 工具/方法 | 覆盖 |
|------|---------|------|
| SAST（静态扫描） | bandit, ruff, mypy | 安全 smell + 类型 |
| 依赖漏洞 | pip-audit, npm audit | 已知 CVE |
| Secret scan | gitleaks, trufflehog | 凭据泄漏到 git |
| IaC scan | trivy (dockerfile) | 镜像漏洞 |
| 自定义审计 | 人工 review | 业务逻辑 |

BotGroup 已有 ruff + pytest + bandit-ready 项目结构（用 `pyproject.toml` 标准布局），但没看到 SAST 流水线。我会做**人工审计 + bandit/safety 静态扫描 + 自定义安全 checklist**。

---

## 现状分析

### 已知 commit 历史里的安全相关 fix

- `60b7039 fix(chat,kb): 修复代码审计发现的引用链路缺陷`
- `42e1a30 fix(audit): 审计日志记录真实客户端 IP`

说明项目**之前做过类似审计**。我需要看这些 commit 的范围，确认是否复盘。

### 核心模块分布（重点审计对象）

| 模块 | 风险点 |
|------|--------|
| `backend/app/api/chat.py` | SSE 鉴权、user 输入注入 LLM prompt |
| `backend/app/api/kb.py` | 文件上传、admin 权限校验 |
| `backend/app/api/users.py` | 用户管理、密码策略 |
| `backend/app/api/attachments.py` | 文件上传/下载路径、SSRF |
| `backend/app/api/audit.py` | 日志注入、审计完整性 |
| `backend/app/api/groups.py` | owner 权限、scope 隔离 |
| `backend/app/services/mineru.py` | 第三方 API 凭据 |
| `backend/app/services/zhipuai_embed.py` | 第三方 API 凭据 |
| `backend/app/services/ragflow_client.py` | 第三方 API 凭据 |
| `backend/app/services/local_retriever.py` | SQL 拼接、SSO/RCE |
| `backend/app/auth.py` | session 强度、bootstrap 密码 |
| `backend/app/main.py` | CORS、middleware |
| `frontend/lib/api.ts` | XSS、Sensitive data 持久化 |

---

## 审计策略

### 阶段 1：自动化扫描（快速 baseline）

跑：
- `bandit -r backend/app` —— Python SAST
- `pip-audit` —— 依赖漏洞
- `npm audit --prefix frontend` —— 前端依赖漏洞
- `gitleaks detect --no-banner` —— 历史 git 是否有泄露的 secret

### 阶段 2：人工审计（10 个 check item）

按 OWASP / 业内审计清单，每项至少 2 个具体证据 + 评级（critical/high/medium/low/info）。

1. **认证 & 会话**
   - JWT 算法/signing key 强度
   - bootstrap 默认密码检测
   - cookie `secure` / `samesite=strict`
   - 会话固定 / 失效处理
   - 失败计数器 / 速率限制

2. **访问控制矩阵**
   - 每条 API 路由的 `Depends(require_user/require_admin)` 是否正确
   - "owner" 校验在 create/read/update/delete 各路径是否完整
   - KB / Bot / Group 的 RBAC 边界
   - 跨用户数据泄漏面（user A 能看 user B 的数据吗）

3. **SQL 注入 / ORM 安全**
   - 所有 `text()` SQL 是否使用 `:param` 而不是 f-string
   - `session.execute(stmt, params)` 还是 f-string
   - ORDER BY/LIMIT 等动态拼接

4. **SSRF / 第三方 API 出站**
   - MinerU / GLM / RAGFlow 调用是否对 URL 校验
   - `kbDocumentPreviewUrl` 是否允许内网 URL
   - `httpx.AsyncClient` 是否限制 timeout、follow_redirects

5. **文件上传 & 下载**
   - `UPLOAD_DIR` 路径穿越（`../` 注入）
   - `attachment_id` 是否校验 owner
   - PDF preview 路径是否 owner-scoped
   - 文件类型白名单（不是只查扩展名，是 magic bytes）

6. **注入面：LLM/RAG 链路**
   - 用户输入是否未消毒就直接拼到 system prompt
   - KB chunk 内容（来自不可信 PDF）是否影响 LLM 行为
   - chunk snippet 注入到前端 React（`dangerouslySetInnerHTML` 的引用 chip 是不是 HTML safe）
   - `[N]` / `[doc: ...]` regex 注入（用户消息里写 `[doc: xxx.pdf p.1 ¶1]` 能否伪造引用？）

7. **XSS / 前端**
   - React `dangerouslySetInnerHTML` 出现位置（chat bubble 已用 markdown-it；message-end 引用的 citation 拼接是否走 sanitize）
   - 用户可控内容（bot name、KB 描述、文件名）进入 innerHTML 的路径
   - cookie 路径 `path="/"` 是否够严格

8. **凭据 & 配置**
   - `.env` 是否在 git 里
   - 任何 hard-coded secret、API key
   - settings 加载是否覆盖默认值（默认 `change-me-in-env-please-very-long-random-string` 已经抛 RuntimeError，但 AUTH_DISABLED 是否绕过这条防御）

9. **日志 & 监控**
   - 审计日志是否能被日志破坏者（CRLF、JSON 注入）
   - 错误堆栈是否泄漏 DB schema / 文件路径 / token
   - 用户密码、session 是否进日志

10. **依赖 & 部署**
    - Docker base image 是否 pinned digest
    - docker-compose 是否把 `.env` 通过 `env_file` 加载（不暴露在容器外）
    - nginx 反代是否带 HTTPS / HSTS（生产模式）
    - 数据库连接是否 TLS（生产）

### 阶段 3：风险评级 & 报告

- 把发现按 critical / high / medium / low / info 排序
- 给出每项的：位置（file:line）、证据、修复建议、估算工时
- **不修代码**，只在报告里列出来由用户拍板

---

## 涉及文件

| 操作 | 路径 |
|------|------|
| 新建报告 | `.trae/documents/security-audit-report.md`（阶段 3 输出） |
| 跑扫描 | `backend/` 目录跑 bandit / pip-audit |
| 跑扫描 | `frontend/` 目录跑 npm audit |
| 跑扫描 | git 历史跑 gitleaks |
| 人工阅读 | 上述 13 个核心模块 |

---

## 假设与决策

- **范围**：14 个核心模块 + 历史 commit 复盘。**不**审计 alembic 迁移、tests、stale 文件。
- **不修代码**：发现的问题只列在报告里；修复走单独 plan。
- **静态扫描输出**：bandit 的 JSON + pip-audit + gitleaks 都放在报告附录。
- **报告放在 docx/PDF**：不；保持 `.trae/documents/security-audit-report.md` 单文件，便于 review。
- **不引入新依赖**：用项目里已有的工具（ruff、pytest、bandit 通过 `pip install bandit` 临时跑）。

---

## 验证步骤

1. 跑 bandit / pip-audit / npm audit / gitleaks —— 输出 raw 结果
2. 按 10 个 check item 人工 review，每个 item 至少 2 处证据
3. 输出报告 `.trae/documents/security-audit-report.md`
4. 用 AskUserQuestion 让用户决定优先级

---

## 调研来源

- [OWASP Top 10 for LLM Applications 2025](https://owasp.org/www-project-top-10-for-large-language-model-applications/)
- [OWASP API Security Top 10](https://owasp.org/www-project-api-security/)
- [Bandit documentation](https://bandit.readthedocs.io/)
- [pip-audit](https://pypi.org/project/pip-audit/)
- [gitleaks](https://github.com/gitleaks/gitleaks)
- 项目历史 commit `60b7039` "修复代码审计发现的引用链路缺陷"