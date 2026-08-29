# ADR — openIndu-portal 中英双语：`/en/` 路由与预渲染架构

| | |
|---|---|
| Status | Approved（2026-08-07，含附录 A 品牌措辞拍板） |
| Date | 2026-08-06 |
| Scope | `openIndu-portal` 子仓（React 18.3 + react-router 7 + Vite 6） |
| Owner | architect |
| Re-review | 2026-11-06，或触发条件：新增第三语种 / 预渲染路由 > 25 条 / Portal 迁至 SSR |

> **为什么是一个 ADR 而不是六个**：D1 决定了 D3/D4/D5 的形状（basename 方案让 `useLocation()` 返回去前缀路径，canonical、预渲染清单、302 落点都是它的推论），拆开会产生"改一个必须改四个"的假独立记录。D2 与 D6 本身可独立推翻，已在各自小节标注。

---

## Context

- 用户已定：中文守根路径，英文走 `/en/` 前缀；技术选型 **react-i18next**；需要 hreflang；LegalPages 不翻译且 `/en/privacy` 等 **302 回中文**；EN 页面**要**预渲染。翻译量约 9,750 字（中文侧 LegalPages 约 6,515 字已排除）。
- 现状事实（已核实）：
  - `src/app/routes.tsx` — 单个 `createBrowserRouter`，根 `path: "/"` + `Layout` + 21 个 children。
  - `src/app/components/SEO.tsx` — `useEffect` 里 upsert meta/canonical，`canonicalPath` 各页硬编码（`/vision` 等）。
  - `scripts/prerender.mjs` — `ROUTES` 是 11 条硬编码常量；靠 `vite preview` 的 SPA fallback 提供任意路径；`saveHtml()` 会把 `http://localhost:4173` 替换成 `https://www.openindu.com`。
  - `index.html` 硬编码 `<html lang="zh-CN">` 与 `og:locale=zh_CN`。
  - `nginx.k8s.conf`（`Dockerfile.k8s` 烤进生产镜像）与 `nginx.conf`（compose）均为 `try_files $uri $uri/ /index.html`。
- **前置依赖**：生产站目前零预渲染（musl 上跑不起 glibc Chrome，`prerender.mjs:186-198` catch 后 `process.exit(0)`）。该 bug 由 team-lead 在 `fix/k8s-dockerfile-prerender` 分支独立修复，先于 i18n 落地。**本 ADR 按"生产会有预渲染"设计。**

### 硬约束（贯穿全部决策）

**C1｜locale 必须能在运行时从 `location.pathname` 判定。** 预渲染依赖 `vite preview` 的 SPA fallback 提供 `/en/vision`：同一份 `dist/index.html` + 同一份 bundle 必须能渲出 EN。任何把 basename/locale 烤进构建产物的方案都会让 EN 预渲染拿到 ZH 内容，且失败是静默的。

**C2｜`<head>` 写入必须无条件且完整。** `prerender.mjs` 渲染 `/` 时会覆写 `dist/index.html`，而这正是 SPA fallback 的来源——之后每个路由都是从"上一次渲染完的文档"起步的。当前全站中文时这个污染不可见；引入 EN 后，残留的 `lang="zh-CN"` / ZH hreflang 会被烤进 EN 页面。两道防线：① `SEO.tsx` 每次都写全 locale 相关标签，绝不 `if` 跳过；② `ROUTES` 把 `/` 排到**最后**（只有 `/` 会覆写 fallback 源）。

---

## D1 — `/en/` 的实现机制 ★ reversible-late

| 选项 | 机制 | 评估 |
|---|---|---|
| **A. 单 router + 运行时 basename** | `createBrowserRouter(routes, { basename: detect() === "en" ? "/en" : "/" })`，`detect()` 读 `window.location.pathname` | ✅ 满足 C1。路由表零改动，全部 `<Link to="/vision">` 零改动（react-router 自动加前缀，匹配与生成两侧都对）。`useLocation().pathname` 返回**去前缀**路径 → canonical 只需拼一次前缀。单份 `dist`、单份资源缓存。代价：切换语言必须整页跳转（basename 是构造期参数），但这对 i18n 反而是**优点**——新文档、`lang` 干净、无半翻译中间态 |
| **B. 复制路由表挂 `/en` 子树** | `[{path:"/",children}, {path:"/en",children: makeChildren()}]` | ⚠️ 满足 C1，但每个 `<Link to>` 都要变 locale-aware（`useLocalizedHref`）——Layout 一处就 ~20 个链接，页面里还有更多。任何一处漏改，EN 页面就把用户悄悄踢回中文，且 lint 抓不到。PR-1 diff 直接冲破 RULE 4 的 400 行。路由表双份维护 |
| **C. 构建期双 bundle** | `vite build` 两次（`--base=/en/` + `VITE_LOCALE=en`），产物合并 | ❌ **违反 C1**。若强推，预渲染要改成起两个 preview server、跑两轮 puppeteer、分别落盘——构建时间翻倍、CI 复杂度翻倍、`/en` 的 `--base` 让静态资源 URL 分叉从而丧失共享缓存，而换来的收益（每语种包体略小）在 ~9,750 字的量级上不存在 |

**决策：A（单 router + 运行时 basename）。**

```ts
// src/i18n/locale.ts —— 唯一的 locale 真值来源
export type Locale = "zh" | "en";
export const detectLocale = (p = window.location.pathname): Locale =>
  p === "/en" || p.startsWith("/en/") ? "en" : "zh";
export const basenameFor = (l: Locale) => (l === "en" ? "/en" : "/");
export const stripPrefix = (p: string) => p.replace(/^\/en(?=\/|$)/, "") || "/";
export const toLocale = (l: Locale, p: string) => (l === "en" ? (p === "/" ? "/en" : `/en${p}`) : p);
```

**Consequences**
- `routes.tsx` 只多一行 `{ basename }`；children 数组原样保留。
- 语言切换 = `<a href>` 整页跳转（真锚点，可被爬虫发现，正是 Google 发现 EN 树的方式），不是 `<Link>`。
- ⚠️ **陷阱**：在 basename `/en` 下，`<Navigate to="/privacy">` 解析成 `/en/privacy` → **无限循环**。跨 locale 跳转只能用 `window.location.replace()`（见 D5）。
- 未登记 `/en/*` 的路径落到既有 `path: "*"` → NotFound，行为不变。

---

## D2 — locale 文件组织 ○ reversible-early

**决策：确认"按页面分 namespace"，加两条修正。**

```
src/locales/
├── zh/  common.json  home.json  motion-control.json  studio.json  vision.json
│        iiot.json  infrastructure.json  resources.json  chat.json  misc.json
└── en/  （同名镜像）
```

1. **每页的 SEO 文案（title / description / keywords）放进该页自己的 namespace，不单独建 `seo.json`。** 否则 PR-2..PR-5 每个都要改 `seo.json` → 四个分支必冲突，正好抵消分 namespace 的收益。
2. **注册表用 `import.meta.glob('./locales/*/*.json', { eager: true })`，不手写 import 清单。** 否则新增一个 namespace 就要改共享的 `i18n/index.ts`，冲突点又回来了。glob 是 Vite 原生能力，无新依赖。

并行性核对：PR-2..PR-5 各自只碰 `{zh,en}/<自己的页>.json` + 自己的 `.tsx` → **零重叠**。唯一共享文件 `common.json` 由 PR-1 一次性交付并冻结。

**eager 而非 lazy 是刻意的**：懒加载 namespace 会让首帧出现未翻译文本，与 puppeteer 的 1500ms 固定等待形成竞态——预渲染产物是否含译文将变成掷骰子。i18next 必须配 `initImmediate: false` + `react: { useSuspense: false }`，确保首次渲染即为终态。代价是双语全量进主包（估算 gzip < 30 KB），营销站可接受。

---

## D3 — SEO.tsx locale 感知 ★ reversible-late（错误的 canonical 要几周到几个月才能从索引里洗掉）

**问题**：`canonicalPath` 硬编码 `/vision`，EN 下会让 `/en/vision` 自指到 `https://www.openindu.com/vision` —— 这不只是"多页共用 canonical"，而是**整棵 EN 树自我声明为 ZH 的副本**，Google 会直接不收录。

| 选项 | 评估 |
|---|---|
| 各页改传 `canonicalPath={t("seo.path")}` | ❌ 把 SEO 正确性摊到 11 个页面，任一页漏改静默出错 |
| **SEO.tsx 内部加前缀，各页保持传 locale-中性路径** | ✅ 单点负责，页面侧零改动，漏不了 |

**决策：`canonicalPath` 语义改为"locale-中性路径"（页面继续传 `/vision`），前缀与 hreflang 由 SEO.tsx 统一计算。**

```tsx
const locale = useLocale();                      // 来自 D1 的同一个 detect
const path   = canonicalPath ?? stripPrefix(location.pathname);
const zhUrl  = `${origin}${path}`;
const enUrl  = `${origin}${toLocale("en", path)}`;

upsertCanonical(locale === "en" ? enUrl : zhUrl);
document.documentElement.lang = locale === "en" ? "en" : "zh-CN";
upsertMeta('meta[property="og:locale"]', { content: locale === "en" ? "en_US" : "zh_CN" });

if (localized !== false) {                        // 双语页
  upsertAlternate("zh-Hans",   zhUrl);
  upsertAlternate("en",        enUrl);
  upsertAlternate("x-default", zhUrl);            // 默认落中文，与 D6"不自动跳"一致
} else {
  removeAlternates();                             // ZH-only 页：一条都不发
}
```

**四条必须写进实现说明的规则**
1. **hreflang 必须互指。** LegalPages 只存在中文版，若中文侧仍宣告 `en → /en/privacy`，而后者 302 回中文，Google 判为无效互指。故 `SEO` 新增 `localized?: boolean`（默认 `true`），LegalPages 传 `localized={false}`，两侧都不发 alternate。
2. **`upsertAlternate` / `removeAlternates` 必须无条件执行**（C2）：`link[rel=alternate][hreflang="X"]` 选择器 upsert，ZH-only 页主动清除残留。
3. **`document.documentElement.lang` 必须运行时写**，因为 `index.html` 硬编码 `zh-CN`，不改就会被烤进每个 EN 预渲染文件。
4. `saveHtml()` 已经把 `localhost:4173` 全局替换为生产域名，canonical / alternate / og:url 自动变绝对生产 URL，**无需改预渲染脚本的这一段**。

**非功能目标（可断言）**：每个预渲染文件的 canonical 必须等于自身 URL；每个 EN 文件的 `zh-Hans` 目标必须在对应 ZH 文件里回指。PR-6 把这两条写成构建后断言。

---

## D4 — 预渲染路由清单 ★ 裁决

**裁定：预渲染 = 18 页；sitemap.xml = 22 条 URL。两个数字都对，但属于两份不同的清单——此前沟通中的"22"是把这两者混为一谈了。**

| 清单 | 组成 | 数量 |
|---|---|---|
| **预渲染（`ROUTES`）** | ZH 现有 11 条 + EN 7 条（`/en` 及 6 个共享子页；4 个 legal 页因 302 回中文而**排除**） | **18** |
| **sitemap.xml** | ZH 现有 13 条（含未预渲染的 `/resources/documents`、`/resources/software`）+ EN 9 条（同样排除 4 个 legal） | **22** |

EN 预渲染 7 条：`/en`、`/en/motion-control`、`/en/motion-control/studio`、`/en/vision`、`/en/iiot-platform`、`/en/infrastructure`、`/en/resources`。

`ROUTES` 从硬编码常量改为按 locale 生成：

```js
const SHARED  = ["/motion-control", "/motion-control/studio", "/vision",
                 "/iiot-platform", "/infrastructure", "/resources"];
const ZH_ONLY = ["/privacy", "/legal", "/cookies", "/legal-center"];  // EN 侧 302 回中文，不渲染

const ROUTES = [
  ...SHARED, ...ZH_ONLY,                     // 10
  ...SHARED.map((p) => `/en${p}`),           //  6
  "/en",                                     //  1 → dist/en/index.html
  "/",                                       //  1 → dist/index.html —— 必须最后（见 C2）
];                                           // = 18
```

**`/` 排最后是硬性要求，不是风格偏好**：`saveHtml("/")` 覆写 `dist/index.html`，而它是 SPA fallback 的来源。当前脚本把 `/` 排第一，导致后续 10 条全部从"已渲染的中文首页"起步——全中文时无害，加了 EN 就会污染 `lang` 与 hreflang。

`/en` 落盘为 `dist/en/index.html`，nginx `try_files $uri $uri/ /index.html` 对 `/en` 与 `/en/` 都能命中，无需额外配置。

sitemap.xml 本次**手工扩到 22 条**（含 `xhtml:link` alternates），保持 boring default；"从同一份 manifest 生成 sitemap"记入债务台账，触发条件：路由数 > 25 或新增第三语种。

---

## D5 — `/en/privacy` 的 302 落点 ◐ reversible-mid

| 选项 | 评估 |
|---|---|
| **nginx `return 302`** | ✅ 真 302，爬虫首跳即拿到 Location，不消耗抓取预算，无 JS 依赖。**RULE 8 不适用**——`nginx.k8s.conf` / `nginx.conf` 是 portal 仓内的构建资产，不是 K8s manifest（后者才必须在独立 GitOps 仓） |
| 客户端 `<Navigate>` | ❌ 先 200 再 JS 跳 = 软跳转；`/en/privacy` 可能被单独收录；无 JS 爬虫（GPTBot / Claude-Web，正是做预渲染的目标受众）看到空壳。且在 basename `/en` 下 `<Navigate to="/privacy">` 会解析成 `/en/privacy` → 无限循环 |

**决策：nginx 为权威，客户端留一层 dev/preview 对等网。**

```nginx
# nginx.k8s.conf 与 nginx.conf 都要加，位置在 location / 之前
location ~ ^/en/(privacy|legal|cookies|legal-center)/?$ {
    return 302 /$1;
}
```

两份 conf 都改，理由是本地 compose 栈必须与生产同构（否则"本地验证通过"不成立）。

客户端网：EN locale 下把这 4 条路由的 element 换成一个执行 `window.location.replace(stripPrefix(pathname))` 的小组件——**绝不能用 `<Navigate>`**（同上，会死循环）。它只在 `vite dev` / `vite preview` / nginx 规则被误删时生效；生产正常路径下永远不会执行。

robots.txt 不为这 4 条加 Disallow（Disallow 会挡住 Google 看见 302）。但需为 `/en/login`、`/en/register`、`/en/account` 补上与中文侧对等的 Disallow（8 个 user-agent 段各 3 行）。

---

## D6 — 语言检测与切换持久化 ○ reversible-early（但"自动跳"一旦上线并被抓取，回退代价很高 → 按 late 对待）

**决策：不按 `Accept-Language` 自动跳转；不持久化 localStorage。URL 是 locale 的唯一真值。**

不自动跳的四条理由（前两条是硬伤，不是偏好）：
1. **Googlebot 从美国 IP 抓取，`Accept-Language` 为 `en` 或缺省。** 自动跳意味着站点最重要的落地页、也是 `x-default` 目标的中文首页，被当成 EN 抓取。这是本次改造里能犯的最贵的错。
2. **预渲染会被污染。** puppeteer 默认 `Accept-Language: en-US` → 渲染 `/` 时被弹到 `/en/`，`dist/index.html` 里装的是英文首页。而脚本仍会打印 `18 prerendered, 0 failed` —— 静默失败。
3. 百度爬虫、以及浏览器语言为英文的中国用户（相当常见）会被推到英文站。
4. 100% 的访问在最热路径上多付一次往返。

**替代方案**：Header + Footer 各放一个显式切换器，用 `<a href={toLocale(other, currentNeutralPath)}>` 整页跳到**对位页面**（不是永远跳首页——跳首页会丢上下文，也丢掉一次内链权重传递）。真锚点 = 可被爬虫遍历，这正是 Google 发现 EN 树的主路径。

**不持久化的理由**：预渲染产物由 nginx 分发给所有用户，任何"读 localStorage 改变渲染结果"的逻辑都会与共享静态 HTML 冲突（第一个用户的偏好被烤进别人的页面，或首屏闪烁）。只有 2 个语种 + 常驻可见切换器时，持久化换不来什么。

若日后确需照顾回访用户，允许的形态只有一种：**可关闭的提示条**（"View this page in English →"），且必须在 `useEffect` 里挂载后渲染、绝不自动跳转。记入债务台账，不在本次范围。

`Vary: Accept-Language` 因此**不需要**（也就避免了 CDN 缓存碎片化）。

---

## 非功能目标

| 维度 | 目标 | 验证方式 |
|---|---|---|
| 延迟 | EN 页与 ZH 页同构（nginx 静态文件，无服务端协商），p95 首字节 < 200ms（境内） | 与现有 ZH 页对照 |
| 预渲染真实性 | 18 个文件全部含译文正文；EN 文件不得包含中文标题串"一栈贯通" | PR-6 构建后断言 |
| SEO 正确性 | 每文件 canonical == 自身 URL；hreflang 三元组互指；`lang` 属性与目录一致 | PR-6 构建后断言 |
| 包体 | 双语 locale JSON 合计 gzip ≤ 30 KB | build 输出比对 |
| 可观测 | `visitsApi.track(location.pathname)` 在 basename 方案下上报**去前缀**路径 → EN 流量会与 ZH 合并统计 | ⚠️ 已知缺口，见债务台账 |

**已知构建风险（PR-6 处理，此处仅记录）**：`prerender.mjs:58-61` 的 8 秒兜底 `resolvePromise(server)` 配合 `--strictPort`，会在存在僵尸 4173 进程时去渲染**旧 bundle**，却仍打印 "N prerendered, 0 failed"。PR-6 加 build-stamp 断言防这一类静默失败。

## 债务台账（本次刻意留下的）

| 条目 | 触发再评估的条件 |
|---|---|
| sitemap.xml 手工维护（22 条），未与预渲染 manifest 同源 | 路由数 > 25 或新增第三语种 |
| `visitsApi.track` 上报去前缀路径，EN/ZH 流量不可分 | 需要按语种看流量时（改为上报 `toLocale(locale, path)`） |
| `llms.txt` / `llms-full.txt` 仅中文 | EN 树被 AI 爬虫收录后 |
| `/en/chat` 走 RAG，后端知识库为中文，会用中文作答 | **需 product-manager 裁决**：EN 下隐藏智能咨询入口，还是接受中文作答 |
| 回访用户语言提示条（D6 的可选增强） | 有数据表明 EN 用户回访率显著时 |

---

## 附录 A — 术语表初稿（PR-1 交付物，待用户拍板）

> 格式：`中文 | 建议英译 | 备注`。定稿后落到 `openIndu-portal/docs/i18n-glossary.md`，PR-2..PR-5 必须遵循，不得各译各的。

### A1 品牌与叙事（最需要用户拍板的一组）

| 中文 | 建议英译 | 备注 |
|---|---|---|
| openIndu Community | openIndu Community | 不译 |
| openIndu-studio / openIndu-platform / openindu-station | 同名不译 | 仓库名即产品名，大小写照抄 |
| 一栈贯通，开放智造 | One Stack, End to End — Open Manufacturing | Home hero 主标题。备选：*One Stack, All the Way Through* |
| 工业自动化的端到端开源操作系统 | The End-to-End Open-Source OS for Industrial Automation | Home 副标题 + `<title>` |
| 从工艺参数到产线数据，一个栈打通 | From process parameters to line data — one stack, end to end. | Home / Footer 反复出现，必须统一 |
| 五大节点闭环 | The Five-Stage Closed Loop | 直译 node 在英文读起来像网络节点；建议用 stage。备选：*Five-Node Closed Loop* |
| 工艺知识 | Process Knowledge | 闭环节点 1 |
| 工程生成 | Engineering Generation | 闭环节点 2 |
| 跨品牌执行 | Cross-Brand Execution | 闭环节点 3。"跨品牌"营销语境亦可用 *vendor-neutral* |
| 采集与数据 | Acquisition & Data | 闭环节点 4 |
| 分析洞察 | Analytics & Insight | 闭环节点 5 |
| 三大核心产品 | Three Core Projects | 与社区战略"三核心项目"对齐 |
| 全链路开源 | Open Source End to End | Home benefits |
| 非标自动化 | Custom Automation | 直译 *non-standard automation* 在英文工业语境里不自然；行业习惯是 custom / bespoke machine building。**用户已确认 2026-08-07** |
| 端侧小模型 | On-Device Small Models (SLM) | 战略叙事词，页面尚未出现，先定调 |
| OT-IT | OT/IT | 行业写法是斜杠；"OT-IT 融合" → *OT/IT convergence* |
| 面板半导体工艺 | Display & Semiconductor Process | 面板 = flat-panel display；专栏名建议 *Display & Semiconductor Process* |

### A2 导航栏 / 页脚固定说法

| 中文 | 建议英译 | 备注 |
|---|---|---|
| 首页 | Home | |
| 下载中心 | Downloads | URL 保持 `/resources` 不变 |
| AI+运动控制 | AI + Motion Control | 加号两侧留空格，四个板块统一 |
| 概览 | Overview | 二级菜单 |
| openIndu-studio 平台 | openIndu-studio Platform | |
| AI+视觉 | AI + Machine Vision | 工业语境下 vision = machine vision，单用 Vision 过泛 |
| AI+工业互联网平台 | AI + Industrial IoT Platform | 正文里可简写 IIoT |
| AI+基础设施 | AI + Infrastructure | 该页实为 LLM API 网关 |
| 智能咨询 / 智能咨询机器人 | AI Assistant | 备选：*Ask openIndu* |
| 登录 / 注册 | Sign in / Sign up | |
| 退出登录 | Sign out | |
| 普通用户 / 会员 / 管理员 | User / Member / Admin | 角色标签 |
| 快速链接 | Quick Links | 页脚栏目 |
| 核心服务 | Core Services | 页脚栏目 |
| 相关平台 | Related Platforms | 页脚栏目 |
| 法律与隐私 | Legal & Privacy | 页脚栏目（链接目标仍是中文页） |
| 隐私声明 / 法律声明 / 关于 Cookies | Privacy Statement / Legal Notice / About Cookies | 仅链接文案译，页面不译 |
| 社区服务状态 / 社区管理平台 | Service Status / Community Admin | 外链 |
| 备案号 | ICP Filing No. | 编号本身照抄，中国大陆合规要求 |

### A3 领域术语（正文高频）

| 中文 | 建议英译 | 备注 |
|---|---|---|
| 上位机 | host-PC application | 直译 *upper computer* 是中式英语，英文读者不懂 |
| 运动控制卡 | motion control card | 控制器则用 *motion controller* |
| 电气 → BOM → IO → PLC/HMI | Electrical → BOM → I/O → PLC/HMI | 英文 I/O 带斜杠 |
| IO 地址表 | I/O address table | |
| 工艺窗口 / 缺陷图谱 / 节拍模型 | process window / defect taxonomy / takt-time model | |
| 良率归因 | yield attribution | |
| 产品追溯 | product traceability | |
| 数据大屏 | Operations Dashboard | 直译 *big screen* 不用；场景是车间看板 |
| 边缘网关 / 云边协同 | edge gateway / cloud-edge collaboration | |
| 工站 / 工站软件 | station / station software | 对应 openindu-station |
| 敬请期待 / 即将推出 | Coming soon | 两处中文说法合并为一个英文说法 |
| 正式推出 | Generally available | 或 *Now available* |
| 联系我们了解更多 | Contact us to learn more | CTA |
| 微信扫码关注公众号 | Follow us on WeChat | |

---

## 附录 B — PR-1 影响清单（RULE 4：单次改动 ≤ 400 行）

**结论：按原范围，PR-1 约 500 行，超 RULE 4 上限 → 必须拆成 PR-1a / PR-1b。** 拆分点选在"不可见的基础设施"与"可见的外壳翻译"之间，两者各自可独立验证、独立回滚，不是为过审而做的形式切分。

### PR-1a｜i18n foundation（无可见 UI 变化）

| 文件 | 动作 | 估计行数 |
|---|---|---|
| `package.json` | 加 `i18next` + `react-i18next` | +2 |
| `package-lock.json` | 生成物 | 不计入（PR 描述里注明） |
| `docs/i18n-glossary.md` | 新建（附录 A 定稿后落盘） | +55 |
| `src/i18n/locale.ts` | 新建：detect / basenameFor / stripPrefix / toLocale | +35 |
| `src/i18n/index.ts` | 新建：i18next init + `import.meta.glob` 注册表 + `initImmediate:false` | +40 |
| `src/i18n/LocaleProvider.tsx` | 新建：`useLocale()` context | +25 |
| `src/main.tsx` | `import "./i18n"` | +1 |
| `src/app/routes.tsx` | 加 `{ basename }`；EN 下 4 条 legal 路由换 `RedirectToZh` | ~15 |
| `src/app/components/SEO.tsx` | locale 感知 canonical + hreflang 三元组 + `<html lang>` + `og:locale` + `localized` prop | ~45 |
| `src/app/pages/LegalPages.tsx` | 4 处 `<SEO>` 加 `localized={false}` | +4 |
| `src/__tests__/i18n-locale.test.ts` | 新建：前缀往返、`/en` 无斜杠、`/enigma` 不误判 | +45 |
| `src/__tests__/seo-hreflang.test.tsx` | 新建：EN 自指、ZH-only 页不发 alternate、`lang` 属性 | +55 |
| | **合计** | **≈ 322 行**（含 55 行文档） |

### PR-1b｜shell translation（外壳可见翻译）

| 文件 | 动作 | 估计行数 |
|---|---|---|
| `src/locales/zh/common.json` | 新建：导航 + 页脚 + 认证 chrome（~45 键） | +47 |
| `src/locales/en/common.json` | 同上镜像 | +47 |
| `src/app/components/LanguageSwitcher.tsx` | 新建：`<a href>` 整页跳对位页面 | +30 |
| `src/app/components/Layout.tsx` | ~40 处字面量换 `t(...)`；桌面 + 移动各挂一个切换器 | ~70 |
| `src/__tests__/language-switcher.test.tsx` | 新建：ZH↔EN 对位路径、根路径特例 | +40 |
| | **合计** | **≈ 234 行** |

### PR-1 明确**不**碰的东西

- `scripts/prerender.mjs`、`public/sitemap.xml`、`public/robots.txt`、`nginx.k8s.conf`、`nginx.conf` —— 全部归 **PR-6**（预渲染 + SEO 资产 + 302 规则）。PR-1a 之后 `/en/*` 已可访问且 SEO 正确，只是尚未预渲染、尚未被 302 保护；这是安全的中间态。
- 任何 `src/app/pages/*.tsx` 正文（LegalPages 那 4 行 `localized={false}` 除外）—— 归 PR-2..PR-5，每 PR 一个页面 namespace，互不冲突。

### 交付顺序

`PR-1a → PR-1b → (PR-2 ∥ PR-3 ∥ PR-4 ∥ PR-5) → PR-6`

PR-1a 是全部后续 PR 的硬前置（`useLocale` / `t` 必须先存在）。PR-1b 与 PR-2..PR-5 之间无文件重叠，可并行。PR-6 必须最后，因为预渲染断言要求 EN 页面已有译文。**前提：team-lead 的 `fix/k8s-dockerfile-prerender` 先合并**，否则 PR-6 的断言会在一个从不产出预渲染文件的构建里空转。
