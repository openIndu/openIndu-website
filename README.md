# openIndu-website

openIndu 开源工业自动化生态平台的聚合开发仓。

## 子仓库

| 子仓库 | 说明 |
|--------|------|
| [openIndu-backend](https://gitee.com/openIndu/openIndu-backend) | FastAPI 后端服务（REST API + MCP Server） |
| [openIndu-admin](https://gitee.com/openIndu/openIndu-admin) | React 统一管理后台 |
| [openIndu-portal](https://gitee.com/openIndu/openIndu-portal) | React 社区官网前台 |

## 快速开始

```bash
# 克隆聚合仓（含子仓）
git clone --recurse-submodules https://gitee.com/openIndu/openIndu-website.git
cd openIndu-website
```

## 文档

- [CLAUDE.md](CLAUDE.md) — AI Agent 开发入口指南
- [prod/requirements.md](prod/requirements.md) — 平台需求文档（权威需求来源）
- [.claude/governance/](.claude/governance/) — Agent 治理体系

## 治理

本仓受 [workflow-control-tower](https://github.com/agentic-develop-playground/workflow-control-tower) 统一管控。
