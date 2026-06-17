# openIndu-website 治理体系

本目录包含 openIndu-website 聚合仓的 AI Agent 治理规范。

## 文件说明

| 文件 | 说明 |
|------|------|
| `principle.md` | Agent 行为守则（Rule #1） |
| `development-workflow.md` | 开发工作流定义 |

## Agent 角色体系

openIndu-website 有两大类 Agent：

### Meta 层（治理）
- **Fullstack Developer**: 全栈协调、跨子仓任务分派、架构评审
- **Arbiter**: 代码审核、跨模块仲裁（由 workflow-control-tower 统一管理）

### Domain 层（开发）
- **Backend Developer**: FastAPI 后端开发（openIndu-backend）
- **Frontend Developer**: React 前端开发（openIndu-admin + openIndu-portal）
- **DevOps Engineer**: 部署与运维（Docker、K8s、CI/CD）

## 开发流程

```
需求（prod/requirements.md）
    │
    ▼
Fullstack Developer 方案设计
    │
    ├──→ Backend Developer ──→ PR ──→ Arbiter 审核
    │
    └──→ Frontend Developer ──→ PR ──→ Arbiter 审核
    │
    ▼
联调测试 → DevOps 部署 → 验收
```

## 与 workflow-control-tower 的关系

```
workflow-control-tower（大脑 / 权威源）
    │
    │  下发 Agent 行为守则、流程模板
    │
    ▼
openIndu-website（聚合仓 / 开发入口）
    │
    ├── openIndu-backend（submodule）
    ├── openIndu-admin（submodule）
    └── openIndu-portal（submodule）
```

- **workflow-control-tower** 维护 `team/principle.md`（Agent 守则权威源）和 `route.json`（仓库路由）
- **openIndu-website** 的 `.claude/governance/principle.md` 是对权威源的项目层覆盖，保持一致
- Agent prompt 的权威定义在 workflow-control-tower，本仓的 `.claude/agents/` 为项目特定 Agent
