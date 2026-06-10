# Luna-Corpus 前端仪表盘设计

## 概述

为 luna-corpus RAG 问答系统构建前端管理仪表盘，使用 React + Vite + shadcn/ui 技术栈。

## 布局结构

```
┌─────────────────────────────────────────────────────────────┐
│ Header: Logo + 健康状态指示器 (MySQL/Chroma/Ollama)          │
├────────────┬────────────────────────────────────────────────┤
│            │                                                │
│  Sidebar   │              Main Content Area                 │
│  - 问答    │                                                │
│  - 文档    │    (根据选中的菜单显示对应内容)                   │
│  - 设置    │                                                │
│            │                                                │
└────────────┴────────────────────────────────────────────────┘
```

## 页面模块

### 1. 问答页面 (Q&A)

- 顶部：输入框 + 发送按钮 + 历史对话切换
- 中部：对话列表（用户问题 + AI 回答 + 来源引用）
- 底部：处理时间显示

### 2. 文档管理页面 (Documents)

- 顶部：添加文档按钮 + 搜索框
- 中部：文档列表（卡片或表格形式）
  - 每条文档：标题、来源、状态标签、创建时间
  - 操作：处理（向量化）、删除
- 支持文档详情查看

### 3. 系统状态页面 (Status)

- 健康状态卡片（MySQL/Chroma/Ollama）
- 服务连接状态指示器（绿色/红色）
- 可添加配置管理（API 地址等）

### 4. 设置页面 (Settings)

- API 配置
- 向量化参数配置
- 其他系统设置

## 组件清单

| 组件 | 说明 |
|------|------|
| `Sidebar` | 左侧导航菜单 |
| `Header` | 顶部栏含 Logo 和状态指示器 |
| `StatusBadge` | 健康状态指示器 |
| `QuestionInput` | 问答输入框 |
| `MessageBubble` | 对话消息气泡 |
| `SourceCard` | 来源引用卡片 |
| `DocumentCard` | 文档卡片 |
| `DocumentTable` | 文档表格视图 |
| `AddDocumentModal` | 添加文档弹窗 |

## API 集成

| 接口 | 用途 |
|------|------|
| `POST /api/v1/qa/query` | 问答查询 |
| `GET /api/v1/documents` | 获取文档列表 |
| `POST /api/v1/documents` | 创建文档 |
| `GET /api/v1/documents/{id}` | 获取文档详情 |
| `DELETE /api/v1/documents/{id}` | 删除文档 |
| `POST /api/v1/documents/{id}/process` | 处理文档 |
| `GET /api/v1/health` | 健康检查 |

## 技术实现

- **框架**: React 18 + Vite
- **UI 库**: shadcn/ui + Tailwind CSS
- **状态管理**: React Query (TanStack Query)
- **路由**: React Router v6
- **HTTP 客户端**: fetch / axios

## 目录结构

```
apps/
  luna-corpus-web/
    src/
      components/
        ui/           # shadcn/ui 组件
        layout/       # Sidebar, Header
        qa/           # 问答相关组件
        documents/    # 文档管理组件
        status/       # 状态监控组件
      pages/
        QAPage.tsx
        DocumentsPage.tsx
        StatusPage.tsx
        SettingsPage.tsx
      lib/
        api.ts        # API 调用
        utils.ts
      App.tsx
      main.tsx
```

## 验收标准

1. 所有 API 集成正常工作
2. 健康状态实时显示
3. 文档 CRUD 功能完整
4. 问答交互流畅
5. 响应式布局适配
