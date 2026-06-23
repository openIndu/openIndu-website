# openIndu-website

openIndu 开源工业自动化生态平台的聚合开发仓，通过 git submodule 统一管理前后端子仓库。

## 子仓库

| 子仓库 | 路径 | 技术栈 | 状态 |
|--------|------|--------|:---:|
| [openIndu-backend](https://github.com/openIndu/openIndu-backend) | `openIndu-backend/` | FastAPI + PostgreSQL + Milvus | 🟢 活跃 |
| [openIndu-admin](https://github.com/openIndu/openIndu-admin) | `openIndu-admin/` | React 19 + Tailwind CSS 4 + shadcn/ui | 🟢 活跃 |
| [openIndu-portal](https://github.com/openIndu/openIndu-portal) | `openIndu-portal/` | React 19 + Tailwind CSS 4 + shadcn/ui | 🟢 活跃 |

## 快速开始

```bash
# 1. 克隆聚合仓（含所有子仓）
git clone --recurse-submodules https://github.com/openIndu/openIndu-website.git
cd openIndu-website

# 2. 从模板创建本地环境变量
cp .env.example .env
# 编辑 .env，填写 OSS / SMS 等配置

# 3. 一键启动所有服务
docker compose up -d --build
```

## 本地服务端口

| 服务 | 端口 | 说明 |
|------|:---:|------|
| openIndu-portal | `3000` | 社区官网前台 |
| openIndu-admin | `3001` | 统一管理后台 |
| Web API | `8004` | REST API |
| MCP Server | `8005` | Claude Code 知识检索（内网） |
| PostgreSQL | `5432` | 业务数据库 |
| Milvus | `19530` | 向量数据库 |

默认管理员：手机号 `13800000000`，验证码 `888888`（开发环境固定）。

## 更新子仓

```bash
git submodule update --remote --recursive
```

## 文档

- [CLAUDE.md](CLAUDE.md) — AI Agent 开发入口指南
- [prod/requirements.md](prod/requirements.md) — 平台需求文档（权威需求来源）
- [.claude/governance/](.claude/governance/) — Agent 治理体系

## 治理

本仓受 [workflow-control-tower](https://github.com/agentic-develop-playground/workflow-control-tower) 统一管控。禁止直接 push `main`，所有变更须走功能分支 + PR。K8s 部署清单归口 [openIndu/infra-deploy](https://github.com/openIndu/infra-deploy)。
