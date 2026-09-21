# ADR — Issue #199：Admin Settings 页下线，Embedding/RAG 配置归属重整（跨 admin / backend / studio）

| | |
|---|---|
| Status | **Approved**（2026-09-21，用户已确认签字确认清单第 1/2/3/5 项：D1 按命名约定对齐执行、D3 按展示层合并解读执行、D2 bake period 定为 4 周、`requirements.md` §4.3.7 RAG Server 叙述修正并入 `WEBSITE-1`。清单第 4 项——两处"需 product-manager 裁决"（`deleted` 墓碑行留存策略、studio 服务化时机）——用户未在本次表态，按 ADR 原文本就不阻塞本次 6 个可执行 PR 处理，留待另行安排） |
| Date | 2026-09-21 |
| Scope | `openIndu-admin`（Settings 页 + `configApi`）+ `openIndu-backend`（`/config` 路由 + `system_configs` 表 + embedding 配置来源）+ `openIndu-studio`（`local-rag-mcp` 文档/命名约定）+ `openIndu-website`（`prod/requirements.md` 口径修正） |
| Owner | architect |
| Re-review | 2026-12-21，或以下任一提前触发：① `BACKEND-3`（`DROP TABLE system_configs`）执行前必须重新过一遍本 ADR；② 用户对 D1/D3 的确认意见与本文假设不符；③ `openIndu-studio` 因 §2.2.8 工程产物服务立项而需要真正服务化时 |

> **2026-09-21 更新：用户已批准，本文转入 Approved。** 签字确认清单第 1/2/3/5 项均已按推荐方案确认（见上方 Status 行），`ADMIN-1`/`ADMIN-2`/`BACKEND-1`/`BACKEND-2`/`WEBSITE-1`/`STUDIO-1` 六个 PR 现可按 Appendix A 的排期开始实现；`BACKEND-3`（`DROP TABLE`）仍按 D2 门禁延后，不在本次批准范围内。清单第 4 项两处"需 product-manager 裁决"尚未表态，不阻塞已批准的六项。以下正文保留提案原貌（含"计划""拟""建议"等措辞），作为决策记录不做回溯性改写。
>
> **为什么是一份 ADR 而不是三份**：D1（studio 归属模型）决定了 D2 要迁移到哪里、迁移的东西有多重；D2 的排期又决定了 D3 能不能独立于它先/后落地。三者共享同一组"已核实事实"（尤其是下面这条），拆开会重复贴一遍上下文。**D3 例外**：它在实现上与 D1/D2 完全无文件重叠、可独立成 PR、可独立回滚（见 Appendix B），之所以仍放在同一份 ADR 里，只是因为它来自同一个 GH issue、同一个 Admin 页面组。

---

## Context

### 1. Issue 原文与歧义

> openIndu/openIndu-website#199："the admin frontend about settings page should be removed, including the Embedding model and remove the pending and synced in pending, and move it to openindu-studio."

用户已确认按方案 C 执行。但 issue 原文里 "remove the pending and synced in pending" 在当前代码里找不到字面对应——`pending`/`synced` 只出现在 Document Management（`DocumentList.tsx`）的同步状态徽标里，而不是 Settings 页。这段文字对应到哪个具体改动，是 D3 要处理、且**必须标注为本文解读、需用户另行确认**的问题，见 D3。

### 2. Settings 页现状（已读代码核实）

`openIndu-admin/src/app/pages/settings/SettingsView.tsx`（63 行，路由 `/settings`，仅 admin 可见）渲染 5 个字段：`embedding_model`、`embedding_device`（cpu/cuda）、`rag_chunk_size`、`rag_chunk_overlap`、`rag_sync_interval`。表单默认值硬编码为 `{embedding_model: 'BAAI/bge-m3', embedding_device: 'cpu', rag_chunk_size: '512', rag_chunk_overlap: '50', rag_sync_interval: '60'}`（`SettingsView.tsx:9-15`）。

后端 `GET/PUT /api/v1/config`（`openIndu-backend/app/api/config.py`，43 行）读写 `system_configs` 表（`app/models/system_config.py`，24 行）——一张通用 `config_key`/`config_value` KV 表，这 5 行只是前端恰好渲染的那几行。

`openIndu-website/prod/requirements.md` §3.3.7 把这 5 个字段归类为"业务参数"层，声称"存储位置=数据库 `system_configs` 表 / 修改方式=Admin 后台页面 / **生效方式=即时生效**"。

### 3. 核心发现：这 5 个字段今天不驱动任何真实行为（已用穷举 grep 核实，不是推断）

对整个 `openIndu-backend` 做 `SystemConfig|system_configs` 全文 grep，命中的只有：模型定义本身、`alembic/env.py`/`web_app.py` 里的 `# noqa: F401` 占位 import、以及 `app/api/config.py` 的纯 CRUD 代码。**没有任何其他文件读取过 `system_configs` 表。** 真正驱动同步行为的是完全独立的两套机制：

| 字段（Settings 页） | 写入位置 | 谁真正读取 / 实际生效值 |
|---|---|---|
| `embedding_model` | `system_configs.config_value` | 无人读取。`rag_sync_service.py:41` 与 `milvus_service.py:27` 各自硬编码字符串字面量 `"BAAI/bge-m3"`（两处独立硬编码，非共享常量） |
| `embedding_device` | 同上 | 无人读取。`rag_sync_service.py:35-40` 自行 `torch.cuda.is_available()` 探测；`milvus_service.py:27` 无条件硬编码 `device="cpu"`——两条同步/查询路径的设备选择逻辑本身就互不一致，与该字段完全无关 |
| `rag_chunk_size` / `rag_chunk_overlap` | 同上 | 无人读取。`rag_sync_service.py:56-57` 硬编码 `CHUNK_SIZE_TOKENS=400` / `CHUNK_OVERLAP_TOKENS=50`（**按 token 计，不是按字符**——而 Settings 页表单默认值 "512"/"50" 是按**字符**计的旧口径，两者单位都对不上；`prod/rag-optimization-design.md` §5.2 记录了这次"512 字符→400 token"的历史改口径，Settings 页从未跟着更新） |
| `rag_sync_interval` | 同上 | 无人读取。真正生效的是 `app/core/config.py:60` 的 `settings.RAG_SYNC_INTERVAL_MINUTES`（`.env` 环境变量，与这个同名但不同源的 DB 键毫无关系） |

也就是说：**Settings 页从第一天起就没有控制过它声称控制的东西**。`prod/requirements.md` §3.3.7 "即时生效" 的说法与代码不符，是一处此前无人发现的文档/实现落差。这个发现直接决定了 D2 的答案：迁移这 5 个 KV 值的数据风险≈0，因为没有下游依赖它们。

**旁证（非本 issue 要求，仅作为佐证记录）**：`app/web_app.py::_init_milvus_collection()` 第 77 行建表时把向量字段写死为 `dim=1024`（BGE-M3 的输出维度）。即便 `embedding_model` 字段真被接上读取逻辑，换成输出维度不同的模型也需要 Milvus collection 重建 + 全量重嵌入——这本身就不是一个"表单填完即时生效"量级的参数，Settings 页对它的呈现方式在架构上就是错的，不只是"没接线"。

### 4. `sync_status` 的真实状态机（已读代码核实，5 个值，不是 UI 呈现的 4 个）

`Document.sync_status`（`app/models/document.py:22`）默认值 `"pending"`。已发现的赋值点：

| 状态 | 赋值位置 | 触发场景 |
|---|---|---|
| `pending` | 列默认值 | 上传后从未同步 / 或值为空时 `sync.py:55` 的兜底 `status or "pending"` |
| `syncing` | `documents.py:94`（上传后台任务）、`documents.py:345`（手动单文档同步端点，带 409 并发守卫：`if doc.sync_status == "syncing": raise 409`） | 仅"上传触发"和"手动点同步按钮"两条路径会显式置为 `syncing` |
| `synced` | `documents.py:97`、`sync_task.py:73` | 同步成功 |
| `failed` | `documents.py:107`、`sync_task.py:92` | 同步失败（含重试耗尽） |
| `deleted` | `sync_task.py:55` | 定时扫描发现 OSS 对象已被带外删除，但 DB 行仍保留（墓碑行，非 API 硬删除） |

**关键细节**：定时任务路径（`sync_task.py::run_sync_once`，每 60 分钟跑一次的那个）**从未把状态显式置为 `syncing`**——一个文档在被批量扫描同步处理的全程，状态就停留在 `pending`（或上次的 `failed`）不变，直到处理结束才跳到终态。`syncing` 只在"上传后台任务"和"手动点同步"这两条**单文档、admin 触发**的路径上出现。前端 `DocumentList.tsx` 又把 `pending`/`syncing`/`deleted` 三者统一渲染成同一种 `warning`（黄色）徽标样式（`item.sync_status === 'synced' ? 'success' : item.sync_status === 'failed' ? 'destructive' : 'warning'`，`DocumentList.tsx:426`）——即代码层面，这几个状态今天的视觉/语义区分度本来就很低。这条事实是 D3 的主要依据。

**顺带发现的既存缺陷（本 ADR 不负责修，仅记录，且此处已按内部复核意见修正过一次表述）**：`_sync_uploaded_document`（`documents.py:87-114`）只在 Python 异常被捕获时才把 `syncing` 改回 `failed`；如果后端进程在同步进行中被硬杀（例如部署导致的 pod 重启），该文档的 `sync_status` 会残留为 `syncing`。若定时任务已启用（`RAG_SYNC_ENABLED=true`），下一次 `scan_documents()` 扫描会把任何非 `synced` 的文档（含 `syncing`）重新排入同步队列（`rag_sync_service.py` 的 `elif db_doc.sync_status != "synced":` 分支），文档本身会在下一个周期自愈——**真正会被永久卡住的是 UI 的手动重试按钮**：`documents.py` 手动同步端点的 409 守卫只要看到 `sync_status == "syncing"` 就拒绝，在下一次定时扫描把状态翻正之前，管理员点"同步"会一直拿到 409。若定时任务被禁用（`RAG_SYNC_ENABLED=false` 的资源受限节点），则没有自愈机制，此时才需要手工改库。这个 bug 与本 issue 无关、早于本次改动存在，列入下方债务台账。

### 5. `openIndu-studio` 今天没有可以承接的落点（已读代码 + 已读该仓 CLAUDE.md 核实）

- `prod/requirements.md` §2.2.8 原文："`openIndu-studio` 当前为纯 Python 引擎库（`converters/`，**无 server/API/内置 LLM**），其'AI 大脑'目前是开发者本地的 Claude Code。" ——这是权威需求文档自己的表述，不是本次分析的推断。
- `openIndu-studio/local-rag-mcp/server.py` 是 **stdio transport**，由 Claude Code 按需拉起的开发者本机进程（"Claude Code 自动启动，无需手动运行"，见文件头注释），**从未作为网络服务部署过**。它连接的是 `controller_knowledge` collection，`openIndu-backend` 连接的是 `plc_knowledge` collection——两个独立 collection，各自独立配置 `MILVUS_HOST`/`PORT`/`EMBEDDING_MODEL`/`EMBEDDING_DEVICE` 环境变量，代码零共享（`server.py` 里 `_search()` 函数的注释直接写着"来自 openIndu-website milvus_service.py"——是**复制粘贴**过来的，不是共享调用）。
- 两个 collection 服务两类不同消费者（backend 的给官网聊天 widget 用，studio 的给 Claude Code agent 用），彼此没有正确性耦合——**不存在"两边必须用同一个 embedding 模型才能工作"的技术约束**（不同 collection，各自独立可寻址）。"迁到 studio 更自然" 更可能是一种"同属 PLC/controller 知识领域"的直觉，而不是任何现存的技术依赖。
- **反向事实**：`openIndu-studio/CLAUDE.md` 顶部横幅写着"重要变更：`frontend`/`backend`/`rag-server`/`mcp-server` **已迁移至 openIndu-website**"——即 RAG 基础设施此前刚经历过一次**从 studio 迁出、迁入 website** 的架构调整。本 issue 要求的方向与那次迁移相反。这不构成否决理由，但意味着"迁回 studio"需要一个比"顺理成章"更具体的技术理由，而不能只援引"之前好像是在 studio"。

### 6. Admin 导航结构里 `/settings` 与 `/settings/tags` 是两个不同功能，不能混删

`routes.tsx` 里 `/settings`（`SettingsView.tsx`，对应 requirements §3.3.7）和 `/settings/tags`（`TagsView.tsx`，品牌/分类/系列标签管理，对应 §3.3.6）是兄弟路由，共享 `Sidebar.tsx` 里同一个"系统配置"折叠分组（`settingsSubItems`，`Sidebar.tsx:30-36`）。`TagsView.tsx` 是活跃功能（`DocumentList.tsx` 的品牌/分类/系列筛选器直接依赖它），**不在本次退役范围内**，删除时必须只动 `/settings` 这一项，分组容器和 `/settings/tags` 原样保留。

---

## 硬约束（贯穿全部决策）

**C1｜生产服务不得依赖只在开发者本机运行的 stdio 工具。** `openIndu-backend` 是常驻 K8s 部署的 FastAPI 服务；`local-rag-mcp/server.py` 是 stdio transport、按需拉起的开发者本机进程，从未部署为网络服务。任何要求 backend 在请求路径或调度任务里"调用 studio"的方案，在 studio 真正长成一个可寻址的部署单元之前都不成立——这不是本文的保守选择，是当前基础设施状态下的硬约束。

**C2｜Milvus collection 向量维度建表时固定，换 embedding 模型是 schema 迁移级操作，不是热更新参数。** 见 Context §3 旁证。任何方案都不得在文档或 UI 里暗示"改个下拉框就能换模型"。

**C3｜跨仓部署不是原子的，退役后端路由前，前端必须先停止调用它。** `openIndu-admin` 与 `openIndu-backend` 是两个独立镜像、两条独立的 RULE 11 交付流水线，同一次"cutover"必然分两次部署落地，中间有先后顺序。

**C4｜本次改动不得在同一个 PR 里删除 `system_configs` 表或表里的数据行。** 表持续存在直到独立的、带 bake period 的后续迁移执行（`BACKEND-3`，见 D2）。

---

## D1 — Embedding 配置的归属载体 ★ reversible-late

**问题**：openIndu-studio 今天既没有 server，也没有可被 backend 依赖的 API——"把 embedding 归属迁过去"具体接在哪？

| 选项 | 做法 | 评估 |
|---|---|---|
| **A. 命名约定对齐，无运行时依赖（推荐）** | `openIndu-backend` 新增 `settings.EMBEDDING_MODEL`（env var，默认值与今天硬编码的字符串完全相同），把 `rag_sync_service.py`/`milvus_service.py` 里两处硬编码字面量替换成这个 setting；命名直接复用 `local-rag-mcp/server.py` 已经在用的 `EMBEDDING_MODEL` 环境变量名。studio 的 `local-rag-mcp` 不做代码改动（它已经是这个命名约定的原始来源），只在其 `CLAUDE.md` 补一条"该命名约定是跨仓共享参考"的说明 | ✅ 满足 C1（零网络依赖，零新增部署面）；零行为变化（默认值不变）；"归属"体现为"studio 的既有约定成为组织标准"，是唯一不需要新造基础设施就能兑现的解读 |
| B. studio 长出一个真实部署的网络配置/embedding 服务，backend 在启动或调用时向它取值 | 需要先给 studio 建 FastAPI/gRPC 服务、写 Dockerfile、接 K8s（会违反 C1 除非先做这件事）、定义服务间鉴权、处理 studio 服务不可用时 backend 的降级策略 | ⚠️ 技术上可行，但是一个独立的、量级远超"下线一个 admin 页面"的基础设施立项，且 §2.2.8 已经规划了 studio 服务化的路线图（工程产物服务 Phase 2a/2b）——**若要做，应该和那次服务化一起做一次，而不是现在为了 5 个字段单独起一套部署**。是否现在就投入，是产品/路线图优先级问题，见债务台账 |
| C. 什么都不改，只删 Settings 页，5 个字段原地消失，不建立任何跨仓约定 | 最省事 | ❌ 没有兑现 issue "move to openindu-studio" 的任何部分，等于只做了方案 A（narrow）+ 一半的 B（medium），不构成对用户已选定方案 C 的合理解释 |
| D. 把同步**执行**（scheduler、PDF 解析、Milvus 写入）整体迁到 studio | 彻底解决"归属"问题 | ❌ 违反 C1（studio 无部署面）；且把一个明确在工作的调度任务迁移到一个从未跑过网络服务的仓库，风险与工作量完全不成比例，issue 原文也只提到 "Embedding model"，没有要求迁移执行引擎 |

**决策：A。** 具体改动（对应 `BACKEND-2`，见 Appendix B）：

```python
# app/core/config.py 新增
EMBEDDING_MODEL: str = "BAAI/bge-m3"  # 与 openIndu-studio/local-rag-mcp 的同名环境变量保持同一命名约定
```

`rag_sync_service.py:41` 与 `milvus_service.py:27` 的字符串字面量替换为 `settings.EMBEDDING_MODEL`；`.env.example` 补一行 `EMBEDDING_MODEL=BAAI/bge-m3`。

**明确不做的事（避免顺手夹带范围外改动）**：
- 不引入共享的 `EMBEDDING_DEVICE` 设置。`rag_sync_service.py` 的 CUDA 自动探测和 `milvus_service.py` 的强制 CPU 是两条路径今天就不一致的既有行为；用一个共享变量统一它们，默认值不管取哪一边都会悄悄改变另一边的现有行为（GPU 利用率或查询延迟），这是一次独立的性能/资源决策，不属于"退役配置页"的范围。列入债务台账。
- 不把 `rag_chunk_size`/`rag_chunk_overlap` 提升为环境变量。它们与 studio 毫无关系（studio 的 `local-rag-mcp` 只做检索、不做任何 PDF 解析/分块），保持现状的 Python 常量即可，提升为 env var 是纯粹的操作灵活性增强，不是本 issue 要求的一部分。
- 不把 `rag_sync_interval` 提升或改名。它已经有一个真正生效、独立于本次改动的等价物（`RAG_SYNC_INTERVAL_MINUTES`），本次只是删除那个从未生效过的同名 DB 键。

**Consequences**
- backend 与 studio 之间**不产生任何新的运行时依赖**——C1 全程满足。
- "迁到 studio" 的兑现方式是**命名权威**而非**运行时耦合**：以后任何仓库需要一个 embedding 模型配置项，参照 studio 这个既有命名，而不是各自发明。
- 若未来 §2.2.8 的工程产物服务真的把 studio 服务化，选项 B 自然重新出现，届时应作为那次立项的一部分复用，而不是现在预先搭一半。

---

## D2 — 迁移/下线排期与回滚（覆盖"零停机、零数据丢失"要求） ◐ reversible-mid

**先说明为什么这不是一次典型的"迁移"**：Context §3 已经证明，`system_configs` 里这 5 个字段今天不被任何运行时代码读取。真正"活着"、不能中断的系统——APScheduler 调度、`rag_sync_service.py` 的解析/嵌入/写入、`Document.sync_status` 状态机——**完全不在本次改动涉及的文件范围内**（`sync_task.py`、`rag_sync_service.py`、`app/api/documents.py` 的同步端点、`app/api/sync.py` 全部保持不动）。所以这里不存在"活配置系统"意义上的双写/影子期问题；真正需要设计的是**跨两个独立部署单元（admin 镜像、backend 镜像）的退役顺序**，避免中间出现"admin 还在调一个已经被删的路由"的窗口。

### 排期

| 阶段 | 动作 | 仓库 | 依赖顺序 | 数据风险 |
|---|---|---|---|---|
| Stage 0（现状） | Settings 页可用但不生效；`system_configs` 表里躺着 5 行从未被读取的数据 | — | — | — |
| **Stage 1** `ADMIN-1` | 删除 `SettingsView.tsx`、路由、导航项、`configApi`、`SystemConfig` 类型、`unwrapItems` 辅助函数及相关测试 | `openIndu-admin` | **必须先于 Stage 2 部署上线** | 无（前端不持有数据） |
| **Stage 2** `BACKEND-1` | 删除 `app/api/config.py`、`app/models/system_config.py` 及其 import；**不触碰 `system_configs` 表本身** | `openIndu-backend` | 必须晚于 Stage 1 上线 | 无（表继续存在，只是 ORM/路由不再引用它） |
| Stage 3 `BACKEND-2` | `EMBEDDING_MODEL` 提升为具名 env var（D1） | `openIndu-backend` | 与 Stage 1/2 无文件重叠，任意顺序、甚至可并行 | 无（默认值不变） |
| Stage 3′ `WEBSITE-1` / `STUDIO-1` | 文档口径修正（见 Appendix B） | `openIndu-website`、`openIndu-studio` | 无运行时依赖，建议紧跟 Stage 1/2 落地以保持文档与代码一致 | 无 |
| **Stage 4**（延后执行）`BACKEND-3` | 新增 Alembic 迁移，`DROP TABLE system_configs` | `openIndu-backend` | **门禁**：Stage 2 上线后 ≥ 1 个发布周期（建议 ≥ 4 周）且期间无人反馈配置缺失，才执行 | 表结构不可逆删除——见下方回滚 |

### 为什么 Stage 1 必须先于 Stage 2

C3：如果 Stage 2（删路由）先于 Stage 1（admin 还在调 `GET/PUT /config`）上线，用户打开尚未重新部署的旧版 Settings 页会看到接口 404。影响面很小（该页面本来就不生效，且只有 admin 能看到），但顺序成本为零，没有理由不做对。

### "cutover 瞬间正在 syncing 的文档怎么办"

**不需要特殊处理，因为本次改动不touches 同步执行路径本身。** `BACKEND-1`/`BACKEND-2` 的部署会重启 `openIndu-backend` pod（任何后端改动都会），这与"部署期间可能打断一个正在跑的 APScheduler 任务"是**部署这件事本身固有的、与本次改动无关的既有风险**，不是本 ADR 引入的新风险。真正兜底的是 `rag_sync_service.py` 已有的幂等设计：`sync_document()` 每次都先 `collection.delete(delete_expr)` 按 `document_name` 删除旧向量再插入新向量（`rag_sync_service.py:277-282`），因此一次被中断的同步在下一个调度周期或下一次手动触发时会被完整重做，不会产生重复向量或半状态数据。**唯一的既有缺口**（非本次引入）：如果进程在写 `sync_status="syncing"` 之后、写终态之前被硬杀，该文档会卡在 `syncing`，后续手动重试被 409 永久拒绝——见 Context §4 与债务台账，本 ADR 不在此处修它，但 D3 的简化方向恰好降低了这个卡死状态在 UI 上造成困惑的概率。

### "配置值如何转移，不留下'谁都不是权威'的空窗"

**`EMBEDDING_MODEL`（唯一有实际转移的字段）**：转移前，硬编码 Python 字面量是权威值；转移后，`settings.EMBEDDING_MODEL`（未设置时回落到相同默认值）是权威值。因为默认值处处相同，**任意时刻代码都有确定取值**，不存在空窗——这是"提升硬编码常量为同默认值的具名配置项"这类重构的标准性质，不需要额外设计动作。其余 4 个字段（`embedding_device`/`rag_chunk_size`/`rag_chunk_overlap`/`rag_sync_interval`）本来就没有权威过，谈不上"转移"，直接删除。

### 回滚

| 阶段 | 回滚方式 | 成本 |
|---|---|---|
| Stage 1 | `git revert` admin PR，重新部署 | 低——页面、路由、导航原样恢复，因为没有数据被删除 |
| Stage 2 | `git revert` backend PR，重新部署 | 低——`system_configs` 表全程未动，路由/模型代码原样恢复即可读到原数据 |
| Stage 3 (`BACKEND-2`) | `git revert` | 低——纯改名，行为不变 |
| **Stage 4**（一旦执行） | **不可简单回滚**——`DROP TABLE` 之后只能从数据库备份恢复该表 | 这正是把它单独作为 Stage 4、且设置 bake period 门禁的原因：前 3 个阶段全部零风险可逆，只有这一步不可逆，所以刻意延后、刻意需要独立确认 |

---

## D3 — `sync_status` 状态集简化 ◐ **本节是本文作者（architect）对 issue 原文的解读，不是字面需求，需用户在评审时明确确认或改写**

> issue 原文"remove the pending and synced in pending"在当前代码里没有字面对应（Context §4）。以下是我认为最合理、且风险最低的一种解读，附上另外两种被放弃的解读及理由；**用户签字确认清单里单列了这一项**，因为它改的是一个用户可见的状态展示逻辑，值得单独点头。

**我的字面猜测**：这句话很可能是"remove the pending and syncing [distinction], [merge them] in pending"的笔误/口语化表达——即"把 pending 和 syncing 这两个状态的区分去掉，统一显示成 pending"。这个猜测恰好与下面纯技术角度得出的结论一致，互相印证，但我仍然把它当作**待验证的猜测**，不是确定的原意。

**支持简化的技术依据（Context §4 已证）**：① 定时批量同步路径从来不设置 `syncing`，只有两条 admin 触发的单文档路径会，说明这两个状态在系统里的区分本来就不完整；② 前端已经把 `pending`/`syncing`/`deleted` 三者渲染成同一种徽标颜色，视觉上早就没有区分；③ `syncing` 状态还牵扯一个既有的"卡死后 409 永久拒绝重试"的缺口（Context §4 末尾），减少这个状态的可见性能顺带降低用户碰到该缺口时的困惑。

| 选项 | 做法 | 评估 |
|---|---|---|
| **A. 仅展示层合并（推荐）** | 后端 `sync_status` 五个值（`pending`/`syncing`/`synced`/`failed`/`deleted`）**原样不动**，包括 409 并发守卫逻辑；只改 `DocumentList.tsx` 的**渲染**：徽标把 `pending`/`syncing`/`deleted` 三者统一显示文案"待同步"，操作按钮把"同步中.../同步"的文案判断简化为"是否禁用"而不区分具体状态 | ✅ 零后端/数据库/迁移风险（不改列、不改状态机、不改并发保护）；`app/mcp/tools.py:106` 透出给 Claude Code 的原始值不受影响；纯前端小改动（约 3-6 行，见 Appendix B）；可独立于 D1/D2 随时上线，也可独立于本 ADR 其余部分单独回滚 |
| B. 真的从数据库状态机里去掉 `syncing`（改列约束/改所有写入点） | 上传/手动同步端点不再显式置 `syncing`，409 并发守卫改用其他机制（如内存锁或新增列） | ⚠️ 改动横跨 `documents.py` 三处写入点 + 需要重新设计并发保护，中等风险中等收益；能"真的"简化状态机，但代价明显高于选项 A，且需要新写并发保护逻辑本身就有引入新 bug 的空间 |
| C. 去掉手动重试按钮 | 呼应 issue 里可能想表达的"简化同步管理 UI" | ❌ 这是运营能力的减法（今天失败的文档只能靠手动同步按钮恢复，去掉它意味着失败后只能等下一个整点批量任务，或者去手工调接口）——这是一个产品能力取舍，不是单纯的状态展示简化，我不认为这是 issue 原文想表达的内容，且擅自砍掉一个现用的运维手段超出了"清理 Settings 页"的合理解读范围 |

**决策：A（如获确认）。** 具体改动局限在 `DocumentList.tsx` 三处（对应 `ADMIN-2`，见 Appendix B）：
- 第 180 行 `refetchInterval` 的轮询判定条件（逻辑不变，只是不再需要分别列举 `pending`/`syncing`，可以简化表达）
- 第 426 行徽标 variant 三元表达式
- 第 443/446 行按钮 `disabled`/文案的三元表达式

**Consequences**
- 后端 `sync_status` 列、迁移、`app/mcp/tools.py` 的 MCP 输出、`app/api/sync.py` 的聚合统计**全部不变**——`tests/unit/test_api_coverage.py:319-320` 的既有测试无需修改。
- 用户在 Document Management 页面看到的"同步中"文案消失，改为统一的"待同步"，这是一个**可感知的行为变化**，因此单独列入签字确认清单，不与 Settings 页下线（一个用户看不到任何变化，因为它本来就没用的改动）混为一谈。
- **已知的展示层小瑕疵（不阻塞，已知即可）**：`app/api/sync.py:57` 的头部计数 `pending_count = stats.get("pending", 0) + stats.get("failed", 0)` **不含 `syncing`**。这个统计口径本次不改，D3 上线后会略微放大它的观感——一行的徽标显示"待同步"，但页面头部"待同步/失败：N 个文档"的 N 不把它算进去，容易让人以为漏计。这个不一致在今天就存在（只是徽标以前显示的是英文原始值 `syncing`，观感上更像"另一种状态"），D3 只是让合并后的中文文案更容易被误读成"应该被计入"。若要修，`ADMIN-2` 之外单独加一行 `+ stats.get("syncing", 0)` 即可，是否现在顺手修、还是留给债务台账，留给实现时判断（不改变 `ADMIN-2` 已声明的"零后端改动"范围，除非明确决定要修）。
- 如果用户否决这个解读、认为原意是别的东西（例如选项 B 或 C，或完全不同的东西），`ADMIN-2` 可以整个撤回而不影响 `ADMIN-1`/`BACKEND-1`/`BACKEND-2` 已经落地的部分——这也是把它做成独立 PR 的原因。

---

## 影响范围（按仓库）

| 仓库 | 改动文件 | 性质 |
|---|---|---|
| `openIndu-admin` | `src/app/pages/settings/SettingsView.tsx`（删除）、`src/app/routes.tsx`（删 1 条路由+1 条 import）、`src/app/components/Sidebar.tsx`（删 1 个导航项，保留分组容器与 `/settings/tags`）、`src/api/index.ts`（删 `SystemConfig` 类型、`unwrapItems`、`configApi`）、`src/__tests__/api.test.ts`（删对应测试块） | `ADMIN-1`，纯删除 |
| `openIndu-admin` | `src/app/pages/documents/DocumentList.tsx` | `ADMIN-2`，展示层小改（待确认，见 D3） |
| `openIndu-backend` | `app/api/config.py`（删除）、`app/models/system_config.py`（删除）、`app/web_app.py`（删 3 处 import/注册）、`alembic/env.py`（删 1 处 import）、`tests/unit/test_api_coverage.py`（删对应测试） | `BACKEND-1`，纯删除，**不动表** |
| `openIndu-backend` | `app/core/config.py`、`app/services/rag_sync_service.py`、`app/services/milvus_service.py`、`.env.example` | `BACKEND-2`，新增具名配置（D1） |
| `openIndu-backend` | 新 Alembic 迁移文件 | `BACKEND-3`，**延后执行**，`DROP TABLE system_configs` |
| `openIndu-website`（聚合仓自身） | `prod/requirements.md` §3.3.7（重写配置分层表，删"业务参数"行，embedding 相关项并入"基础设施连接"层）、§3.4（as-built 页面清单删除 SettingsView 一行，参照既有的 `~~会员申请审核~~` 划除写法）、§4.3.7/§4.3.8（删 `/config` 端点表；可选修正"RAG Server 回调"这段与实现不符的架构叙述）、版本历史表新增一行 | `WEBSITE-1`，文档 |
| `openIndu-studio` | `CLAUDE.md` | `STUDIO-1`，文档，声明 `EMBEDDING_MODEL` 命名约定为跨仓参考、并记录本 ADR 链接（RULE 6：这是对一份已确认文档的修改，需要在该文件里附变更记录） |

**不受影响，需要在评审时明确指出以免被误伤**：`app/api/sync.py`（`/sync/trigger|status|logs`）、`app/tasks/sync_task.py`、`app/services/rag_sync_service.py` 的分块/嵌入执行逻辑、`app/api/documents.py` 的同步端点与 409 守卫、`Document` 模型与 `sync_status` 列本身、`app/mcp/tools.py`、`openIndu-admin` 的 `TagsView.tsx` 与 `/settings/tags` 路由。

---

## 非功能目标

| 维度 | 目标 | 验证方式 |
|---|---|---|
| 可用性 | 定时 OSS→Milvus 同步任务在 `ADMIN-1`/`BACKEND-1`/`BACKEND-2` 三次部署前后成功率、耗时无回归 | 对比部署前后 `sync_logs` 表的 `success`/`failed` 比例 |
| 数据完整性 | `system_configs` 表行数在 Stage 1-3 全程不变（Stage 4 之前） | `SELECT COUNT(*) FROM system_configs` 部署前后一致 |
| 无残留死链接 | Admin 侧不残留任何指向 `/settings`（非 `/settings/tags`）或 `/api/v1/config` 的可达入口 | 全文 grep `configApi`、`/settings'` （排除 `/settings/tags`）应为 0 命中 |
| 行为等价 | `EMBEDDING_MODEL` 提升为 env var 前后，`rag_sync_service.py`/`milvus_service.py` 实际加载的模型字符串完全相同 | 单测断言 `settings.EMBEDDING_MODEL == "BAAI/bge-m3"` 且两个服务调用点不再含字面量 |
| 文档真实性 | `prod/requirements.md` 不再包含与代码不符的"即时生效"表述 | 人工核对 §3.3.7 改写后的分层表 |

---

## 债务台账

| 条目 | 说明 | 触发再评估的条件 |
|---|---|---|
| `BACKEND-3`（`DROP TABLE system_configs`）延后执行 | 见 D2 Stage 4 | Stage 2 上线 ≥ 4 周且无人反馈配置缺失（**具体周期属于运维/产品节奏判断，架构侧只给出建议值，需 product-manager/ops 确认或调整**） |
| 硬杀后 `syncing` 残留期间，手动重试按钮被 409 永久拒绝（文档本身若定时任务启用会在下一周期自愈，`RAG_SYNC_ENABLED=false` 时不会） | Context §4 末尾，既有 bug，与本 issue 无关 | 有真实用户/运维报告"手动同步按钮长期 409"案例时优先修；本 ADR 不修 |
| `app/api/sync.py:57` 的 `pending_count` 统计不含 `syncing`，D3 上线后徽标"待同步"与头部计数口径不完全一致 | D3 Consequences 已记录，纯展示层瑕疵 | 若决定修，一行改动（`+ stats.get("syncing", 0)`）；是否现在顺手做，留给 `ADMIN-2` 实现时判断 |
| `rag_sync_service.py`（CUDA 自动探测） vs `milvus_service.py`（强制 CPU）设备选择不一致 | D1 "明确不做的事" | 若 GPU 查询延迟成为优先级（例如智能咨询响应时间成为瓶颈）时再统一，并作为独立 ADR |
| `system_configs` 表 `DROP` 之后表结构不可逆 | D2 回滚表 | Stage 4 执行前必须有数据库层面的备份/快照存在，具体备份策略由 ops 负责，不在本 ADR 范围 |
| `Document.sync_status = "deleted"`（带外删除墓碑行）的数据留存策略 | 该状态今天允许一条元数据行永久留在列表里（只是徽标不醒目），是否应该改为硬删除或加一个"清理"入口，是数据留存策略问题 | **需 product-manager 裁决**——本 ADR 发现但不处理，issue #199 未提及这一点 |
| `prod/requirements.md` §4.3.7 "RAG Server 回调 Backend" 的架构叙述与实际实现（同进程 APScheduler，无独立 RAG Server）不符 | Context 已指出 | 是否在 `WEBSITE-1` 里顺手修正，还是单开一个文档修正任务，**优先级判断留给 product-manager/manager**，不影响本 ADR 其余部分 |
| studio 是否应该真正服务化（D1 选项 B） | 若 §2.2.8 工程产物服务 Phase 2a/2b 立项，RAG/embedding 服务化可以搭便车一起做 | **需 product-manager 在路线图层面裁决**是否/何时投入，架构侧不单方面决定这类投入优先级 |

---

## Appendix A — 交付顺序

```
ADMIN-1 ──(必须先上线)──▶ BACKEND-1
BACKEND-2 ── 与上两者无文件重叠，任意时点独立上线
WEBSITE-1 ── 建议紧跟 ADMIN-1/BACKEND-1 落地，保持文档口径与代码一致；无强制顺序
STUDIO-1  ── 与其余全部无运行时依赖，任意时点独立上线
ADMIN-2   ── 完全独立分支，等待 D3 单独确认后随时可发，不依赖上述任何一项
BACKEND-3 ── 显式延后，Stage 4 门禁满足后才发起（见 D2）
```

---

## Appendix B — PR 影响清单（RULE 4：单次改动 ≤ 400 行 / ≤ 1 个模块边界）

### `ADMIN-1`｜移除 Settings 页与 configApi

| 文件 | 动作 | 估计行数 |
|---|---|---|
| `src/app/pages/settings/SettingsView.tsx` | 整文件删除 | −63 |
| `src/app/routes.tsx` | 删 1 条 `import` + 1 条路由（`/settings/tags` 保留） | −2 |
| `src/app/components/Sidebar.tsx` | 删 `settingsSubItems` 里 1 项 + 未再使用的 `Settings` 图标 import | −2 |
| `src/api/index.ts` | 删 `SystemConfig` 接口（6 行）+ `unwrapItems` 辅助函数（6 行，删除后已无其他调用方）+ `configApi`（6 行） | −18 |
| `src/__tests__/api.test.ts` | 删 `describe('unwrapItems helper', …)`（45 行）+ `describe('configApi', …)`（13 行）+ `expect(exports.configApi).toBeDefined()` 1 行 | −59 |
| | **合计** | **≈ −144 行**，单模块（admin 前端），**远低于 400 行上限，无需拆分** |

### `BACKEND-1`｜移除 `/config` 路由与 `SystemConfig` 模型引用（不动表）

| 文件 | 动作 | 估计行数 |
|---|---|---|
| `app/api/config.py` | 整文件删除 | −43 |
| `app/models/system_config.py` | 整文件删除 | −24 |
| `app/web_app.py` | 删 import 列表中 `config,`（1 行）、删 `SystemConfig` 的 `# noqa` import（1 行）、删 `include_router` 列表里的 `config.router,`（1 行） | −3 |
| `alembic/env.py` | 删 `SystemConfig` 的 `# noqa` import | −1 |
| `tests/unit/test_api_coverage.py` | 删 config PUT 往返测试（约在第 278-281 行附近，实现时以当时文件为准核实实际边界） | 约 −15（估） |
| | **合计** | **≈ −86 行**，单模块（backend API 层），远低于 400 行上限 |

### `BACKEND-2`｜`EMBEDDING_MODEL` 提升为具名配置（D1）

| 文件 | 动作 | 估计行数 |
|---|---|---|
| `app/core/config.py` | 新增 `EMBEDDING_MODEL: str = "BAAI/bge-m3"` + 注释 | +3 |
| `app/services/rag_sync_service.py` | 字面量替换为 `settings.EMBEDDING_MODEL` | ~2（改） |
| `app/services/milvus_service.py` | 字面量替换为 `settings.EMBEDDING_MODEL` | ~1（改） |
| `.env.example` | 新增 1 行 | +1 |
| | **合计** | **≈ 10 行**，单模块，与 `BACKEND-1` 零文件重叠，可并行或任意顺序 |

### `ADMIN-2`｜`sync_status` 展示层合并（D3，待确认）

| 文件 | 动作 | 估计行数 |
|---|---|---|
| `src/app/pages/documents/DocumentList.tsx` | `refetchInterval` 判定、徽标 variant、按钮文案/禁用三处三元表达式改写 | ~6（改） |
| | **合计** | **≈ 6 行**，单文件，独立分支，不依赖其余任何 PR |

### `WEBSITE-1`｜`prod/requirements.md` 口径修正

| 文件 | 动作 | 估计行数 |
|---|---|---|
| `prod/requirements.md` §3.3.7 | 重写配置分层表，删业务参数行 | ~15（改） |
| `prod/requirements.md` §3.4 | as-built 清单标注 SettingsView 已移除 | ~2 |
| `prod/requirements.md` §4.3.7/§4.3.8 | 删 `/config` 端点表；可选修正 RAG Server 叙述 | ~10-20（改，视是否顺手修正架构叙述而定） |
| `prod/requirements.md` 版本历史表 | 新增一行 | +1 |
| | **合计** | **≈ 30-40 行**，单文件，远低于上限 |

### `STUDIO-1`｜文档说明

| 文件 | 动作 | 估计行数 |
|---|---|---|
| `CLAUDE.md` | 声明 `EMBEDDING_MODEL` 命名约定为跨仓参考 + 变更记录（RULE 6 要求：修改已确认文档需附变更说明） | +10~15 |

**结论**：全部 7 个计划中的 PR 均在 400 行上限之内、且各自落在单一模块/单一仓库边界内，**本次不存在需要在计划阶段就拆分的项**（与 i18n ADR 的 PR-1 情况不同，那次是超限后拆分；这次是核实后确认都不超限）。`BACKEND-3` 因数据不可逆性单独延后执行，不是因为行数问题。

---

## 签字确认清单（本 ADR 转为 Approved 前，需用户逐项确认或改写）

1. **D1**：确认"embedding 归属迁到 studio"按**命名约定对齐**（studio 的 `EMBEDDING_MODEL`/`EMBEDDING_DEVICE` 环境变量命名成为跨仓参考）解读即可，**不要求**现在就把 studio 建成一个 backend 依赖的真实网络服务（选项 B，架构上可行但是一个独立、量级更大的立项，建议留给 §2.2.8 studio 服务化时一并做）。**具体而言**：改动后 `openIndu-backend` 与 `openIndu-studio` 之间不会有任何一方在运行时读取、调用或依赖另一方——两边各自独立维护一份相同默认值的字符串常量，日后其中一方改了默认值，不会有任何机制侦测到两边已经不一致。
2. **D3（重点）**：确认"remove the pending and synced in pending"按本文解读处理——即 `DocumentList.tsx` 把 `pending`/`syncing`（以及既有的 `deleted`）在展示层合并为统一的"待同步"呈现，**后端状态机、并发守卫、MCP 输出全部不变**。如果原意其实是选项 B（真的从数据库状态机去掉某个状态）或选项 C（去掉手动重试按钮）或完全是另一件事，请明确指出，`ADMIN-2` 会据此重新设计，不影响其余已确认部分。
3. **D2 的 bake period**：`BACKEND-3`（`DROP TABLE system_configs`）默认建议延后 ≥ 4 周执行，这个周期是否合适，或是否要求一个更明确的日期/审批人，需要确认。
4. **债务台账**中标注"需 product-manager 裁决"的两项：① `sync_status="deleted"` 墓碑行的数据留存策略；② studio 是否/何时投入真正服务化——本 ADR 均未替用户做出决定，仅记录发现。
5. 是否顺手在 `WEBSITE-1` 里修正 `prod/requirements.md` §4.3.7 那段与实现不符的"RAG Server 回调"架构叙述，还是留到单独的文档修正任务——不影响本次功能性改动，但会改变 `WEBSITE-1` 的行数估计。
