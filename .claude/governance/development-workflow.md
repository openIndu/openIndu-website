# 开发工作流

> 本文件定义 openIndu-website 聚合仓的开发工作流。

## 需求 → 交付 完整流程

```
prod/requirements.md（需求文档）
        │
        ▼
   需求评审（用户确认）
        │
        ▼
   Fullstack Developer 方案设计
        │
        ├── 拆分为子仓任务
        │
        ├──→ Backend Developer      openIndu-backend/
        │     ├── API 设计与实现
        │     ├── 数据库迁移
        │     ├── 单元测试
        │     └── PR → Arbiter 审核
        │
        ├──→ Frontend Developer     openIndu-admin/ 或 openIndu-portal/
        │     ├── 页面/组件开发
        │     ├── API 对接
        │     ├── 单元测试
        │     └── PR → Arbiter 审核
        │
        ▼
   联调测试（Fullstack Developer 协调）
        │
        ▼
   DevOps Engineer 部署
        │
        ▼
   验收 → 合并 main
```

## 分支策略

| 分支类型 | 命名规范 | 说明 |
|---------|---------|------|
| 功能分支 | `feat/<brief-description>` | 新功能开发 |
| 修复分支 | `fix/<brief-description>` | Bug 修复 |
| 需求分支 | `req/<requirement-id>` | 对应 requirements.md 的需求条目 |

## PR 规范

- 标题格式：`<type>(<scope>): <description>`
- scope: `backend`, `admin`, `portal`, `docs`
- type: `feat`, `fix`, `docs`, `refactor`, `test`
- 必须关联 `prod/requirements.md` 中的需求条目
- 必须通过 CI 检查
- 必须至少一人审核

## 子仓 PR 流程

1. 在子仓内创建分支
2. 开发 + 测试
3. 提交到子仓远程（`git push origin <branch>`）
4. 在 GitHub 上创建 PR（`gh pr create --repo openIndu/<subrepo> --base main --head <branch>`）
5. 审核通过后合并到子仓 main（`gh pr merge <id> --repo openIndu/<subrepo> --merge`）
6. 在聚合仓更新 submodule 指针：`git submodule update --remote`
7. 在聚合仓提交 submodule 指针更新（同样走功能分支 → PR → 合并）

## 代码审查清单

- [ ] 是否符合 `prod/requirements.md` 需求描述
- [ ] 是否有对应的测试
- [ ] API 变更是否更新了文档
- [ ] 数据库变更有迁移脚本
- [ ] 无硬编码的敏感信息
- [ ] 前端组件是否可访问（a11y）
- [ ] 是否遵循子仓自身的代码规范
