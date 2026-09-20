# frontend/app

> Next.js App Router 路由。

## 路由清单

| 路径 | 文件 | 作用 |
| --- | --- | --- |
| `/` | `page.tsx` | 首页（群组列表） |
| `/bots` | `bots/page.tsx` | 机器人管理（含搜索 + 分页） |
| `/models` | `models/page.tsx` | 模型浏览（NewAPI 中转） |
| `/group/[id]` | `group/[id]/page.tsx` | 单个群组聊天 |
| `/knowledge` | `knowledge/page.tsx` | KB 列表（含新建/重命名/删除） |
| `/knowledge/[id]` | `knowledge/[id]/page.tsx` | KB 详情 + 上传 + chunk 预览 |
| `/skills` | `skills/page.tsx` | 技能中心 |
| `/admin` | `admin/page.tsx` | 管理面板 |
| `/login` | `login/page.tsx` | 登录 |
| `/sse-test` | `sse-test/page.tsx` | SSE 自测页 |

## 顶层文件

- `layout.tsx` — 全局 layout（Sidebar + AuthGate）
- `globals.css` — 全局 CSS 变量

## 约定

- 所有页面 `"use client"`
- 数据获取在 `useEffect` 或事件回调；走 `lib/api.ts`
- 表单错误内联展示
- 长任务用 SSE + EventSource，不用 WebSocket