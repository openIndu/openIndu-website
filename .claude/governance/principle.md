# Agent 行为守则

> 本文件是 openIndu-website 所有 AI Agent 的 **Rule #1**，
> 任何 Agent 在执行任务前必须首先加载并遵守本守则。
>
> **权威源**：[openIndu/workflow-control-tower · team/principle.md](https://github.com/openIndu/workflow-control-tower/blob/main/team/principle.md)（共 11 条 RULE）。
>
> 本文件为 openIndu-website **项目层**简化版，覆盖最常用的 5 主原则 + 项目层文件写权限矩阵。
> 与权威源冲突时以权威源为准；权威源含完整 11 条 RULE 与 5.1-5.4 细则。

## 核心原则

### 1. 工程基础先行
- 所有代码必须有对应的测试
- API 变更必须更新文档
- 数据库变更必须提供迁移脚本
- 需求变更必须更新 `prod/requirements.md`

### 2. 自动化优先
- 重复操作必须脚本化
- 部署必须容器化（Docker + K8s）
- 构建和发布必须 CI/CD

### 3. 人机协作分级
- **L0**: 纯查询/搜索 → Agent 自主执行
- **L1**: 单文件修改 → Agent 执行 + 事后通知
- **L2**: 多文件修改 → Agent 设计方案 → 人工审核 → 执行
- **L3**: 架构变更 → 人工主导，Agent 辅助

### 4. 验证/评审/安全
- 每次修改必须验证（运行测试、检查 API、检查前端）
- 多 Agent 协作时必须有 arbiter 审核
- 禁止直接 push main，必须走 PR

### 5. 已完成产物不可变
- 已合并到 main 的代码不可随意修改
- 修改需求走新 PR

## 硬约束

| # | 约束 | 执行方式 |
|---|------|---------|
| 1 | 禁止直接 push main/master | branch protection |
| 2 | 只能写入职责范围内的文件 | 路径校验 |
| 3 | 禁止访问工作目录外的文件 | 工作目录限定 |
| 4 | 敏感信息（密钥/密码）禁止硬编码 | 环境变量/Secret |
| 5 | 必须引用 RAG 知识库进行品牌相关开发 | MCP 工具调用 |
| 6 | K8s 清单归口 infra-deploy，本仓禁止保留 deploy/k8s | CI 守卫 + PR |
| 7 | 所有功能开发以 `prod/requirements.md` 为唯一需求来源 | 流程校验 |

## 子仓操作规则

| 规则 | 说明 |
|------|------|
| 子仓代码修改 | 必须 `cd` 进入子仓目录后操作 |
| 子仓分支 | 在子仓内创建 feature 分支，不得直接在 main 上修改 |
| 子仓提交 | 遵循子仓自身的 commit 规范 |
| 聚合仓提交 | 仅提交 submodule 指针变更 + 聚合仓自身文件变更 |

## 文件写权限矩阵

| Agent | 可写目录 |
|-------|---------|
| Backend Developer | `openIndu-backend/`, `prod/` |
| Frontend Developer | `openIndu-admin/`, `openIndu-portal/`, `prod/` |
| Fullstack Developer | 全部子仓 + `prod/` |
| DevOps Engineer | 聚合仓根目录（Dockerfile、CI 配置）；K8s 清单 → infra-deploy |
