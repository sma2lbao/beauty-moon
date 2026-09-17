# beauty-moon

基于 [Nx](https://nx.dev) 管理的 monorepo，混合 **TypeScript** 与 **Python** 两种语言；Python 侧统一使用 [uv](https://docs.astral.sh/uv/) 管理依赖与虚拟环境（通过 [nxlv/python](https://github.com/lucasvieirasilva/nx-plugins) 插件集成到 Nx）。

## 环境要求

| 工具 | 版本 | 说明 |
| --- | --- | --- |
| Node.js | >= 20.19（本机 24.x） | 运行 Nx 与 JS 工具链 |
| npm | 随 Node | 安装 JS 依赖 |
| Python | 3.14.x | 各 Python 项目由 `.python-version` 锁定，uv 自动解析 |
| uv | >= 0.5 | Python 包管理 / 虚拟环境 / 构建 |

## 目录结构

```
beauty-moon/
├── packages/
│   ├── ts-utils/               # TypeScript 库示例（tsc 构建 + vitest 测试）
│   │   ├── src/                # 源码
│   │   ├── vitest.config.mts   # 测试配置
│   │   └── package.json
│   └── py-utils/               # Python 库示例（uv + pytest + ruff + hatchling）
│       ├── py_utils/           # Python 包源码
│       ├── tests/              # pytest 测试
│       ├── .python-version     # 锁定 Python 3.14.5
│       ├── pyproject.toml      # 依赖 / 构建 / ruff / pytest 配置
│       ├── uv.lock             # uv 锁文件（提交到 git）
│       └── project.json        # Nx 目标定义
├── nx.json                     # Nx 配置
├── tsconfig.base.json          # TS 路径别名（@beauty-moon/*）
└── package.json                # JS 依赖 + npm workspaces(packages/*)
```

## 常用命令

```sh
npx nx graph                     # 打开项目依赖关系图
npx nx run-many -t build         # 构建所有可构建项目
npx nx run-many -t test          # 运行所有测试
npx nx show projects             # 列出所有项目
```

### TypeScript（ts-utils）

```sh
npx nx build @beauty-moon/ts-utils   # tsc 构建到 dist/
npx nx test @beauty-moon/ts-utils    # vitest 单测
npx nx typecheck @beauty-moon/ts-utils
```

### Python（py-utils）

首次运行任一目标时，uv 会自动在项目目录创建 `.venv` 并按 `uv.lock` 安装依赖。

```sh
npx nx sync py-utils     # uv sync：创建/更新 .venv 与依赖
npx nx lint py-utils     # ruff 检查
npx nx format py-utils   # ruff 格式化
npx nx test py-utils     # pytest（含覆盖率与 HTML 报告）
npx nx build py-utils    # hatchling 构建 wheel/sdist 到 dist/
```

测试报告输出在根目录 `reports/` 与 `coverage/`（已被 git 忽略）。

## 新增项目

### TypeScript

```sh
npx nx g @nx/js:lib packages/<名称> --unitTestRunner=vitest --bundler=tsc
```

### Python（uv）

```sh
npx nx g @nxlv/python:uv-project <项目名> \
  --projectType=library \
  --directory=packages/<目录名> \
  --moduleName=<python模块名> \
  --pyenvPythonVersion=3.14.5 \
  --no-interactive
```

`--projectType=application` 可创建应用类项目（附带 `serve` 目标）。

## Python 依赖管理（uv）

```sh
npx nx run py-utils:add requests      # 新增依赖（uv add）
npx nx run py-utils:add --name pytest --group dev    # 新增 dev 依赖
npx nx run py-utils:remove requests   # 移除依赖
npx nx run py-utils:lock --update     # 更新 uv.lock
npx nx run py-utils:sync              # 同步 .venv
```

依赖统一写在各项目的 `pyproject.toml`（`[project.dependencies]` / `[dependency-groups]`），锁定信息提交 `uv.lock`。

## 其他

- **路径别名**：TS 包在 `tsconfig.base.json` 中以 `@beauty-moon/*` 互相引用。
- **共享 venv**：默认每个 Python 项目独立 `.venv`；如需工作区共享，可运行 `npx nx g @nxlv/python:migrate-to-shared-venv`。
- **发布**：Python 项目已内置 `@nxlv/python` 的 release 集成，TS 包可用 `npx nx release`。
