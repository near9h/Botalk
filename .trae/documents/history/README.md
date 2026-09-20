# history — 历史方案归档

> 开发期沉淀的方案文档。迁移自旧 `.trae/documents/` 顶层。
> **不要修改这些文件** —— 历史定稿；新版以 [../06-implementation/](../06-implementation/) 为准。

## 索引（按主题）

| 原文件 | 主题 | 现位置（活跃文档） |
| --- | --- | --- |
| `knowledge_base_rag_plan.md` | RAG 整体设计（早期） | 已合并进 [../04-architecture/hybrid-bm25-rag.md](../04-architecture/hybrid-bm25-rag.md) + [../04-architecture/rag-design.md](../04-architecture/rag-design.md) |
| `rag-design.md` | RAGFlow 时代的方案（**已废弃**） | 现 [../adr/0004-kb-local-rag.md](../adr/0004-kb-local-rag.md)（明确放弃 RAGFlow） |
| `hybrid-bm25-rag-plan.md` | BM25+向量融合 | 现 [../04-architecture/hybrid-bm25-rag.md](../04-architecture/hybrid-bm25-rag.md) |
| `sentence-window-context-plan.md` | 句窗上下文 | 现 [../04-architecture/sentence-window-context.md](../04-architecture/sentence-window-context.md) |
| `skill-center-plan.md` | 技能中心 | 现 [../04-architecture/skill-center.md](../04-architecture/skill-center.md) |
| `ui-redesign-plan.md` | UI 重设计 | 现 [../05-design/ui-redesign.md](../05-design/ui-redesign.md) |
| `group-policy-firewall-plan.md` | 群组策略防火墙 | 现 [../06-implementation/group-policy-firewall.md](../06-implementation/group-policy-firewall.md) |
| `citation-stability-plan.md` | 引用稳定 | 现 [../06-implementation/citation-stability.md](../06-implementation/citation-stability.md) |
| `attachment_generation_stability_plan.md` | 附件生成稳定 | 现 [../06-implementation/attachment-generation-stability.md](../06-implementation/attachment-generation-stability.md) |
| `i18n-completion-plan.md` | 国际化完成 | 现 [../06-implementation/i18n-completion.md](../06-implementation/i18n-completion.md) |
| `user-mgmt-audit-log-plan.md` | 用户管理 + 审计日志 | 现 [../09-operations/user-mgmt-audit-log.md](../09-operations/user-mgmt-audit-log.md) |
| `security-audit-plan.md` | 安全审计计划 | 现 [../07-testing/security-audit-plan.md](../07-testing/security-audit-plan.md) |
| `security-audit-report.md` | 安全审计报告 | 现 [../07-testing/security-audit-report.md](../07-testing/security-audit-report.md) |
| `audit-fixes-high-critical.md` | 高危审计修复 | 现 [../07-testing/audit-fixes-high-critical.md](../07-testing/audit-fixes-high-critical.md) |
| `multi-bot-group-chat-plan.md` | 多 bot 群聊原始方案 | 现 [../01-initiation/project-charter.md](../01-initiation/project-charter.md) |
| `多机器人群聊工具开源方案调研.md` | 开源方案调研 | 现 [../02-planning/market-survey.md](../02-planning/market-survey.md) |

> 注：上表里原文件路径（左侧）就是 `history/` 下的文件；活跃文档（新位置）见右侧链接。

## 保留原则

- **不改文件内容** — 历史定稿
- **不删文件** — 审计需要
- **新增内容**：写新章节下的活跃文档，并在活跃文档顶部加引用本文件