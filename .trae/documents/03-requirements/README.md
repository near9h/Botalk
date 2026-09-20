# 03 需求管理（Requirements）

> PMBOK 第 5 章：项目范围管理 之 需求收集与定义。

---

## 1. 业务需求（Business Requirements）

| ID | 描述 | 优先级 |
| --- | --- | --- |
| BR-001 | 业务人员可一站式使用多模型互相评审 | P0 |
| BR-002 | 上传企业文档 → bot 自动引用并标注出处 | P0 |
| BR-003 | 所有用户操作可追溯（审计合规） | P0 |
| BR-004 | 部署方运维可单机一键升级 | P0 |
| BR-005 | 多语言：中英文混用场景下 bot 回复跟用户语种 | P1 |
| BR-006 | 引用准确率 ≥ 90%（不出现空指针 / 段页错位） | P1 |

---

## 2. 干系人需求（Stakeholder Requirements）

| 角色 | 需求 | 来源 |
| --- | --- | --- |
| 业务 | 多模型互评 + 引用 | BR-001/002 |
| 安全 | 审计日志全、密码哈希、权限分层 | [security-audit-report](../07-testing/security-audit-report.md) |
| 运维 | 一键启停、健康检查、Runbook | [09-operations](../09-operations/) |
| 开发 | 代码模块化、可测、可回滚 | [06-implementation](../06-implementation/) |

---

## 3. 解决方案需求（Solution Requirements）

### 3.1 功能需求

#### 3.1.1 机器人（Bots）

- 列表支持**搜索 + 分页**（见 [06/bots-search-pagination.md](../06-implementation/bots-search-pagination.md)）
- CRUD + 模型下拉自动补全 NewAPI 已注册模型
- 角色：user 可管理自己；admin 可管理全部

#### 3.1.2 群组（Groups）

- 创建时选模式（auto / round_robin / manual）+ max_rounds
- 添加机器人从已存在 bot 池选
- 删除级联清理消息

#### 3.1.3 消息 / 聊天（Messages + Chat）

- 流式 SSE 输出（`/api/chat/stream`）
- 同任务上下文注入（`_load_prior_history`）
- 引用回查 chunk（bbox 标注用 PDF.js）

#### 3.1.4 知识库（KB / RAG）

- 上传 PDF / Word / Excel / PPT
- MinerU 解析 + LibreOffice headless 转 PDF
- 检索：BM25 + pgvector cosine + RRF 融合（单一方案）
- 引用稳定（见 [06/citation-stability.md](../06-implementation/citation-stability.md)）

#### 3.1.5 审计（Audit）

- 用户操作全留痕（login / create / delete / update）
- client_ip 来自 `X-Real-IP` / PROXY 协议
- 见 [09-operations/user-mgmt-audit-log.md](../09-operations/user-mgmt-audit-log.md)

### 3.2 非功能需求

| 维度 | 目标 |
| --- | --- |
| 可用性 | 单一服务重启 RTO < 5min |
| 性能 | 单次 chat SSE P95 < 30s（不含 NewAPI 端到端） |
| 安全 | 密码 bcrypt 哈希 + 审计留痕 + 权限边界 |
| 可维护 | 模块 README + ADR（见 [adr/](../adr/)） |
| 可移植 | Docker Compose 一键交付 |
| 可观测 | docker logs + 审计表查询 |

### 3.3 接口需求

- **API**：FastAPI 自动 OpenAPI（`/docs`）
- **前端 ↔ 后端**：JSON + SSE；详见 [05-design/api-contract.md](../05-design/api-contract.md)（待补）
- **后端 ↔ NewAPI**：OpenAI `/v1/chat/completions` 兼容

---

## 4. 需求追溯矩阵（RTM）

| 业务需求 | 设计文档 | 实现 | 测试 |
| --- | --- | --- | --- |
| BR-001 | [04-architecture/rag-design.md](../04-architecture/rag-design.md) | `backend/app/orchestrator/msghub.py` | `tests/test_msghub_lang_directive.py` |
| BR-002 | [04-architecture/hybrid-bm25-rag.md](../04-architecture/hybrid-bm25-rag.md) | `services/rag_retriever.py` `services/local_retriever.py` | `tests/test_local_retriever.py` |
| BR-003 | [09-operations/user-mgmt-audit-log.md](../09-operations/user-mgmt-audit-log.md) | `app/services/audit.py` | `tests/test_audit.py` |
| BR-005 | [06-implementation/i18n-completion.md](../06-implementation/i18n-completion.md) | `services/language_detect.py` | `tests/test_language_detect.py` |
| BR-006 | [06-implementation/citation-stability.md](../06-implementation/citation-stability.md) | `services/citation_aligner.py` | `tests/test_citation_aligner.py` |

---

## 5. 验收准则（Acceptance Criteria）

- ✅ 用户能完成"建 bot → 建群 → 加入 bot → 提问 → 流式看到回复 → 上传文档 → 引用"
- ✅ 审计表 `audit_log` 能查到所有用户操作（带 client_ip）
- ✅ 删除 KB 级联清理 chunks + 文档
- ✅ 重命名 KB 不影响挂载的 bot（见最近 commit `ae0bae1`）
- ✅ CI 跑通 pytest + tsc

---

## 6. 相关链接

- [04 架构设计](../04-architecture/)
- [05 详细设计](../05-design/)
- [07 测试](../07-testing/)