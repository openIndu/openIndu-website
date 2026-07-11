# RAG（智能咨询 / MCP 检索）现状评估与优化设计

> 版本: 0.3.0 | 日期: 2026-07-11 | 状态: Step 0/1/2 已实施并实测验证；Step 3-5 待排期（详见 §6）
>
> 本文档基于 [`prod/requirements.md`](requirements.md) §4.3.12（智能咨询）、§4.4（MCP Server）、§4.6.2（Milvus Collection）整理现状架构，
> 并结合历史生产数据、当前数据库实测，评估检索效果与命中率，给出优化建议。**本文档只做分析，不包含已实施的变更**——所有建议需用户确认优先级后再排期实施。

---

## 1. 现状架构（源自 requirements.md，本次未做架构变更）

### 1.1 两个检索入口，共享同一套底层能力

| 入口 | 服务 | 消费者 | 生成方式 |
|------|------|--------|---------|
| MCP Server（:8005） | 11 个工具（`search_plc_manual` 等 8 类文档检索 + `get_brand_mapping` + `list_available_*` ×2） | Claude Code / AI Agent | 仅返回检索片段，生成在调用方（Claude Code） |
| 智能咨询 `/api/v1/chat`（:8004） | SSE 流式问答 | Portal member 用户 | 检索片段 + 后端内置 LLM（DeepSeek）生成完整答案 |

两者都通过 `app/services/milvus_service.py` 的同一个 `MilvusService.search()` 查询同一个 Milvus collection（`controller_knowledge`），检索逻辑完全一致，只是消费方式不同。

### 1.2 索引与检索参数（代码实测，非文档默认值）

```python
# app/web_app.py _init_milvus_collection()
fields = [id, text(≤2048), document_name(≤500), brand(≤50), category(≤50), page, chunk_id, embedding(FLOAT_VECTOR, dim=1024)]
index_params = {"metric_type": "COSINE", "index_type": "IVF_FLAT", "params": {"nlist": 128}}

# app/services/milvus_service.py search()
search_params = {"metric_type": "COSINE", "params": {"nprobe": 10}}
embedding_model = SentenceTransformer("BAAI/bge-m3", device="cpu")  # 查询时固定 CPU，不管同步链路是否用 GPU
```

### 1.3 双模式作答（chat_service.py，v0.13.0 已文档化）

- `determine_mode()`：检索 top-1 COSINE score ≥ **0.7** → `grounded`；否则 → `fallback`（通用知识 + 前端警告条）
- 阈值 0.7 有实证依据（不是拍脑袋）：富士以太网 0.74→grounded ✅；富士 PLC 编程示例 0.67→fallback ✅；FX5U 地址规划 0.54→fallback ✅
- 会话模式检索前经 `rewrite_query()` 用 LLM 把多轮追问改写为自包含查询，缓解跨轮品牌/系列漂移

### 1.4 当前生效配置（`.env` 实测值）

```
RAG_TOP_K=5              CHAT_DAILY_LIMIT=30           RAG_SYNC_ENABLED=false（内置定时同步已关闭）
LLM_MODEL=deepseek-chat  LLM_TEMPERATURE=0.2           RAG_SYNC_INTERVAL_MINUTES=60（未生效，因上面已关）
```

同步链路目前依赖**离线脚本** `scripts/offline_embed.py`（GPU 加速，绕过 APScheduler 内置同步——因为 CUDA 卡死曾导致内置同步整批挂死）。

---

## 2. 当前数据状态（本次排查实测，与文档/历史记忆有出入）

| 指标 | 6-29 历史记忆 | **当前实测（07-10）** |
|------|:---:|:---:|
| PG `documents` 总数 | 243 | **350**（+107，07-05 前后批量导入） |
| Milvus `controller_knowledge` entities | 144,993 | **0** |
| `documents.sync_status` | 全部 synced | **全部 350 篇 = pending** |
| 品牌数 | 16 | 17（新增 akribis） |

**结论（用户已确认根因）：数据丢失是一次向量重构/优化操作直接删除旧数据导致的**——为修正批量导入时写错的 `brand` 元数据（中文 label 而非英文 slug），需要重建向量，操作中直接清空了 collection，而后续全量重新嵌入未完整执行（或又被重置），导致 350 篇文档全部回到 pending、Milvus 归零。

### 2.1 复盘：根因已在代码中定位（`scripts/fix_brand_values.py`）

该脚本用于修正批量导入时写错的 brand 值（`三菱`/`CKD`/`康耐视` 等中文/大小写误值 → `mitsubishi`/`ckd`/`cognex` 英文 slug），逻辑分三步：

```python
# scripts/fix_brand_values.py（openIndu-backend）
milvus_service.delete_by_document(doc.original_name)   # ① 只删这一篇的旧向量——per-doc，不是整库删除
oss.copy_object(...); oss.delete_object(...)            # ② 迁移 OSS key 到新品牌路径
doc.brand = new_brand; doc.sync_status = "pending"      # ③ 更新 PG，标记 pending 等待重新嵌入
```

**脚本本身的设计是安全的**——① 是逐篇 `delete_by_document()`，不是 `drop_collection()`，不会一次性清空整个 collection。真正的缺口在**流程**：脚本执行完 ①②③ 后，**必须紧接着跑一次完整的重新同步**（`offline_embed.py --run` 或触发 `/documents/sync/trigger`）把这些标记为 `pending` 的文档重新嵌入回 Milvus——但这一步没有跑完（或跑到一半中断），导致受影响文档长期停留在"向量已删、未重新插入"的中间态。结合当前 350 篇全部 `pending`（不止脚本里 `BRAND_FIX` 涉及的 mitsubishi/ckd/cognex/akribis 几个品牌），推测同期可能还有类似的 category 修正脚本（如 `fix_rename_category.py`）做了同样的"标记 pending"操作，多个脚本的 pending 标记叠加，而后续重新嵌入的收尾工作一直没有完整执行。

**操作准则（写入本文档，供后续参考）**：
- `fix_brand_values.py` 这类"改 PG/OSS 元数据 + 标记 sync_status=pending"的脚本，**执行后必须在同一次操作窗口内跑完重新嵌入**，并用 `offline_embed.py --status` 确认 `pending=0` 后才算完成——不要让"标记 pending"和"重新嵌入"这两步跨会话、跨天分开执行，中间的空窗期就是这次数据丢失的直接原因。
- 索引参数调整（本文档 §4 建议的 IVF_FLAT→FLAT）**不需要碰数据**：`Collection.drop_index()` 与 `drop_collection()` 是两个独立操作，前者只删 ANN 索引结构、不动向量本体，可以安全单独执行（`drop_index` → `create_index` 新参数 → `load`），不会重演本次问题。

### 2.2 恢复结果（07-11，Step 1 已执行）

| 指标 | 07-10 实测（本次排查起点） | **07-11 恢复后** |
|------|:---:|:---:|
| `documents.sync_status` | 全部 350 篇 pending | **全部 350 篇 synced，0 pending，0 failed** |
| Milvus `controller_knowledge` entities | 0 | **156,499** |
| 分块方式 | — | 400 token / 50 token overlap（§5.3 试点选定），双重 token+字节上限保护（见下） |

执行中发现并修复两个此前从未触发过的潜在 bug（旧的按字符数分块从未逼近这些边界，切到按 token 分块后才暴露）：
1. **Windows 控制台 GBK 编码崩溃**：`offline_embed.py` 用 `print()` 输出文档名/错误信息，遇到 GBK 无法表示的字符（如英文手册标题里的 "ﬁ" 连字 U+FB01）会抛 `UnicodeEncodeError` 直接杀死整个进程——已加 `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` 修复，不会再因为单篇文档的文本内容中断全量任务。
2. **Milvus VARCHAR 按字节而非字符计数**：`text` 字段 `max_length=2048` 是**字节**限制（pymilvus 侧校验），不是字符数。参数表/寄存器地址表这类内容 token 密度很低（很多字符只占很少 token），400-token 预算可能merge 出几千字符的单个 chunk，超出字节限制导致插入失败——影响约 30% 的三菱 PLC 手册（参数表密集）。修复：分块器改为**token 数与字节数双上限**（`CHUNK_MAX_BYTES=2000`），两者任一先达到就结束当前 chunk；额外处理了"单个段落本身就超字节上限"的罕见情况（硬切分，不丢内容）。已在 `rag_sync_service.py` 与 `offline_embed.py` 同步修复。

修复后全量 235 篇剩余文档（115 篇此前已用新分块器成功嵌入，无需重跑）重新处理：**230 成功，5 篇本身无可提取文本（如扫描件/纯图纸），0 失败**。

---

## 3. 检索效果与命中率评估

### 3.1 历史生产数据（唯一可信的真实信号——查询来自真实用户，非人工构造）

`chat_messages` 表完整保留了每条回答的 `mode` 字段。按时间线切片：

| 时间窗口 | Milvus 状态 | grounded | fallback | grounded 率 |
|---------|:---:|:---:|:---:|:---:|
| 06-29 03:01 ~ 07-01 08:38（确认满库 144,993 chunks） | 满 | 3 | 6 | **33%** |
| 07-05 02:53 起（品牌修正/集合重建期间及之后） | 空/重建中 | 6 | 19 | 不可信（集合非稳态，混有空库期样本） |

**只取"确认满库"窗口的 9 条真实问答作为基线：即使 16 品牌 144,993 chunks 全量在库，grounded 率也只有 33%。** 这是本次评估最核心的量化结论——数据量本身不是瓶颈，检索链路存在明确可优化空间。

### 3.2 满库期 fallback 案例的归因分类

| 问题（用户原话摘要） | 品牌 | 归因 |
|---|---|---|
| 台达变频器错误代码 | delta | **内容缺口**：delta 仅 7 篇 plc-manual + 1 篇 driver-manual，无变频器故障码专项内容 |
| 驱动器选型通用咨询 | — | **合理 fallback**：跨品牌选型建议本就不该被单一手册"grounded"，判定正确 |
| 汇川 EtherCAT / SV680 驱动器 | inovance | **内容缺口（当时）**：06-29 时 inovance 仅 1 篇软件手册，无驱动器手册（07-05 后已补 2 篇，待验证是否覆盖该型号） |
| S7-1200 配置 Modbus TCP（同一问题问两次，一次 grounded 一次 fallback） | siemens | **检索不稳定**：相同语义问题两次检索结果不一致，指向 ANN 召回参数问题（见 3.3） |

### 3.3 检索算法层面的技术瓶颈（新发现，非文档已知问题）

```
index: IVF_FLAT, nlist=128        search: nprobe=10
→ 每次查询仅探测 10/128 ≈ 7.8% 的聚类
```

144,993 向量 / 128 簇 ≈ 每簇约 1,133 个向量。`nprobe=10` 意味着每次查询只在约 11,330 个向量（占全库 7.8%）中做精确比较，其余 92.2% 的向量**即使包含更相关的内容也不会被扫描到**。这直接解释了 3.2 中"同一问题两次检索结果不一致"的现象——查询的微小改写（如 rewrite_query 引入的措辞变化）会让 embedding 落入不同的探测簇，召回结果因此漂移。

**这是当前最具性价比的优化点**：145K 向量、1024 维，对 Milvus 而言是很小的数据量；智能咨询有 `CHAT_DAILY_LIMIT=30`/用户/天的限流，日查询量不大。用 `IVF_FLAT` 近似搜索换来的速度收益，在这个规模下并不必要，但精度损失（漏检 92% 的候选簇）却实实在在地拉低了 grounded 率。

> **Step 0 试点补充发现**：小样本试点（§5.3）用 **FLAT（精确搜索，无 ANN 近似）** 跑了 6 组 chunk 配置，3.2 中长期 fallback 的三个案例（fuji-hardware / inovance-driver-sv680 / ckd-driver）在**全部 6 组配置、精确搜索**下 top-1 分数仍稳定在 0.60-0.67，从未越过 0.7——这三个案例的低分不是 `nprobe` 近似召回漏检导致的，语义相似度本身就没到阈值，需要靠 query rewrite/品牌过滤或重新评估阈值，不是索引调优能解决的。
>
> **Step 2 全量实测（07-11，与上面的试点结论互补而非矛盾）**：Step 0 的试点只有 7 篇文档，规模太小，IVF 近似检索本来就不是那个规模下的瓶颈（FLAT vs IVF 在 7 篇文档、几千向量下几乎无差异）。全量 350 篇（156,499 向量）用**黄金测试集 21 个用例**实测 `nprobe` 的影响，结果印证了 3.3 最初的假设——在真实规模下这确实是问题：
> - 连续两次用**相同配置**（`nprobe=10`）跑同一批查询，top-1 命中率从 38.1% 漂移到 28.6%——在没有任何代码/数据变化的情况下，同一批查询两次给出不同结果，直接证实"近似检索导致结果不稳定"不是猜测，是实测现象
> - 改 `nprobe=10 → 128`（`nlist=128`，即扫描全部聚类，等效精确搜索，且仍是 IVF_FLAT 索引本身，**不需要重建索引**）：top-1 命中率 **28.6% → 42.9%**（+14.3pp），top-k 命中率 **71.4% → 76.2%**（+4.8pp），负样本 fallback 率保持 100% 不变；重复跑两次结果**完全一致**（不稳定现象消失）
> - `grounded_rate`/`grounded_and_correct_rate` 两个指标没变——说明 `nprobe` 修的是"检索到正确文档"这个问题，不直接决定"这个正确文档的余弦分数是否过 0.7"；后者仍是阈值本身或内容/查询语义匹配度的问题，与 Step 0 试点的结论一致
> - **已直接采纳为生产配置**（`app/services/milvus_service.py` 第 40 行 `nprobe: 10 → 128`）——零成本、无回归、消除了不稳定性，符合 §5 "查询时参数、随时可调" 的框架，无需等待重新嵌入

### 3.4 数据完整性缺口（当前实测 vs 需求文档 §3.3.3 定义的 9 个分类）

```
registered active doc_category tags: plc-manual / driver-manual / hmi-manual / hardware-manual / other / robot-manual / scan_code  (7个)
requirements.md 定义:                 plc-manual / driver-manual / hmi-manual / hardware-manual / other / robot-manual
                                      + software-manual / best-practice / electrical-standard  (9个)
```

| 发现 | 影响 |
|------|------|
| `software-manual` 有 **6 篇文档**（mitsubishi 4 + ckd 2），但对应 tag **未在 resource_tags 注册** | Admin 设置页筛选下拉可能看不到这个分类选项；说明 `documents.category` 写入时**未走 tag 校验**，批量导入脚本绕过了标签体系 |
| `best-practice` / `electrical-standard` | 全库 **0 篇文档**——`search_best_practice`/`search_electrical_standard` 这两个 MCP 工具无论检索算法怎么优化，**结构性保证查不到任何内容**，需业务侧补充文档，非工程可单方面解决 |
| `scan_code`（扫码器，cognex 2 篇）| 是已注册 tag，但**不在 requirements.md 文档分类清单里，也没有对应的 MCP 搜索工具**——这 2 篇文档能在 Admin/Portal 正常浏览，但通过任何 MCP 工具都**永远搜不到** |

---

## 4. 优化建议（按优先级排序，供确认后排期）

| 优先级 | 建议 | 工作量 | 风险 | 说明 |
|:---:|------|:---:|:---:|------|
| ~~P0~~ | ~~全量重新同步 350 篇文档到 Milvus~~ | 低（脚本已就绪，GPU ~15-30 分钟） | 低 | **已完成（07-11）**：350 篇全部 synced，156,499 向量，详见 §2.2 |
| **P0** | 补注册 `software-manual` tag；决定 `scan_code` 去留（并入 `hardware-manual` 或新增第 9 个 MCP 工具） | 低 | 低 | 数据完整性修复，影响 Admin 筛选与 MCP 可发现性——**未完成** |
| ~~P1~~ | ~~Milvus `nprobe` 10 → 128~~ | 低（一行配置，零停机） | 低 | **已完成（07-11）**：黄金测试集实测 top-1 命中率 +14.3pp、top-k +4.8pp，且消除了同配置下的结果漂移，详见 §3.3 |
| **P1** | `rewrite_query()` 顺带抽取品牌/型号，自动传入 `where_filter` 缩小 ANN 搜索范围 | 中（需改 prompt + 抽取结构化字段） | 中（抽取错误可能过滤掉正确答案，需要 fallback 兜底） | 减少跨品牌噪声对 top-k 的干扰 |
| **P2** | 建立"黄金测试集"（每品牌/分类抽样 3-5 个已知能被特定文档回答的问题，标注期望命中文档） | 中 | 低 | 把"评估检索效果"从零散生产日志升级为可重复、可回归的量化指标，后续任何调参都能 A/B 对比 |
| **P2** | 补充 `best-practice` / `electrical-standard` / 弱势品牌驱动器手册内容 | 高（依赖业务侧持续上传） | — | 内容缺口非检索算法能解决，需产品侧规划 |

---

## 5. 分层实施策略：区分"一次性决定"与"查询时自由调参"

用户明确担心："同步完成之后，后续又要优化 RAG、又要删向量重新跑，很浪费资源"。这个担心是合理的，但**几乎所有本文档提出的优化项都不需要重新嵌入**——只有 chunk_size/overlap（切块方式）改变才要求重新嵌入，其余全部是查询时参数：

| 类型 | 优化项 | 是否需要重新嵌入 |
|------|--------|:---:|
| **一次性决定**（改了必须重新嵌入） | `chunk_size` / `chunk_overlap` | ✅ 是 |
| | Embedding 模型（BGE-M3） | ✅ 是（本次不改） |
| **查询时参数**（嵌入完成后随时可调，零成本） | 索引类型 IVF_FLAT→FLAT、`nprobe` | ❌ 否——`nprobe` 是每次搜索传的参数，不入索引；索引类型用 `drop_index()`/`create_index()` 只重建 ANN 结构，不碰向量数据 |
| | grounded 阈值（当前 0.7） | ❌ 否——纯 Python 常量 |
| | query rewrite / 品牌自动过滤 | ❌ 否——应用层代码 |

**结论：`chunk_size`/`chunk_overlap` 是唯一必须在正式全量嵌入前定好的参数**，因此不能靠拍脑袋，也不能靠盲目试错（试错=重新嵌入 350 篇=真的浪费资源）。以下是基于业界资料 + 实测数据的分析。

### 5.1 chunk_size/overlap 业界依据（非拍脑袋）

**通用 RAG 分块指南（2026）**：
- 常规起点 400-512 token；**事实类查询（fact-based，检索特定参数/步骤）适合 256-512 token**；分析类查询适合 512-1024 token
- Overlap 传统建议 10-20%，但 2026-01 一项基于 SPLADE + Mistral-8B 在 Natural Questions 上的系统性分析发现 **overlap 对召回没有可测量的提升，只增加索引成本**——不能默认"加了 overlap 就更好"，需要实测

**中文/CJK 专项指南**：
- 中文 RAG 常见推荐范围为 512-1024 token（引用换算约 300-600 中文字符）
- CRUD-RAG 基准研究：**单文档问答（我们的场景——针对某个具体手册问具体参数）用更小的 chunk 准确率更高**；更大的 chunk 有利于"创造性生成/保持连贯性"类任务（不是我们的场景）

**技术文档/表格类指南**：
- 结构感知（按标题/表格边界切分）优于纯按字数切分；表格应作为整体保留，不应被切碎
- 我们当前的分块器（`rag_sync_service.py`/`offline_embed.py` 的 `chunk_pages()`）是"按段落合并直到字数上限"，**不识别表格边界**——PLC/驱动器手册里大量参数表（寄存器地址表、参数一览表）可能被从中间切断

**BGE-M3 官方**（HuggingFace 模型卡 + 作者在 issue 中的回复）：
- 最大支持 8192 token，但官方没有给出"多长最优"的检索质量结论，只说明"文本长就设大一点，注意显存"——**没有可以直接照抄的官方推荐数字**，必须结合具体语言/内容实测

### 5.2 关键实测：现有 512（字符）实际对应多少 token？

用 BGE-M3 真实分词器（而非估算比例）对仿真工业中文技术文本（含参数表格式内容）实测：

```
256 字符 -> 177 token（比例 0.69）
384 字符 -> 246 token（比例 0.64）
512 字符 -> 325 token（比例 0.63）  ← 当前 CHUNK_SIZE 设定
768 字符 -> 486 token（比例 0.63）
1024字符 -> 652 token（比例 0.64）
```

比例非常稳定：**BGE-M3 对这类中文工业技术文本约为 0.63-0.69 token/字符**（该模型的 XLM-RoBERTa 分词器对中文常见词组有较高的子词合并效率，不是"一字一 token"）。

**关键发现**：当前代码用 `len(字符串)` 判断切块边界（`rag_sync_service.py`/`offline_embed.py` 的 `CHUNK_SIZE=512` 是**字符数**，不是 token 数），实测 512 字符 ≈ 325 token——落在"事实类查询 256-512 token"推荐区间的中段偏下，**并非明显偏大或偏小，但当前用"字符数"控制切块边界，本身是个精度问题**：不同内容（纯中文 vs 混排型号/数字如"FX3U"、"D0-D200"）字符→token 比例会漂移，用字符数切块无法稳定控制真实喂给模型的 token 长度，这是应该修正的**基础机制问题**，与"具体设多大"是两件事。

### 5.3 一次性决定：小样本试跑，不赌全量

不满足于"看资料+测比例就拍定一个数字"，用一次很便宜的小规模实验来最终确认：

1. **先修正分块器，改用 token 计数**（用已加载的 BGE-M3 tokenizer 而非 `len(字符串)`），这是机制修正，独立于具体数值
2. 挑 7 篇代表性文档（覆盖 mitsubishi/siemens/keyence/delta/fuji/inovance/ckd 7 品牌，含纯说明文字 + 含参数表格的手册）
3. 对比 3 组 token 目标值：**~250 token**（事实类查询下限，偏保守精确）、**~400 token**（通用起点）、**~600 token**（CJK 区间中段）
4. overlap 对比 2 档：**~12%**（传统默认）vs **0%**（对照 2026-01 的"无收益"发现，验证是否也适用于我们的中文技术内容）
5. 用黄金测试集（`scripts/rag_eval_queries.json`）里对应这 7 篇文档的 7 个用例，在**独立临时 collection + FLAT 精确索引**（隔离 ANN 近似噪声，只测切块本身的质量）下跑全部 6 组配置

**试点结果（`rag_chunk_pilot.py`，7 文档 / 7 用例 / 6 配置，均为 FLAT 精确搜索）：**

| 配置 | chunks/doc | top-1命中率 | top-k命中率 | grounded率 | avg top-1分数 | 总chunk数 |
|---|---:|---:|---:|---:|---:|---:|
| size=400 ovl=50 | 356.4 | 100% | 100% | 57% | **0.690** | 2495 |
| size=600 ovl=70 | 257.7 | 100% | 100% | 57% | **0.690** | 1804 |
| size=400 ovl=0  | 341.9 | 100% | 100% | 57% | 0.687 | 2393 |
| size=600 ovl=0  | 253.0 | 100% | 100% | 57% | 0.686 | 1771 |
| size=250 ovl=0  | 501.4 | 100% | 100% | 57% | 0.681 | 3510 |
| size=250 ovl=30 | 535.1 | 100% | 100% | 57% | 0.679 | 3746 |

**解读：**
- **top-1/top-k 命中率在 6 组配置下全部饱和在 100%**——这 7 个用例本身检索区分度不足以判断"哪个 chunk_size 更准"，唯一有区分度的信号是 avg top-1 分数（越高说明 chunk 内容与查询语义越贴合）和 chunk 总量（直接决定全量嵌入的算力/存储成本）
- **avg 分数排序：400/50 ≈ 600/70 > 400/0 ≈ 600/0 > 250/0 > 250/30**——250 token 明显偏小（比同门户 256-512 事实类推荐区间的下限还紧），分数最低；400 与 600 两档打平
- **overlap 效应很小但方向一致**：除 250 档外，overlap>0 都比 overlap=0 略高（+0.003~0.004），量级上与 §5.1 引用的"overlap 无显著收益"结论并不矛盾（既没有传统认为的大幅提升，也没有变差）
- **grounded率 57%（4/7）在全部 6 组配置下完全不变**——3.3 已补充：这不是 chunk_size 能解决的问题，是另外三个案例的检索区分度问题（见 §3.3 补充发现）
- **成本差异是真实的**：600/70 比 400/50 少 28% 总chunk数（1804 vs 2495），分数完全打平——对 350 篇全量而言意味着显著更少的嵌入算力与 Milvus 存储

**推荐：`chunk_size=400 token, overlap=50 token`**（约 12.5% overlap），理由：分数并列最优，且落在 §5.1 引用的"事实类查询 256-512 token"区间中段，是本项目单文档参数问答场景最貼合文献依据的选择。**`600/70` 是同分的备选**，如果全量 350 篇的嵌入算力/Milvus 存储成本是更优先的考量（少 28% chunk 量，分数完全不吃亏），选 600/70 同样站得住——这两者之间是纯粹的"贴合文献区间" vs "更省成本"的取舍，无客观对错，需用户拍板。

6. **表格感知分块**（不切碎参数表）列为 P2 长期项——工作量更大（需要 PyMuPDF 表格提取或类似方案），不阻塞本轮全量恢复，但在 §4 优化建议表中新增记录

---

## 6. 建议的实施顺序（等待确认）

```
Step 0（P0，已完成）：小样本（7篇）试跑 3×2=6 组 chunk_size/overlap 配置 → 黄金测试集对比 → 结果见 §5.3，用户拍板 400/50
Step 1（P0，已完成 07-11）：两处生产分块器改 token+字节双上限切块 → 350 篇全量重新同步 → 156,499 向量，详见 §2.2
Step 2（P0，已完成 07-11）：`nprobe` 10→128 → 黄金测试集实测 top-1 命中率 +14.3pp、消除结果漂移，详见 §3.3
Step 3（P0，未开始）：补 software-manual tag 注册 + scan_code 归属决策
Step 4（P1，可选，未开始）：query rewrite 增加 where_filter 自动抽取
Step 5（P2，长期，未开始）：表格感知分块；持续用黄金测试集回归
```

Step 0-2 已按计划全部完成：切块参数一次定案、全量嵌入一次做对、索引调优零成本生效，没有出现"嵌完又要删重跑"的浪费。剩余 Step 3-5 都不涉及重新嵌入，可以独立排期，互不阻塞。

---

**当前状态（07-11）**：Step 0/1/2 已完成并实测验证，RAG 检索能力已从"数据全丢"恢复到黄金测试集 top-1 命中率 42.9%、top-k 命中率 76.2%、grounded-and-correct 19.0%。**下一步待确认**：Step 3（tag 数据完整性修复）是否现在处理，Step 4（query rewrite 品牌过滤，可能是继续提升 top-1 命中率的下一个较大杠杆）是否排期，以及是否需要走 `/build` 走一遍子仓 PR + 聚合仓 submodule bump（本次改动：`openIndu-backend/app/services/rag_sync_service.py`、`openIndu-backend/app/services/milvus_service.py`）。
