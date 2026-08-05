# openIndu-website — 聚合仓项目指南

> **Rule #1（元规则）**：本仓遵守 openIndu 社区统一守则（11 条 RULE），由公共插件 `openindu-control-tower@openindu` 提供。**任何任务第一步：调用 `/principle` 加载守则。** 本仓不得自立守则副本；守则修改走 `openIndu/control-tower` 的 spec + arbiter 审核流程。
>
> **权威需求文档**：[`prod/requirements.md`](prod/requirements.md) — 所有功能开发的唯一需求来源。
>
> **硬约束**：禁止直接 `git push` 到 `main`/`master`，必须走 PR；
> K8s 部署清单归口 [openIndu/infra-deploy](https://github.com/openIndu/infra-deploy)。
>
> **治理体系**：Agent 角色定义由公共插件 `openindu-control-tower@openindu` 提供（20 个 SDLC 角色 agent）；开发流程 + PR/执行/通信规范见
> [`.claude/governance/`](.claude/governance/README.md)（保留 development-workflow.md 等仓库特有流程文档）。
>
> **管控中心**：本仓受 [openIndu/control-tower](https://github.com/openIndu/control-tower)
> 统一管控，Agent 行为守则权威源为 `/principle`（11 条 RULE，含 push-main 禁令 / K8s 归口 infra-deploy / Gitee PR 英文 /
> 生产 SQL guard / 修复完整链路 等 openIndu 硬约束）。
>
> **文件写权限矩阵**（仓库特有约束，从本地 principle.md 折入）：
>
> | Agent role | 可写目录 |
> |---|---|
> | backend | `openIndu-backend/`, `prod/` |
> | frontend | `openIndu-admin/`, `openIndu-portal/`, `prod/` |
> | manager / architect | 全部子仓 + `prod/`（设计 + 协调） |
> | ops / release | 聚合仓根目录（Dockerfile、CI 配置）；K8s 清单 → infra-deploy |

## 0. 工作目录约定

**工作目录**: `openIndu-website`

**重要约定**:
- 所有文件操作必须限制在 `openIndu-website` 工作目录内
- 所有相对路径均以 `openIndu-website` 为根目录
- 子仓库通过 git submodule 挂载，Agent 操作子仓代码前需先 `cd` 进入对应子目录

---

## 1. 项目概述

**openIndu-website** 是 openIndu 开源工业自动化生态平台的**聚合开发仓**，通过 git submodule 统一管理以下子仓库：

| 子仓库 | 路径 | 技术栈 | 说明 |
|--------|------|--------|------|
| [openIndu-backend](https://github.com/openIndu/openIndu-backend) | `openIndu-backend/` | FastAPI + PostgreSQL + Milvus | REST API + MCP Server |
| [openIndu-admin](https://github.com/openIndu/openIndu-admin) | `openIndu-admin/` | React 19 + Tailwind CSS 4 + shadcn/ui | 统一管理后台 |
| [openIndu-portal](https://github.com/openIndu/openIndu-portal) | `openIndu-portal/` | React 19 + Tailwind CSS 4 + shadcn/ui | 社区官网前台 |

### 平台服务总览

| 服务 | 域名/端口 | 定位 | 用户 |
|------|------|------|------|
| openIndu-portal | `openindu.com` | 社区官网前台 | 所有人（含未登录） |
| openIndu-admin | `admin.openindu.com` | 统一管理后台 | 已认证用户（按角色分级） |
| openIndu-backend (Web) | `api.openindu.com` | REST API（Portal + Admin） | 前端应用 |
| openIndu-backend (MCP) | `:8005` | MCP Server（Claude Code 知识检索） | Claude Code / AI Agent |

---

## 2. 项目结构

```
openIndu-website/
├── CLAUDE.md                         # 本文件：聚合仓入口指南
├── README.md                         # 项目说明
├── prod/                             # 生产规范（权威文档源）
│   └── requirements.md               # 平台需求文档（所有功能开发的唯一需求来源）
├── .claude/
│   ├── settings.json                 # Hooks 配置（防 push main + lint）
│   ├── settings.local.json           # 权限配置
│   ├── agents/                       # Agent 定义
│   │   ├── backend-developer.md      # FastAPI 后端开发
│   │   ├── frontend-developer.md     # React 前端开发
│   │   ├── fullstack-developer.md    # 全栈协调（跨前后端任务）
│   │   └── devops-engineer.md        # 部署与运维
│   └── governance/
│       ├── README.md                 # 治理体系说明
│       ├── principle.md              # Agent 行为守则
│       └── development-workflow.md   # 开发工作流
├── openIndu-backend/                 # git submodule: FastAPI 后端
├── openIndu-admin/                   # git submodule: React 管理后台
├── openIndu-portal/                  # git submodule: React 官网前台
└── .gitmodules
```

---

## 3. 架构总览

```
                        ┌─────────────────┐
                        │   Nginx Ingress  │
                        └────────┬────────┘
                                 │
          ┌──────────────────────┼──────────────────────┐
          ▼                      ▼                      ▼
   openindu.com          admin.openindu.com      api.openindu.com
   ┌──────────┐          ┌──────────┐            ┌──────────┐
   │ Portal   │          │ Admin    │            │ Web API  │
   │ React    │          │ React    │            │ FastAPI  │
   │ Nginx    │          │ Nginx    │            │ :8004    │
   │ :80      │          │ :80      │            └────┬─────┘
   └──────────┘          └──────────┘                 │
                                                      │
            ┌─────────────────────────────────────────┤
            │                 │                       │
            ▼                 ▼                       ▼
      ┌──────────┐    ┌──────────┐            ┌──────────┐
      │ MCP Svr  │    │PostgreSQL│            │阿里云 OSS │
      │ FastAPI  │    │ :5432    │            │  (私有)   │
      │ :8005    │    └──────────┘            │Presigned  │
      │(内网only)│                            │URL 直下载  │
      └────┬─────┘                            └──────────┘
           │
      ┌────┴──────────┐
      │    Milvus      │    ┌──────────┐
      │    :19530      │    │ RAG Svr  │
      │    向量数据库    │    │ PDF解析   │
      └───────────────┘    │ 向量索引   │
                           └──────────┘
```

---

## 4. 技术栈汇总

| 层 | 技术 | 说明 |
|----|------|------|
| Portal 前端 | React 19 + TypeScript 5 + Vite 6 + Tailwind CSS 4 + shadcn/ui | 社区官网 |
| Admin 前端 | React 19 + TypeScript 5 + Vite 6 + Tailwind CSS 4 + shadcn/ui | 管理后台 |
| 后端 Web API | Python 3.11+ + FastAPI 0.115+ + SQLAlchemy 2.x | REST API |
| 后端 MCP | Python 3.11+ + FastAPI + MCP Python SDK 1.x | Claude Code 知识检索 |
| 数据库 | PostgreSQL 15 | 业务数据 |
| 向量库 | Milvus 2.4 | 知识库向量存储 |
| 对象存储 | 阿里云 OSS（MinIO 开发环境） | PDF + 软件包 |
| RAG | PyMuPDF + BGE-M3 + sentence-transformers | PDF 解析与向量化 |
| 短信 | 阿里云短信 / 腾讯云短信 | 验证码发送 |

---

## 5. 开发约定

1. **需求驱动** — 所有功能开发以 `prod/requirements.md` 为唯一需求来源
2. **方案设计先行** — 执行任务前进行方案设计，复杂任务使用 Plan agent
3. **任何修改必须经过用户同意** — 不得擅自修改代码
4. **测试驱动** — 每次修改代码必须通过测试用例
5. **子仓隔离** — 修改子仓代码时在子仓内创建分支、提交、PR
6. **API 端点验证** — 新增 API 必须验证前后端调用通畅
7. **文档同步** — 架构变更后及时更新 `prod/requirements.md`
8. **清理临时文件** — 脚本执行完成后自行清理

---

## 6. 子仓操作指南

### 克隆聚合仓（含子仓）

```bash
git clone --recurse-submodules https://github.com/openIndu/openIndu-website.git
```

### 更新子仓

```bash
git submodule update --remote --recursive
```

### 在子仓中开发

```bash
cd openIndu-backend
git checkout -b feat/my-feature
# ... 开发 ...
git add .
git commit -m "feat: xxx"
git push origin feat/my-feature
# 在 GitHub 上创建 PR
gh pr create --repo openIndu/<subrepo> --base main --head feat/my-feature
```

---

## 7. 部署方案

### 部署文件分层

| 文件类型 | 放置位置 | 说明 |
|---------|---------|------|
| `Dockerfile` | 各子仓 | 构建逻辑与代码强绑定，随代码变更 |
| `nginx.conf` | Portal / Admin 子仓 | 前端路由规则各不相同 |
| `docker-compose.yml` | 聚合仓根目录 | 跨子仓服务编排（依赖、端口、网络） |
| `.env` | 聚合仓根目录 | 本地开发环境变量（Git 忽略，不提交） |
| `.env.example` | 聚合仓根目录 | 环境变量模板（Git 跟踪） |
| K8s 部署清单 | `infra-deploy` 仓 | 生产部署，不存本仓 |

### 开发环境启动

```bash
# 1. 克隆聚合仓（含子仓）
git clone --recurse-submodules https://github.com/openIndu/openIndu-website.git

# 2. 从模板创建 .env
cp .env.example .env

# 3. 一键启动所有服务
docker compose up -d --build
```

### 本地服务端口

| 服务 | 端口 | 说明 |
|------|:---:|------|
| openIndu-portal | `3000` | 社区官网前台 |
| openIndu-admin | `3001` | 管理后台 |
| Web API | `8004` | REST API |
| MCP Server | `8005` | Claude Code 知识检索 |
| PostgreSQL | `5432` | 业务数据库 |
| Milvus | `19530` | 向量数据库 |

### 存储架构

| 场景 | 业务文件存储 | Milvus 内部存储 |
|------|:---:|:---:|
| **本地开发** | 本地文件系统 (`STORAGE_BACKEND=local`) | MinIO（容器内，不暴露端口） |
| **生产环境** | 阿里云 OSS (`STORAGE_BACKEND=s3`) | MinIO（K8s 内部署） |

切换存储后端只需修改 `.env` 中的 `STORAGE_BACKEND` 环境变量，无需改代码。

### 默认管理员

启动后自动创建管理员账号：

| 字段 | 值 |
|------|------|
| 手机号 | `13800000000` |
| 验证码 | `888888`（开发环境固定） |
| 角色 | `admin` |

---

## 8. 配置参考

### 环境变量（开发环境）

见 `.env.example`（聚合仓根目录）。开发环境配置模板，复制为 `.env` 后使用。

---

**最后更新时间**: 2026-06-20
**文档版本**: 0.3.0
**平台版本**: 0.1.0-SNAPSHOT
