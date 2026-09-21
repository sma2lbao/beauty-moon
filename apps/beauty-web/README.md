# beauty-web

美月 Beauty Moon 品牌前台站点（包名 `@beauty/web`）。React + TypeScript SPA，位于
monorepo 的 `apps/beauty-web` 目录下，由 npm workspaces 管理、Nx 识别。

## 技术栈

| 类别 | 选型 |
| --- | --- |
| 框架 | React 19 + TypeScript |
| 路由 | react-router v8（`BrowserRouter` + 嵌套路由） |
| 数据 | @tanstack/react-query（服务端状态） |
| 样式 | Tailwind CSS v4（`@tailwindcss/vite` 插件，CSS 变量主题） |
| 组件 | shadcn/ui（new-york 风格，源码直接放进 `src/components/ui`） |
| 构建 | Vite 8 |

## 常用命令

在仓库根目录运行（或 `cd apps/beauty-web` 后用 npm run）：

```sh
npx nx dev @beauty/web        # 启动 dev server（默认 5173 端口）
npx nx build @beauty/web      # tsc 类型检查 + vite 生产构建
npx nx preview @beauty/web    # 预览生产构建
npx nx typecheck @beauty/web  # 仅类型检查
```

## 目录结构

```
apps/beauty-web/
├── components.json            # shadcn/ui CLI 配置（npx shadcn add <组件>）
├── index.html
├── vite.config.ts              # react + tailwindcss 插件，@ -> src 别名
└── src/
    ├── main.tsx                # 入口：QueryClientProvider + BrowserRouter
    ├── app.tsx                 # 路由表（SiteLayout 嵌套布局）
    ├── index.css               # Tailwind v4 主题：色板 / 字体 / 满月光盘样式
    ├── components/
    │   ├── layout/             # 页头、页脚、站点布局
    │   └── ui/                 # shadcn 组件（button / card / skeleton）
    ├── lib/
    │   ├── products.ts         # mock 产品接口（后续替换为真实 API）
    │   └── utils.ts            # cn()（clsx + tailwind-merge）
    └── pages/
        ├── home.tsx            # / 首页：品牌 hero + 系列 teaser
        ├── products.tsx        # /products 产品列表（useQuery + 心愿单交互）
        ├── about.tsx           # /about 品牌故事
        └── not-found.tsx       # 404
```

## 约定

- **路径别名**：应用内用 `@/` 指向 `src/`（vite.config.ts 与 tsconfig.json 保持同步）。
- **shadcn/ui**：组件以源码形式维护在 `src/components/ui`，可随时用
  `npx shadcn@latest add <组件>` 追加。
- **数据请求**：页面统一通过 `useQuery` + queryKey 取数，`src/lib/products.ts`
  是唯一的 mock 层，接后端时只改这一个文件。
- **主题**：色板定义在 `src/index.css` 的 `:root` / `.dark`（oklch），
  页头按钮可切换深浅色，偏好写入 localStorage。
