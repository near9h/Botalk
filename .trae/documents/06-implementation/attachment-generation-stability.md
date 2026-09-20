# 附件生成稳定性 + 预览方案

> 调研 + 实施规划 · 2026-09-18
> 适用项目：`/root/Documents/trae_projects/botgroup`

---

## 0. 背景与目标

**痛点**

1. 多 bot 协作产出的文档（HTML / docx 等）**每次内容都不一样**——同一 prompt 重跑，措辞、数字、章节顺序都可能漂移
2. **没有任何"预览"环节**，前端只有下载卡片，没有 KIMI 类产品那种"右边弹出预览 + 下载"的体验
3. 附件 ID 与消息历史关联**断裂**（`Message.attachments` JSON 列从未写入），老任务点回去附件卡片容易掉

**目标**

- A. **稳定性**：让"同一份文档/任务"的产出可复现，根治 LLM 自由文随机性
- B. **预览体验**：右抽屉按 MIME 路由到不同渲染器，对齐 KIMI

---

## 1. 现状梳理（基于代码事实）

### 1.1 附件生命周期

```
[用户] Composer 发消息
    │  POST /api/chat/stream  (frontend/app/group/[id]/page.tsx:217)
    ▼
[后端] chat.stream_chat  (backend/app/api/chat.py:45)
    │  → start_run  (orchestrator/runner.py:70) 建 Run + share_token
    │  → run_group_discussion  (orchestrator/msghub.py:418) 多轮循环（≤6 轮）
    ▼
[Orchestrator] 每轮
    │  policy.select 选出本轮 bot
    │  _generate_agent → OpenAI chat.completions.create(stream=False)
    │    system prompt 注入：persona + 模板原文 + 技能清单
    │    doc_writer 温度=0.3，doc_auditor=0.2
    │    若 bot 有 doc skill：要求 LLM 用 [FILE:foo.md]…[ENDFILE] 包裹
    ▼
[工具] generate_document(markdown, filename, title)
    │  backend/app/tools/document.py:39
    │  1. pypandoc.convert_text(md, "docx", outputfile=dest)
    │  2. 写 Attachment 行（content_md=原始 markdown）
    │  3. 返回 "📄 文档已生成: `<name>` [下载](attachment://<id>)"
    ▼
[SSE] OrchestratorEvent.attachments 字段定义在 msghub.py:88，但**从未被赋值**
    │  前端兜底靠 markdown 文本里的 attachment:// 链接解析
    ▼
[前端] ChatBubble
    │  markdown-it 解析 + 自定义 link_open 拦截 attachment://<id>
    │  (frontend/lib/markdown.ts:57-89)
    │  → 改写 href 为 /api/attachments/<id>/download
    ▼
[下载] GET /api/attachments/{id}/download (backend/app/api/attachments.py:246)
    │  把 content_md UTF-8 编码后返回（mime 用原值但实际是 markdown 字节）
```

### 1.2 现有附件 UI

| 元素 | 文件:行 | 作用 |
|---|---|---|
| `AttachmentCards` 下载卡片 | `frontend/components/ChatBubble.tsx:221-313` | 文件名+大小+↓ 图标 |
| `attachment://` 拦截 | `frontend/lib/markdown.ts:57-89` | 把 markdown 链接转真下载 |
| `attachmentEmoji` | `frontend/components/ChatBubble.tsx:201-214` | 按扩展名选图标 |
| `batchAttachmentMeta` | `frontend/app/group/[id]/page.tsx:259-261` | 老消息兜底批量取元数据 |

⚠️ **没有 iframe srcdoc / pdf.js / mammoth 任何"就地点开看"的预览**

### 1.3 当前随机性来源

1. **LLM 自由文输出**（最大头）：温度 0.2-0.3 仍漂移，多 bot 协作每段措辞都继承
2. **文件名由 LLM 拍脑袋**：`document.py:43` 直接用 `args["filename"]`，prompt 只"建议"英文短名
3. **模板归并不严格**：模型有时把内容省略或气泡里也复述
4. **附件-消息关联断裂**：`Message.attachments` 从未写入，历史消息卡片可能掉
5. **完全无幂等/去重**：重发同 prompt → 全新 docx，无任何"指纹复用"
6. **字节级不可重复**：`attachments.py:266-284` 直接返回 `content_md` 字节，未规范化

---

## 2. 外部方案对比（已 WebSearch 验证真实存在）

### 2.1 MCP 文件生成类 Server

| 名称 | 来源 | 活跃度 | 输出格式 | 持久化 | 预览 | 备注 |
|---|---|---|---|---|---|---|
| `@modelcontextprotocol/server-filesystem` | npm 官方 | ⭐⭐⭐⭐⭐ | 任意 | 沙箱目录 | 否 | 通用 fs |
| `mcp-pandoc` | PyPI v0.11.x | ⭐⭐⭐⭐⭐ | md/html/docx/pdf/rst/latex/epub/ipynb | 输出路径 | 否 | Pandoc 万能 |
| `mcp-docgen` | PyPI v0.8.0 | ⭐⭐⭐ | docx/xlsx/pptx/html/pdf 全套 | 写文件 | 否 | 读+改+写闭环 |
| `md_converter_mcp` | PyPI 0.1.0 | ⭐⭐ | md→pdf/docx | 写文件 | 否 | **打印级报告**：主题+TOC+页码+页眉 |
| `doc-ops-mcp` | npm v0.3.8 | ⭐⭐⭐ | pdf/docx/html/md 互转 | 写文件 | 否 | 中文环境，含水印/二维码 |
| `@lifeng688/document-converter-mcp` | npm v1.0.0 | ⭐⭐⭐ | md↔pdf/docx/html | 写文件 | 否 | Pandoc + MarkItDown 双引擎 |

> **判断**：MCP 对 BotGroup 价值有限——我们已用 OpenAI tool calling 实现同类能力（`app/tools/document.py`），改 MCP 收益≈0、改造成本高。**不推荐**作为当前方案。
> 唯一例外：未来要做 pptx/xlsx/高级 PDF（含 TOC/页眉/公司 logo）时，`md_converter_mcp` 或 `mcp-docgen` 才有意义，但仍可做成内置 tool。

### 2.2 服务端渲染库

| 库 | 用途 | 容器化 | 稳定性 | 引入成本 |
|---|---|---|---|---|
| **pypandoc-binary**（已在用） | md ↔ 一切 | 零（vendored） | 高 | ✅ 已引入 |
| **WeasyPrint** | HTML+CSS→PDF | 需 libpango | 高，无 JS | 中 |
| **Puppeteer / Playwright** | HTML+JS→PDF | +200~500MB | 高 | 中（并发瓶颈） |
| **Gotenberg** | 微服务式（chromium + Loki） | 一个镜像 | 中（继承 Loki 坑） | 中 |
| **docxtpl** | docx 模板 + Jinja 占位符 | 纯 Py | 高 | 低 |
| **Jinja2** | 文本模板 | 纯 Py | 高 | 低 |

⚠️ **LibreOffice headless 不推荐** —— 单进程加锁、僵尸进程、版本漂移。dev.to 有《We Replaced Headless LibreOffice with a Single Rust Binary》专门列举所有坑。

### 2.3 AI 输出稳定化技术

| 技术 | 解决什么 | 局限 |
|---|---|---|
| Structured Output / JSON mode | 保证合法 JSON | 旧版不强制 schema；新版 OpenAI `response_format.strict=true` 才真强制 |
| Pydantic 校验 + 自动重试 | 校验类型/必填 | 只解决"结构对"，内容语义随机性解决不了 |
| Tool calling | 把输出做成结构化调用 | content 字段仍随机 |
| temperature=0 + seed | 同 prompt 同模型同 seed → 同输出 | 换供应商/加 tool 结果就破功 |
| **Template + Data（结构化 JSON + Jinja/docxtpl）** | **LLL 只产结构化数据，模板引擎渲** | **本质性消除随机性** |

**结论**：根治稳定性 = 「结构化数据 + 模板渲染」，其它手段只能压方差。

---

## 3. 预览/下载体验方案

| 格式 | 方案 | 包大小 |
|---|---|---|
| Markdown | 继续用 markdown-it（已引入）+ GFM | 0 |
| HTML | `<iframe sandbox srcdoc>`（已有 ECharts 沙箱经验） | 0 |
| PDF | `pdfjs-dist` 懒加载 | ~1.5MB |
| DOCX | `mammoth` 客户端 docx→html | ~150KB |
| XLSX | `SheetJS (xlsx)` | 数 MB |
| 图片 | `<img>` 直渲 | 0 |

---

## 4. 推荐路线（按改造量从小到大）

### 路线 A · 最小改动：只加预览，不动生成链（1-2 天）

**改/新增**

- `frontend/components/AttachmentPreviewDrawer.tsx`（新）：右抽屉，按 MIME 路由
- `frontend/components/ChatBubble.tsx`：下载卡片左加 👁 预览按钮
- `frontend/lib/preview/{html,markdown,pdf,docx}.{ts,tsx}`（新）：懒加载渲染器
- `backend/app/api/attachments.py:275-284`：支持 `?inline=1` 改 `Content-Disposition: inline`

**新增依赖**：`pdfjs-dist`、`mammoth`（均 `import()` 懒加载）

**收益**：预览体验立即对齐 KIMI
**风险**：不解决"重发同 prompt 产出不一致"的稳定性根问题

### 路线 B · AI 输出 JSON + 模板渲染（**推荐**，1-2 周）

**核心思路**：AI 只产结构化 JSON，模板引擎灌进确定版式

**模型侧**
- `backend/app/skills/registry.py:19-58`：doc_writer manifest 改成"只输出 JSON"
- `backend/app/orchestrator/msghub.py:245-412`：`_generate_agent` 给 doc 类 bot 加 `response_format: json_schema (strict: true)`
- 加 Pydantic 模型服务端校验 + 失败重试（最多 3 次）

**模板侧**（两条路任选）
- **DOCX**：用 `docxtpl` + 用户上传的 .docx 模板（Word 标 `{{ field }}`、`{%p for %}`）
- **HTML**：用 Jinja2 + `template_store/templates/<name>.html.j2`

**关联修复**
- `orchestrator/runner.py:123-154` `save_message` 真正写 `attachments` 参数
- `msghub.py:88` SSE `OrchestratorEvent.attachments` 真正填上
- 前端 `loadAll` 不再依赖 `batchAttachmentMeta` 兜底

**收益**：
- 同一 prompt → 同一文件（除非 seed 真随机）= 根治
- 模板掌控版式，AI 只管数据 = 设计/AI 边界清晰
- 改版式/加 logo 只改模板，不改代码

**风险**：
- 现有"自由模板"需重写为 docx+占位符（有迁移成本）
- LLM 严格 JSON 成功率供应商差异大：OpenAI gpt-4o 2024-08+ 几乎 100%
- 多 bot 链路里 doc_writer 拿的是"上游结构化输出"而非 markdown，需重新设计

### 路线 C · 接入 MCP + 全结构化（**不推荐当前做**，3-4 周）

- 引入 MCP 客户端替换 `app/tools/document.py`
- docker-compose 加 MCP server 进程
- 改造成本巨大，价值有限

---

## 5. 决策点（需要你拍板）

### 5.1 走 A 还是 B？

**A**：仅解决预览体验，不解决内容随机性。改造小，1-2 天上线
**B**：同时解决预览+稳定性，1-2 周投入

**推荐**：**先做路线 A**（满足 KIMI 体验诉求），**同步规划路线 B** 作为下个迭代

### 5.2 稳定性路线 B 的进一步选择

| 维度 | 选项 |
|---|---|
| **粒度** | (a) 章节级占位（章节标题固定，正文自由）<br>(b) 字段级占位（每节也是 schema 字段，正文更稳但灵活性低） |
| **模板由谁设计** | (A) 产品在 Word 里画模板上传<br>(B) 程序员维护<br>(C) 前端拖拽搭模板 |
| **旧路径保留** | 保留 markdown→docx 作为 fallback？或彻底切？ |
| **预览覆盖** | 仅 md/html/docx/pdf，还是含 xlsx/pptx？ |
| **新依赖** | 接受 pdfjs-dist + mammoth（~1.7MB 懒加载）？ |

---

## 6. 待用户确认的关键问题

1. **首选走哪条路？** A / B / C
2. **若 B：模板粒度** 章节级（a） vs 字段级（b）
3. **若 B：是否保留旧 markdown→docx 路径** 作为 fallback
4. **预览覆盖范围**：最小集 md/html/docx/pdf，还是要加 xlsx/pptx

---

## 7. 验收步骤（实施路线 A 后）

1. 进群组发送带 docx skill 的 prompt，bot 产出文档附件
2. 点击附件卡片的 👁 按钮 → 右边弹出抽屉
3. 抽屉内：
   - md/html → iframe 渲染
   - pdf → pdf.js 渲染
   - docx → mammoth 渲染为 html
4. 抽屉顶部固定"下载 / 关闭 / 上一份 / 下一份"
5. 下载按钮走 `?inline=0` → Content-Disposition: attachment
6. 预览按钮走 `?inline=1` → Content-Disposition: inline
7. 历史任务点回，附件卡片仍能预览（修复 Message.attachments 后）

---

## 8. 关键文件 / 行号速查

| 主题 | 路径:行 |
|---|---|
| LLM 调用入口 | `backend/app/orchestrator/msghub.py:245-412` |
| 文档工具实现 | `backend/app/tools/document.py:1-112` |
| doc_writer bot | `backend/alembic/versions/0010_protected_bots.py:42-56` |
| doc_auditor bot | `backend/alembic/versions/0010_protected_bots.py:60-74` |
| document_writer skill | `backend/app/skills/registry.py:19-58` |
| 模板选择 | `backend/app/skills/resolve.py:84-112` |
| system prompt 拼装 | `backend/app/orchestrator/msghub.py:286-322` |
| `[FILE:...]` 协议（**死代码**） | `backend/app/orchestrator/msghub.py:39-63` |
| Attachment 写入 | `backend/app/tools/document.py:85-101` |
| 下载接口 | `backend/app/api/attachments.py:246-284` |
| Message.attachments 列 | `backend/app/db/models.py:167` |
| save_message | `backend/app/orchestrator/runner.py:123-154` |
| 附件卡片渲染 | `frontend/components/ChatBubble.tsx:221-313` |
| `attachment://` 拦截 | `frontend/lib/markdown.ts:57-89` |
| 历史任务批量取 meta | `frontend/app/group/[id]/page.tsx:259-261` |
| 现有预览（不可复用） | `frontend/lib/markdown.ts:144-158`（ECharts） |