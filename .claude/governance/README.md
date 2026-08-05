# openIndu-website 治理体系

本目录只保留 openIndu-website 聚合仓**特有**的流程文档。
Agent 行为守则与角色定义均已收敛到公共插件 `openindu-control-tower@openindu`（源仓 [openIndu/control-tower](https://github.com/openIndu/control-tower)），本仓不再保留副本。

## 文件说明

| 文件                      | 说明                                      |
| ------------------------- | ----------------------------------------- |
| `development-workflow.md` | 开发工作流定义（聚合仓 + submodule 特有） |

> `principle.md` 已于 PR #167 删除 —— 守则唯一权威源是插件的 `/principle`（11 条 RULE）。
> 任何任务第一步必须调用 `/principle`；本仓不得另立守则副本（RULE 1）。

## Agent 角色体系

角色 agent 由插件提供（v5.2.0 共 20 个，零业务绑定），本仓 `.claude/agents/` 已于 PR #167 清空。

| 域          | Agent                                                                |
| ----------- | -------------------------------------------------------------------- |
| 治理        | `control-tower`、`manager`、`arbiter`                                |
| 需求 / 设计 | `business-analyst`、`product-manager`、`architect`、`ui-ux-designer` |
| 构建        | `backend`、`frontend`、`edge`、`station-control`                     |
| 质量        | `reviewer`、`test`、`security`、`inspector`                          |
| 数据 / 洞察 | `data`、`bi-analyst`、`codebase-analyst`                             |
| 运维 / 发布 | `ops`、`release`                                                     |

对应到本仓的写权限边界见 [`CLAUDE.md`](../../CLAUDE.md) 顶部的「文件写权限矩阵」。

## 开发流程

```
需求（prod/requirements.md）
    │
    ▼
codebase-analyst 预检（是否已存在实现 → 调整范围）
    │
    ▼
business-analyst → product-manager → architect
    │  产物写入 design/{business,product,architecture}/
    │
    ├──→ backend  ──→ 子仓 PR ──→ reviewer / arbiter 审核 ──→ 合并
    │
    └──→ frontend ──→ 子仓 PR ──→ reviewer / arbiter 审核 ──→ 合并
    │
    ▼
聚合仓 submodule 指针 PR → /build 构建镜像 → infra-deploy PR → 集群 apply
（RULE 11 完整交付链路，可用 /delivery-check 生成完成度清单）
```

> `codebase-analyst` 预检是 SDLC 试跑发现的首要缺口，详见 [`design/pilot-findings.md`](../../design/pilot-findings.md)。

## 与 control-tower 的关系

```
openIndu/control-tower（大脑 / 权威源，private）
    │  marketplace: openindu
    │  plugin: openindu-control-tower（守则 + 20 agent + skill + push-main hook）
    ▼
openIndu-website（聚合仓 / 开发入口）
    │
    ├── openIndu-backend（submodule）
    ├── openIndu-admin（submodule）
    ├── openIndu-portal（submodule）
    └── openIndu-studio（submodule）
```

- **control-tower** 维护守则（`/principle`）、角色 agent、流程 skill 和 `route.json`（仓库路由）
- 守则修改走 control-tower 的 `spec/` 草稿 → arbiter 审核 → `revision/` 记录 → PR，不在子仓改
- 子仓获取更新：`/plugin update openindu-control-tower@openindu`
- 本仓只保留插件**没有等价物**的资产：`development-workflow.md` 与 `.claude/commands/build.md`（覆盖 RULE 11 ④+⑤，插件 `/build` 只做 ④）
