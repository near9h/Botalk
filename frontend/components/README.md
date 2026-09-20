# frontend/components

> 共享 React 组件。

## 通用 UI（`ui.tsx`）

- `Button` `Input` `Textarea` `Label` `Select`（含分页模式）
- `Dialog` `DialogContent` `DialogHeader` `DialogFooter`
- `useToast` toast 系统
- `EmptyState` 空状态

## 业务组件

| 组件 | 作用 |
| --- | --- |
| `Sidebar` | 全局侧边栏（含上下文 `SidebarContext`） |
| `Composer` | 输入框 + 附件 + 发送 |
| `ChatBubble` | 单条消息气泡（含引用 chip） |
| `CitedRefsFooter` | 引用脚注 |
| `CitationDrawerContext` | 引用抽屉全局状态 |
| `PdfViewerWithBbox` | PDF.js + bbox 标注 |
| `ChunkPreview` | 切片预览 |
| `AttachmentPreviewDrawer` | 附件预览抽屉 |
| `BotCard` / `BotFormDialog` | bot 卡片 / 编辑 |
| `GroupCard` / `GroupWizard` | 群组卡片 / 向导 |
| `KbUploader` | KB 上传 |
| `SourceCitation` | 单条引用渲染 |
| `TemplatePicker` | 模板选择 |
| `EmojiPicker` | 表情 |

## 约定

- 一个文件一个组件（除非强耦合）
- props 用 TS interface 显式声明
- 内部状态 `useState`；跨组件状态走 Context
- 颜色 / 间距走 CSS 变量（`globals.css`）