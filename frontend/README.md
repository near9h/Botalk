# frontend

> Next.js 14 (App Router) + TypeScript 前端。

## 目录

| 子目录 | 作用 | 模块 README |
| --- | --- | --- |
| `app/` | 路由（App Router） | [app/README.md](app/README.md) |
| `components/` | 共享组件（20 个） | [components/README.md](components/README.md) |
| `lib/` | 客户端工具（api / types） | [lib/README.md](lib/README.md) |

## 顶层文件

| 文件 | 作用 |
| --- | --- |
| `Dockerfile` | 多阶段构建：deps → build → runtime |
| `next.config.js` | Next.js 配置（output: standalone） |
| `tsconfig.json` | TypeScript 配置 |
| `package.json` | 依赖 |

## 启动

```bash
# 本地
npm install
npm run dev   # http://localhost:3000

# 生产（容器内）
npm run build
npm start
```

> 容器内通过 Nginx 反代到 3500。`NEXT_PUBLIC_API_BASE` 必须是浏览器可访问的地址。

## 文档入口

- 设计：[.trae/documents/05-design/](../.trae/documents/05-design/)
- UI：[.trae/documents/05-design/ui-redesign.md](../.trae/documents/05-design/ui-redesign.md)