# BotGroup UI/UX 重新设计计划

## Summary

把当前"灰色表单 + prompt 弹窗"的极简实现重塑为一个 **浅色 / 玻璃拟态 / 柔和风格** 的产品级界面，参照 Apple/Stripe 设计语言。改造目标：

1. **机器人管理可视化**：emoji 头像、按模型分组的彩色 badge、彩色温度条、人设预览卡片、空状态引导
2. **模型选择可视化**：下拉 + 卡片选择器双模式，从后端 `/api/models` 拉 NewAPI 模型列表（不再手工输入）
3. **群组管理可视化**：建群向导（4 步 modal）、群成员可视化卡片、可视化运行模式选择器
4. **群聊体验升级**：机器人头像 + 彩色名字气泡、Markdown 渲染、token 用量统计、运行状态指示器
5. **整体风格统一**：玻璃拟态（frosted glass）卡片、柔和阴影、圆角大、Inter 字体、新加坡风格柔和调色板（淡蓝/淡紫/淡绿点缀）

技术栈：**shadcn/ui 风格的 copy-paste 组件**（不引入 npm 包，直接把源文件拷到项目里）。后端加 2 个端点 + 1 个迁移。前端完全重写。

---

## Current State Analysis

**现有前端现状**（[frontend/](file:///root/Documents/trae_projects/botgroup/frontend/)）：

| 文件 | 问题 |
|---|---|
| [app/globals.css](file:///root/Documents/trae_projects/botgroup/frontend/app/globals.css) | 41 行临时 CSS，无设计系统、无变量、无响应式 |
| [app/page.tsx](file:///root/Drae_projects/botgroup/frontend/app/page.tsx) | 群组列表：灰背景、文字卡片、`window.prompt` 建群 |
| [app/bots/page.tsx](file:///root/Documents/trae_projects/botgroup/frontend/app/bots/page.tsx) | 机器人列表：内联 style、`model` 字段是 `<input>` 手工输入、无头像 |
| [app/group/[id]/page.tsx](file:///root/Documents/trae_projects/botgroup/frontend/app/group/[id]/page.tsx) | 群聊：单色气泡、机器人没头像区分、无 Markdown、无运行状态 |

**缺失**：
- 没有任何设计系统（颜色变量、字体、间距、阴影）
- 没有 component primitives（Modal/Dialog/Select/Tabs/Toast 都缺失）
- 模型字段是文本输入 → 用户体验差，容易拼错
- 机器人无头像 → 群聊视觉单薄
- 建群用 `window.prompt` → 产品感缺失

**后端需要的微调**：
- 机器人表缺 `emoji` 字段（要加 migration）
- 缺 `/api/models` 端点（前端下拉框数据源）

**样式参考**（新加坡审美特征）：
- **色调**：浅米白底（`#FAFAF9` / `#F8FAFC`），柔和强调色（薰衣草紫 `#A78BFA`、薄荷绿 `#86EFAC`、桃粉 `#FDA4AF`、天蓝 `#93C5FD`）
- **字体**：Inter（英文）+ PingFang SC（中文），字重 400/500/600
- **形状**：12–20px 圆角、柔和阴影（`0 8px 30px rgba(0,0,0,0.04)`）、1px 浅边框
- **玻璃拟态**：`backdrop-filter: blur(20px)` + 半透明白底（`rgba(255,255,255,0.7)`）
- **间距**：8/12/16/24/32px 节奏
- **微动效**：hover/focus 过渡 150ms ease-out

---

## Proposed Changes

### 1. 后端（最小改动）

#### 1.1 数据库迁移：加 `emoji` 字段
**文件**：[backend/alembic/versions/0002_bot_emoji.py](file:///root/Documents/trae_projects/botgroup/backend/alembic/versions/0002_bot_emoji.py)（新建）
```python
"""add emoji to bots
Revision ID: 0002_bot_emoji
"""
def upgrade():
    op.add_column("bots", sa.Column("emoji", sa.String(8), nullable=False, server_default="🤖"))

def downgrade():
    op.drop_column("bots", "emoji")
```

#### 1.2 ORM 模型更新
**文件**：[backend/app/db/models.py](file:///root/Documents/trae_projects/botgroup/backend/app/db/models.py)
- `Bot` 加 `emoji: Mapped[str] = mapped_column(String(8), default="🤖")`

#### 1.3 Schemas 更新
**文件**：[backend/app/schemas.py](file:///root/Documents/trae_projects/botgroup/backend/app/schemas.py)
- `BotBase` 加 `emoji: str = "🤖"`
- `BotOut` 包含 `emoji`

#### 1.4 新增 `/api/models` 端点
**文件**：[backend/app/api/models.py](file:///root/Documents/trae_projects/botgroup/backend/app/api/models.py)（新建）
- 代理调用 NewAPI `GET /v1/models`，返回 `["data": [{"id": "...", "owned_by": "..."}]]`
- 加简单 60 秒内存缓存（避免每次建机器人页打开都打 NewAPI）

#### 1.5 注册路由
**文件**：[backend/app/main.py](file:///root/Documents/trae_projects/botgroup/backend/app/main.py)
- `app.include_router(models.router, prefix="/api/models", tags=["models"])`

---

### 2. 前端：设计系统 + 组件库 + 页面重写

#### 2.1 全局样式重写（设计系统）
**文件**：[frontend/app/globals.css](file:///root/Documents/trae_projects/botgroup/frontend/app/globals.css)（完全重写）

内容：
- CSS 变量层（颜色、字体、圆角、阴影、间距、动画）
- 浅色主题（默认）+ 预留深色主题切换钩子
- 玻璃拟态 utility class：`.glass`、`.glass-card`
- Inter 字体引入（Google Fonts CDN 链接）
- 动画 keyframes（fade-in、slide-up、shimmer）

#### 2.2 shadcn/ui 风格组件（copy-paste，无 npm 依赖）
**目录**：[frontend/components/ui/](file:///root/Documents/trae_projects/botgroup/frontend/components/ui/)（新建）

按依赖顺序：

| 文件 | 内容 | 用途 |
|---|---|---|
| [utils.ts](file:///root/Documents/trae_projects/botgroup/frontend/components/ui/utils.ts) | `cn(...)` className 合并工具 | 全部组件依赖 |
| [button.tsx](file:///root/Documents/trae_projects/botgroup/frontend/components/ui/button.tsx) | 按钮（5 个 variant × 3 个 size） | 全站 |
| [input.tsx](file:///root/Documents/trae_projects/botgroup/frontend/components/ui/input.tsx) | 文本输入 | 表单 |
| [textarea.tsx](file:///root/Documents/trae_projects/botgroup/frontend/components/ui/textarea.tsx) | 多行输入 | 人设编辑 |
| [label.tsx](file:///root/Documents/trae_projects/botgroup/frontend/components/ui/label.tsx) | 表单 label | 表单 |
| [card.tsx](file:///root/Documents/trae_projects/botgroup/frontend/components/ui/card.tsx) | 玻璃拟态卡片 | 列表项、面板 |
| [dialog.tsx](file:///root/Documents/trae_projects/botgroup/frontend/components/ui/dialog.tsx) | 模态对话框（无 Radix，纯原生 `<dialog>` + 自己实现 focus trap） | 建群向导、机器人编辑 |
| [select.tsx](file:///root/Documents/trae_projects/botgroup/frontend/components/ui/select.tsx) | 下拉（自定义实现，非原生） | 模型选择 |
| [tabs.tsx](file:///root/Documents/trae_projects/botgroup/frontend/components/ui/tabs.tsx) | Tabs（受控实现） | 机器人管理切换视图 |
| [slider.tsx](file:///root/Documents/trae_projects/botgroup/frontend/components/ui/slider.tsx) | 温度滑块 | 机器人温度 |
| [badge.tsx](file:///root/Documents/trae_projects/botgroup/frontend/components/ui/badge.tsx) | 模型/状态彩色 badge | 列表、群组模式 |
| [avatar.tsx](file:///root/Documents/trae_projects/botgroup/frontend/components/ui/avatar.tsx) | emoji 头像（带彩色背景圈） | 机器人、群成员 |
| [empty-state.tsx](file:///root/Documents/trae_projects/botgroup/frontend/components/ui/empty-state.tsx) | 空状态组件（图标 + 标题 + 引导按钮） | 空列表 |
| [toast.tsx](file:///root/Documents/trae_projects/botgroup/frontend/components/ui/toast.tsx) | 顶部 toast 通知 | 成功/失败反馈 |

每个组件都是单文件、纯 React + CSS module（无需 Radix），CSS 直接内联 style 或用 CSS Modules。shadcn/ui 的设计精髓保留（变体设计 tokens、size 系统、可访问性）。

#### 2.3 业务组件
**目录**：[frontend/components/](file:///root/Documents/trae_projects/botgroup/frontend/components/)

| 文件 | 内容 |
|---|---|
| [AppShell.tsx](file:///root/Documents/trae_projects/botgroup/frontend/components/AppShell.tsx) | 左侧玻璃侧栏 + 顶部导航的统一壳 |
| [BotCard.tsx](file:///root/Documents/trae_projects/botgroup/frontend/components/BotCard.tsx) | 机器人卡片：emoji 头像 + 名称 + 模型 badge + 温度条 + 人设预览 |
| [BotFormDialog.tsx](file:///root/Documents/trae_projects/botgroup/frontend/components/BotFormDialog.tsx) | 机器人新建/编辑对话框（含 ModelSelect） |
| [ModelSelect.tsx](file:///root/Documents/trae_projects/botgroup/frontend/components/ModelSelect.tsx) | 模型选择器：搜索 + 模型列表 + 模型分组（OpenAI/Anthropic/Google/Other）+ 显示 owned_by |
| [EmojiPicker.tsx](file:///root/Documents/trae_projects/botgroup/frontend/components/EmojiPicker.tsx) | emoji 选择网格（8 大类 × 每类 12 个 = 96 个候选） |
| [GroupCard.tsx](file:///root/Documents/trae_projects/botgroup/frontend/components/GroupCard.tsx) | 群组卡片：emoji 图标 + 名称 + 模式 badge + 成员头像组 + 消息数 |
| [GroupWizard.tsx](file:///root/Documents/trae_projects/botgroup/frontend/components/GroupWizard.tsx) | 4 步建群向导：基础信息 → 选择模式 → 选择成员 → 确认 |
| [ChatBubble.tsx](file:///root/Documents/trae_projects/botgroup/frontend/components/ChatBubble.tsx) | 聊天气泡：头像 + 彩色名字 + 内容 + Markdown（用 `marked` CDN）+ 流式光标 |
| [Composer.tsx](file:///root/Documents/trae_projects/botgroup/frontend/components/Composer.tsx) | 输入框：@机器人触发器、自动高度、发送按钮 |
| [Sidebar.tsx](file:///root/Documents/trae_projects/botgroup/frontend/components/Sidebar.tsx) | 侧边栏：logo + 导航 + 当前用户区域 |

#### 2.4 页面重写

| 文件 | 重写内容 |
|---|---|
| [app/layout.tsx](file:///root/Documents/trae_projects/botgroup/frontend/app/layout.tsx) | 引入 Inter 字体、设置 viewport、加 Toaster provider |
| [app/page.tsx](file:///root/Documents/trae_projects/botgroup/frontend/app/page.tsx) | 群组列表：玻璃卡片网格、空状态、GroupCard 组件、顶部"+"按钮触发 GroupWizard |
| [app/bots/page.tsx](file:///root/Documents/trae_projects/botgroup/frontend/app/bots/page.tsx) | 机器人管理：BotCard 网格、按模型分组、搜索栏、空状态、BotFormDialog |
| [app/group/[id]/page.tsx](file:///root/Documents/trae_projects/botgroup/frontend/app/group/[id]/page.tsx) | 群聊：左右两栏；左侧成员 + 设置；右侧 ChatBubble 列表 + Composer；底部显示当前运行状态 |

#### 2.5 API 类型与端点更新
**文件**：[frontend/lib/api.ts](file:///root/Drae_projects/botgroup/frontend/lib/api.ts)
- `Bot` 类型加 `emoji: string`
- `Group` 类型加 `description` 等显示字段（已有）
- 新增 `listModels(): Promise<ModelInfo[]>` 调用 `/api/models`

---

### 3. 设计与交互细节

#### 3.1 配色（CSS 变量）

```css
:root {
  --bg:           #FAFAF9;        /* 主背景，米白 */
  --surface:      rgba(255, 255, 255, 0.7);  /* 玻璃卡 */
  --surface-2:    rgba(255, 255, 255, 0.9);  /* 浮层 */
  --border:       rgba(0, 0, 0, 0.06);
  --fg:           #1F2937;
  --fg-muted:     #6B7280;
  --fg-subtle:    #9CA3AF;

  /* 强调色（柔和版） */
  --accent:       #A78BFA;        /* 薰衣草紫 - 主操作 */
  --accent-2:     #93C5FD;        /* 天蓝 - 信息 */
  --accent-3:     #86EFAC;        /* 薄荷绿 - 成功 */
  --accent-4:     #FDA4AF;        /* 桃粉 - 用户 */
  --accent-5:     #FCD34D;        /* 暖黄 - 警告 */

  /* 模型分类色 */
  --model-openai: #10B981;
  --model-anthropic: #D97706;
  --model-google: #4285F4;
  --model-zhipu: #6366F1;
  --model-other: #6B7280;
}

.glass {
  background: var(--surface);
  backdrop-filter: blur(20px) saturate(180%);
  -webkit-backdrop-filter: blur(20px) saturate(180%);
  border: 1px solid var(--border);
  border-radius: 16px;
  box-shadow: 0 8px 30px rgba(0, 0, 0, 0.04);
}
```

#### 3.2 关键页面线框

**首页（群组列表）**：

```
┌──────────────────────────────────────────────────────────┐
│  [☰] BotGroup                            欢迎回来 ⌘K     │  ← 顶部玻璃条
├──────────┬───────────────────────────────────────────────┤
│  🤖      │  群组                       [＋ 新建群组]      │
│  BotGroup│  ┌─────────┐ ┌─────────┐ ┌─────────┐          │
│          │  │ 📋      │ │ 🎨      │ │ 💼      │          │
│  群组    │  │ 产品讨论 │ │ 设计评审 │ │ 投资决策 │          │
│  机器人  │  │ 4成员   │ │ 2成员   │ │ 3成员   │          │
│  设置    │  │ auto   │ │ manual  │ │ RR     │          │
│          │  └─────────┘ └─────────┘ └─────────┘          │
│          │                                               │
│  ───    │  [空状态插画 + 引导文案]                          │
│  用户    │                                               │
└──────────┴───────────────────────────────────────────────┘
```

**机器人管理**：

```
┌──────────────────────────────────────────────────────────┐
│  机器人管理       [搜索框 🔍]      [视图：网格 | 列表]    │
│                                                       │
│  ●● OpenAI / Anthropic / Google / 其他                  │  ← 过滤标签
│                                                       │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐                   │
│  │ 😊      │ │ 🦾      │ │ 🧠      │                   │
│  │ 助手A   │ │ 工程师 │ │ 思考者 │                   │
│  │ GPT-4o  │ │ Claude  │ │ Gemini │                   │
│  │ ▒▒▒▒▒░ │ │ ▒▒▒▒░░ │ │ ▒▒▒▒▒▒ │                   │
│  │ 简洁派  │ │ 严谨派  │ │ 全面派  │                   │
│  └─────────┘ └─────────┘ └─────────┘                   │
└──────────────────────────────────────────────────────────┘
```

**群聊视图**：

```
┌──────────────────────────────────────────────────────────┐
│ 左侧（玻璃栏）                │ 主区                      │
│                              │                          │
│ 📋 产品讨论                  │  😊 助手A · GPT-4o         │
│ ━━━━━━━━━━━━━━━━━━          │  ┌──────────────────┐    │
│ 🤖 GPT-4o-mini  运行中 ●     │  │ 我建议采用敏捷开发 │    │
│ 🤖 Claude                    │  └──────────────────┘    │
│ 🤖 Gemini                    │                          │
│                              │  ┌──────────┐ 🦾 工程师  │
│ ＋ 添加机器人                 │  │ 代码已就绪 │    │
│                              │  └──────────┘    │
│                              │                          │
│ 模式：auto · 轮次 3/6        │         ┌────────────────┐ │
│                              │         │ 好的，继续。  │ 👤 你 │
│                              │         └────────────────┘ │
│                              │                          │
│                              │  [💬 输入消息...] [发送]  │
└──────────────────────────────────────────────────────────┘
```

#### 3.3 关键交互

- **机器人卡片 hover**：上浮 2px + 阴影加深，背景微微彩色化
- **建群向导**：4 步进度条 + 左右切换按钮，可返回上一步
- **机器人添加**：点击群成员头像弹出 emoji 选择 + 模型下拉
- **@机器人触发**：输入框输入 `@` 弹出机器人菜单（用 MentionMenu 组件，参考 Linear/Notion 的体验）
- **流式响应**：每个 token 后追加游标（呼吸动画），完成后游标消失、内容淡入
- **运行状态指示**：群聊顶部显示"3 位机器人正在讨论..."，并在每个正在发言的机器人头像旁加脉冲光晕

---

## Assumptions & Decisions

| 决策 | 取舍 |
|---|---|
| 浅色 + 玻璃拟态 + 柔和 | 用户指定 |
| shadcn/ui copy-paste（不装 npm 包） | 用户指定；好处：构建快、可审计；代价：需手写 Select/Dialog 等 |
| emoji 头像 | 用户指定；零依赖、视觉好 |
| 不引入 Tailwind | 避免重建 PostCSS 链；用 CSS Modules + 全局 CSS 变量 |
| 不引入 Markdown 库 | 用 `marked` CDN（< 10KB），在 ChatBubble 里按需渲染 |
| 不做深色主题 | 用户没要求；预留 CSS 变量钩子，未来加 |
| 后端改动最小化 | 仅加 emoji 列 + `/api/models` 端点 |
| 前端 4 个页面全部重写 | 因为组件库变更，全改更干净 |
| 不做国际化 | 单一中文界面，新加坡审美已通过字体/色调满足 |
| 不做拖拽排序 | 群成员 join_order 后端已有，前端可后续用 dnd-kit |

---

## Verification Steps

1. **后端冒烟**：
   ```bash
   curl http://localhost:8000/api/models -H "Accept: application/json"
   # 应返回 NewAPI 8 个模型
   ```
   ```bash
   curl http://localhost:8000/api/bots
   # 应返回已有机器人列表，每个包含 emoji 字段（默认 🤖）
   ```

2. **前端类型检查**：
   ```bash
   cd frontend && npx tsc --noEmit
   ```

3. **前端构建**：
   ```bash
   docker compose build frontend && docker compose up -d frontend
   docker compose logs -f frontend | head -30
   ```

4. **端到端可视化检查**（用 Playwright 截图）：
   - 访问 http://localhost:3500 → 截首页
   - 访问 http://localhost:3500/bots → 截机器人管理页
   - 访问 http://localhost:3500/group/1 → 截群聊页
   - 验证：玻璃拟态、emoji 头像显示正常、模型下拉可选、按钮 hover 有反馈

5. **响应式**：缩小浏览器到 800px、500px，检查侧栏是否折叠、消息列表可滚

---

## 实施里程碑

| # | 任务 | 估时 |
|---|---|---|
| M1 | 后端：emoji 字段迁移 + `/api/models` 端点 | 30 分钟 |
| M2 | 前端：globals.css 设计系统 + Inter 字体 | 1 小时 |
| M3 | 前端：14 个 shadcn 风格 UI 组件（button/card/dialog/select/...） | 3 小时 |
| M4 | 前端：业务组件（BotCard/GroupCard/ChatBubble/...） | 2 小时 |
| M5 | 前端：4 个页面全部重写 | 2 小时 |
| M6 | Docker 重建、端到端验证、Playwright 截图回归 | 1 小时 |

总计：约 1 个工作日。

---

## 风险与回滚

- **构建风险**：shadcn/ui copy-paste 需要手写 Dialog/Trap focus，可能第一遍构建踩坑。回滚：保留旧页面，仅替换 globals.css 和单个目标页验证。
- **样式冲突**：旧 CSS class 名（`.shell`、`.bubble` 等）会被新系统覆盖，无需手动清理，全局替换即可。
- **数据迁移**：emoji 字段有默认值 `🤖`，存量机器人自动获得该值，无需手动迁移数据。