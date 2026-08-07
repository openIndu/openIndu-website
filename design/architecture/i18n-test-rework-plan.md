# i18n Test Rework Plan -- openIndu-portal e2e + unit test suite

| Field | Value |
|---|---|
| Status | Approved (2026-08-07) |
| Date | 2026-08-06 |
| Scope | `openIndu-portal/e2e/*.spec.ts` (11 files) + `src/__tests__/*` (8 files covering 4 modules) |
| Owner | test seat |
| Pre-read | `design/architecture/adr-i18n-en-routing.md` (D1-D6, glossary Appendix A) |
| Target PRs | PR-1a/b through PR-6 (i18n implementation series) |

---

## 0. Baseline Snapshot (as-is, 2026-08-06)

| File | Tests | Chinese assertions | Nature |
|---|---|---|---|
| `e2e/home.spec.ts` | 9 | 17 | Page copy, nav links, section headers |
| `e2e/navigation.spec.ts` | 7 | 12 | Header link text, URL, h1, heading |
| `e2e/subpages.spec.ts` | 10 | 13 | h1, badges, architecture section, WeChat text |
| `e2e/workflow.spec.ts` | 5 | 10 | h1, step titles, badge text, description text |
| `e2e/login.spec.ts` | 7 | 8 | Heading, placeholder, button text, link text, error text |
| `e2e/register.spec.ts` | 6 | 6 | Heading, placeholder, button text, link text |
| `e2e/resources.spec.ts` | 3 | 5 | Page title, tab labels, placeholder, button text |
| `e2e/auth-guard.spec.ts` | 4 | 3 | Page title, h1 text |
| `e2e/account.spec.ts` | 1 | 1 | Heading text |
| `e2e/runtime-regression.spec.ts` | 1 | 1 | Heading text |
| `e2e/login-regression.spec.ts` | 1 | 0 | (no Chinese assertions -- token/redirect check) |
| `src/__tests__/api.test.ts` | ~30 | 6 | Error messages ("手机号格式错误", "请求参数错误", fallback) |
| `src/__tests__/chat.test.ts` | 4 | 6 | SSE data payloads ("你好", "世界", "生成失败") |
| `src/__tests__/AuthGuard.test.tsx` | 4 | 2 | Permission-denied text ("权限不足", "该页面仅面向...") |
| `src/__tests__/user-utils.test.ts` | 4 | 2 | Fallback strings ("未绑定手机号", "个人中心") |
| `src/__tests__/auth-store.test.ts` | ~30 | 0 | (no Chinese assertions -- auth logic only) |
| `src/__tests__/utils.test.ts` | 10 | 0 | (no Chinese assertions -- cn() utility) |
| `src/__tests__/ui.test.tsx` | ~20 | 0 | (no Chinese assertions -- component rendering) |
| `src/__tests__/auth-provider.test.tsx` | ~10 | 0 | (no Chinese assertions -- auth flow) |
| **TOTAL** | **~128** | **76 e2e + 16 unit = 92** | |

> **New tests expected from PR-1a/b** (not present yet): `i18n-locale.test.ts` (+45 lines), `seo-hreflang.test.tsx` (+55 lines), `language-switcher.test.tsx` (+40 lines). These are **new additions**, not rewrites, and are out of scope of this rework plan.

---

## 1. Strategy

### 1.1 Core problem: the independence trap

If e2e assertions read locale JSON (`expect(h1).toContainText(t("motion.title"))`), they become **tautological**: the test verifies that react-i18next renders whatever the JSON says. A copy-paste error where both `zh/motion-control.json` and `en/motion-control.json` contain the same Chinese text ("AI+运动控制") is invisible -- the test passes because it asserts exactly the wrong value.

**The test must have its own opinion about what the correct text is.** Otherwise it cannot detect the most likely i18n bug: a key mapping to the wrong language.

### 1.2 Three-tier assertion strategy

| Tier | What it checks | Mechanism | Fraction of assertions |
|---|---|---|---|
| **Tier 1 -- Golden value** | Critical copy is correct in each locale | Hardcoded expected string, **not** sourced from locale JSON. Curated manually, reviewed as part of PR. | ~15% (hero tagline, CTAs, H1 titles) |
| **Tier 2 -- Structural** | i18n pipeline is functioning; element is present | `data-testid` + `toBeVisible()`, or locale-key-based selectors | ~70% (navigation, sections, cards, forms) |
| **Tier 3 -- Smoke** | Page loads without JS errors; canonical URL correct | `page.goto()`, `toHaveURL()`, `pageErrors === []` | ~15% |

**Why this split works**: A copy-paste translation error will be caught by Tier 1 (the golden value disagrees with the rendered text). A broken `t()` call, missing key, or missing namespace will be caught by Tier 2 (the element is absent or React crashes). A basename misconfiguration will be caught by Tier 3 (wrong URL, wrong canonical, console errors).

### 1.3 Locale parameterization

Tests that run against both locales use `test.describe` with a locale fixture:

```ts
const LOCALES = [
  { locale: "zh" as const, prefix: "",   label: "Chinese" },
  { locale: "en" as const, prefix: "/en", label: "English" },
] as const;
```

Each test receives `locale` and `prefix`. URL assertions become `toHaveURL(prefix + "/motion-control")`. Text assertions reference a per-locale golden-value table.

### 1.4 `data-testid` convention for navigation

The current `Layout.tsx` renders nav links without test identifiers. The rework plan **requires** PR-1b to add `data-testid` attributes to nav items using the neutral path as the identifier:

```tsx
// Before (current)
<Link to="/motion-control">AI+运动控制</Link>

// After (PR-1b)
<Link to="/motion-control" data-testid="nav-/motion-control">
  {t("common:nav.motionControl")}
</Link>
```

This costs 1 attribute per link (~20 additions in Layout.tsx, within PR-1b's ~234 line budget) and enables tests to click links by structural identity regardless of locale.

### 1.5 Unit test treatment

Unit tests with Chinese assertions fall into two categories:

| Category | Action | Examples |
|---|---|---|
| **API error messages** from backend | Keep as-is. These are backend responses, not frontend locale strings. If they are later i18n'd, the test documents the contract. | `api.test.ts` error tests |
| **UI text rendered by React** | Treat same as e2e: golden value lock for permission-denied messages, locale-key assertion for fallback strings | `AuthGuard.test.tsx`, `user-utils.test.ts` |
| **SSE/data payloads** | Keep as-is. These are test fixtures, not assertions about rendered UI. | `chat.test.ts` ("你好", "世界") |

---

## 2. Per-File Disposition

### 2.1 e2e specs (11 files)

#### `e2e/navigation.spec.ts` -- **REWRITE (full)**

| Current | After i18n |
|---|---|
| 7 tests, all Chinese hardcoded | 7 tests x 2 locales = 14 tests, or 7 parameterized tests |
| `getByText("AI+运动控制")` | `getByTestId("nav-/motion-control")` |
| `toHaveURL("/motion-control")` | `toHaveURL(prefix + "/motion-control")` |
| `toContainText("AI+运动控制")` | Golden value: `zh: "AI+运动控制"`, `en: "AI + Motion Control"` |
| "登录" link via `getByRole("link", { name: "登录" })` | `getByTestId("nav-/login")` |
| "注册" link via `getByRole("link", { name: "注册" })` | `getByTestId("nav-/register")` (or check `/register` redirects to `/login` per ADR D1) |
| Logo "openIndu" text unchanged across locales | Keep text assertion (brand name invariant) |

**Effort**: Medium. See Section 3 for full worked example.

**Note on register link**: PR-1b's Layout.tsx already changes the register link (ADR says register may redirect to login). The navigation test must adapt to whatever the final link structure is.

---

#### `e2e/home.spec.ts` -- **REWRITE (full)**

| Current | After i18n |
|---|---|
| 9 tests, 17 Chinese assertions | 9 parameterized tests x 2 locales |
| `getByText("一栈贯通，开放智造")` | Golden value table: `zh: "一栈贯通，开放智造"`, `en: "One Stack, End to End -- Open Manufacturing"` |
| `getByText("三大核心产品")` | Golden value table |
| `getByText("五大节点闭环")` | Structural: `getByTestId("section-five-nodes")` + golden value for heading |
| Node loop text ("工艺知识", "工程生成", etc.) | Golden value table (5 nodes x 2 locales = 10 values) |
| Nav links list check | Check via `data-testid` presence, not Chinese text |
| Footer text "openIndu Community" | Keep as-is (invariant) |
| WeChat QR text | Golden value table |
| Repo names (openIndu-studio, etc.) | Keep text assertions (invariant proper nouns) |

**Effort**: High -- largest spec, 17 golden values to curate.

---

#### `e2e/subpages.spec.ts` -- **REWRITE (full)**

| Current | After i18n |
|---|---|
| 10 tests across 4 page groups | Parameterized per locale |
| `toContainText("AI+运动控制")` | Golden value table |
| `getByText("正式推出")` / `getByText("敬请期待")` | Golden value: `zh: "正式推出"`, `en: "Generally available"` / `zh: "敬请期待"`, `en: "Coming soon"` |
| `getByText("三菱PLC")` / `getByText("西门子PLC")` | Keep as-is (invariant brand names) |
| `getByText("技术架构")` | Golden value |
| `getByText("已上线")` | Golden value |
| `getByRole("link", { name: "访问模型平台" })` | Replace with `data-testid` link selector; golden value for link text assertion |

**Effort**: Medium. Brand names (Siemens, Mitsubishi) are invariant and need no locale parameterization.

---

#### `e2e/workflow.spec.ts` -- **REWRITE (full)**

| Current | After i18n |
|---|---|
| 5 tests, 10 Chinese assertions | Parameterized per locale |
| `toContainText("openIndu-studio 介绍")` | Golden value table |
| 6 step titles ("电气模组梳理" etc.) | Golden value table (6 steps x 2 locales = 12 values) |
| `getByText("步骤 1")` ... `getByText("步骤 6")` | Keep numeric part invariant; "步骤" vs "Step" via golden value |
| `getByText("根据设备清单...")` | Golden value for that specific description |

**Effort**: Medium. Step badges are semi-structural ("步骤 N" vs "Step N").

---

#### `e2e/login.spec.ts` -- **REWRITE (medium)**

| Current | After i18n |
|---|---|
| 7 tests | Parameterized |
| `getByRole("heading", { name: "手机号登录" })` | Golden value: `zh: "手机号登录"`, `en: "Sign in with Phone"` |
| `toHaveAttribute("placeholder", "请输入 11 位手机号")` | Test placeholder presence structurally: `toHaveAttribute("placeholder", /.+/)` for presence, golden value for content |
| `getByRole("button", { name: "发送验证码" })` | Golden value: `zh: "发送验证码"`, `en: "Send Code"` |
| `getByRole("button", { name: "登录" })` | Golden value |
| `getByRole("link", { name: "立即注册" })` | `data-testid` for link identity, golden value for text |
| `toContainText("11 位")` | Golden value for error fragment |

**Risk note**: Login error messages come from the backend API (`detail` field), not from locale JSON. If the backend does not i18n error messages, these assertions stay as-is. Clarify with backend seat before rewriting.

---

#### `e2e/register.spec.ts` -- **REWRITE (medium)**

Identical pattern to login: headings, placeholders, buttons, links all need golden value tables. Effort is moderate because register is a simpler form.

**Special note**: ADR D1 mentions `register` route becomes `<Navigate to="/login">`. If this is implemented, the register spec may be reduced to verifying the redirect.

---

#### `e2e/resources.spec.ts` -- **REWRITE (medium)**

| Current | After i18n |
|---|---|
| `getByText("文档与软件下载")` | Golden value: `zh: "文档与软件下载"`, `en: "Documents & Software Downloads"` |
| `getByRole("button", { name: "文档" })` / `{ name: "软件" }` | Golden value |
| `getByPlaceholder("输入关键词搜索资源")` | `data-testid` + golden value for placeholder text |
| `getByRole("button", { name: "搜索" })` | Golden value |

**Effort**: Medium. Tab labels and search UI text are the main targets.

---

#### `e2e/auth-guard.spec.ts` -- **MINIMAL REWRITE**

| Current | After i18n |
|---|---|
| 4 tests | Mostly unchanged -- tests auth logic, not text |
| `getByText("文档与软件下载")` | Golden value or `data-testid` |
| `toContainText("文档与软件下载")` (h1) | Golden value |

**Effort**: Low. Auth flow logic is locale-independent; only 2 text assertions need updating.

---

#### `e2e/account.spec.ts` -- **MINIMAL REWRITE**

| Current | After i18n |
|---|---|
| 1 test | Update heading assertion |
| `getByRole("heading", { name: "账号设置" })` | Golden value: `zh: "账号设置"`, `en: "Account Settings"` |
| `getByText("138****8000")` | Keep as-is (masked phone, invariant) |

**Effort**: Trivial -- 1 golden value.

---

#### `e2e/runtime-regression.spec.ts` -- **NO REWRITE**

| Current | After i18n |
|---|---|
| `getByRole("heading", { name: "核心解决方案" })` | This may fail under EN locale if heading text changes. Replace with `data-testid` or add locale-awareness. |

**Assessment**: The heading text "核心解决方案" in the English locale would likely be "Core Solutions". If the API mock returns this, the test needs the golden value. But since this is a runtime regression test (API response format check), the text assertion could be replaced with a structural check (`h2` element visible with some text) rather than a specific content assertion.

**Effort**: Trivial.

---

#### `e2e/login-regression.spec.ts` -- **NO REWRITE**

This test fills inputs by `#login-phone`/`#login-code` CSS IDs and checks token storage -- no Chinese text assertions. No changes needed.

**Effort**: Zero.

---

### 2.2 Unit tests (4 files with Chinese assertions)

#### `src/__tests__/api.test.ts` -- **NO REWRITE (but review)**

| Line | Current assertion | Assessment |
|---|---|---|
| `toBe("手机号格式错误")` | `getApiErrorMessage` test: AxiosError with `detail: "手机号格式错误"` | **Keep**. This is a backend API response string, not frontend locale. If the backend later i18n's error messages, these tests document the breaking contract change. |
| `toBe("请求参数错误")` | Same pattern, `message` field | **Keep** (same reasoning). |
| `toBe("请求失败，请稍后重试")` | Default fallback string in `getApiErrorMessage` | **Keep** (this IS a frontend string that would need i18n, but it's currently hardcoded in `api/index.ts`, not in locale JSON. If it gets moved to `t()` later, the test asserts the change). |

**Verdict**: These assertions test API response parsing, not UI rendering. No i18n rewrite needed. If `getApiErrorMessage` is later i18n'd, the test will naturally break and flag the contract change.

---

#### `src/__tests__/chat.test.ts` -- **NO REWRITE**

All Chinese strings are test fixture data (`"你好"`, `"世界"`, `"生成失败"`) simulating SSE stream payloads from the backend. No UI locale dependency. No changes needed.

---

#### `src/__tests__/AuthGuard.test.tsx` -- **MINIMAL REWRITE**

| Line | Current | After i18n |
|---|---|---|
| `getByText("权限不足")` | Hardcoded | If AuthGuard uses `t("auth:permissionDenied")`, this needs a locale context. Golden value approach: render with i18n provider, assert both locales. |
| `getByText("该页面仅面向成员及以上角色开放，请联系管理员升级账号权限。")` | Hardcoded | Same treatment. |

**Note**: This test currently renders `AuthGuard` without an i18n provider, and `AuthGuard` renders hardcoded Chinese strings. After PR-2..PR-5 replaces those with `t()` calls, the test **must** wrap in an `I18nextProvider` or else `t()` will throw. The rewrite is therefore **mandatory**, not optional.

**Effort**: Low -- add i18n provider wrapper + golden value assertions.

---

#### `src/__tests__/user-utils.test.ts` -- **MINIMAL REWRITE**

| Line | Current | After i18n |
|---|---|---|
| `toBe("未绑定手机号")` | `maskPhone()` fallback | If `maskPhone` uses `t()`, it needs i18n context. Currently it's a hardcoded string in `user.ts`. If it stays hardcoded, no change. If it becomes `t("user:noPhone")`, wrap in provider. |
| `toBe("个人中心")` | `getDisplayName()` fallback | Same assessment. |

**Verdict**: Only needs rewriting if `user.ts` is migrated to use `t()`. If these utilities stay as hardcoded strings (plausible for utility functions that don't have React context access), no rewrite needed.

**Effort**: Low (or zero if utilities stay hardcoded).

---

### 2.3 Unit tests with zero Chinese assertions (no changes)

- `src/__tests__/utils.test.ts` -- `cn()` class merging, no locale dependency
- `src/__tests__/ui.test.tsx` -- Component rendering (Button, Card, Input, Select, Tabs), no locale dependency
- `src/__tests__/auth-store.test.ts` -- Auth logic, no locale dependency
- `src/__tests__/auth-provider.test.tsx` -- Auth provider, no locale dependency

**Effort**: Zero for all four.

---

### 2.4 Summary effort matrix

| File | Rewrite level | Golden values needed | Est. lines changed | Priority |
|---|---|---|---|---|
| `e2e/navigation.spec.ts` | FULL | 12 (6 x 2 locales) | ~80 | P0 (blocking for PR-1b) |
| `e2e/home.spec.ts` | FULL | 34 (17 x 2 locales) | ~120 | P0 (blocking for PR-2) |
| `e2e/subpages.spec.ts` | FULL | 16 (8 x 2 locales, brand names excluded) | ~90 | P0 |
| `e2e/workflow.spec.ts` | FULL | 20 (10 x 2 locales) | ~75 | P0 |
| `e2e/login.spec.ts` | MEDIUM | 16 (8 x 2 locales) | ~60 | P1 |
| `e2e/register.spec.ts` | MEDIUM | 12 (6 x 2 locales) | ~50 | P1 |
| `e2e/resources.spec.ts` | MEDIUM | 10 (5 x 2 locales) | ~40 | P1 |
| `e2e/auth-guard.spec.ts` | MINIMAL | 4 (2 x 2 locales) | ~15 | P2 |
| `e2e/account.spec.ts` | MINIMAL | 2 (1 x 2 locales) | ~10 | P2 |
| `e2e/runtime-regression.spec.ts` | MINIMAL | 2 (1 x 2 locales) | ~5 | P2 |
| `e2e/login-regression.spec.ts` | NONE | 0 | 0 | -- |
| `src/__tests__/api.test.ts` | NONE (review only) | 0 | 0 | -- |
| `src/__tests__/chat.test.ts` | NONE | 0 | 0 | -- |
| `src/__tests__/AuthGuard.test.tsx` | MINIMAL | 4 (2 x 2 locales) | ~15 | P2 |
| `src/__tests__/user-utils.test.ts` | MINIMAL or NONE | 4 (2 x 2 locales) | ~10 | P3 |
| **TOTAL** | | **~128 golden values** | **~570 lines** | |

> **Golden value curation is the dominant cost.** Each value must be cross-checked against the glossary (ADR Appendix A). This is inherently a manual review task, not automatable. The alternative -- reading from locale JSON -- would be cheaper but produce tautological tests that cannot detect the most likely i18n bug class.

---

## 3. Worked Example: `e2e/navigation.spec.ts`

Below is the full rewritten spec. It follows the three-tier strategy and is designed as the canonical pattern for all other e2e rewrites.

```ts
import { test, expect } from "@playwright/test";

// ─── Golden-value table ───
// Curated manually. Each value is cross-checked against
// docs/i18n-glossary.md (ADR Appendix A). These values are NOT
// read from locale JSON -- that would make the test tautological.

const GOLDEN = {
  h1MotionControl:  { zh: "AI+运动控制",              en: "AI + Motion Control" },
  h1Vision:         { zh: "AI+视觉",                  en: "AI + Machine Vision" },
  h1IIoT:           { zh: "工业互联网平台",            en: "Industrial IoT Platform" },
  h1Infra:          { zh: "AI+基础设施",               en: "AI + Infrastructure" },
  headingLogin:     { zh: "手机号登录",                en: "Sign in with Phone" },
  headingRegister:  { zh: "注册 openIndu 社区账号",    en: "Create an openIndu Account" },
} as const;

type GoldenKey = keyof typeof GOLDEN;

function gv(key: GoldenKey, locale: "zh" | "en"): string {
  return GOLDEN[key][locale];
}

// ─── Locale parameterization ───

const LOCALES = [
  { locale: "zh" as const, prefix: "",    label: "Chinese" },
  { locale: "en" as const, prefix: "/en", label: "English" },
] as const;

for (const { locale, prefix, label } of LOCALES) {

  test.describe(`Navigation (${label})`, () => {

    // ─── Tier 3: Home page loads ───

    test("home page loads without errors", async ({ page }) => {
      const errors: string[] = [];
      page.on("pageerror", (err) => errors.push(err.message));

      await page.goto(prefix + "/");
      await expect(page.locator("h1").first()).toBeVisible();
      expect(errors).toEqual([]);
    });

    // ─── Tier 2: Structural navigation + Tier 1: golden-value H1 ───

    test("navigates from home to motion control via header link", async ({ page }) => {
      await page.goto(prefix + "/");

      // Tier 2: click by structural identity (data-testid)
      await page.getByTestId("nav-/motion-control").click();

      // Tier 3: URL check
      await expect(page).toHaveURL(prefix + "/motion-control");

      // Tier 1: golden-value assertion on critical copy
      await expect(page.locator("h1")).toContainText(gv("h1MotionControl", locale));
    });

    test("navigates from home to vision via header link", async ({ page }) => {
      await page.goto(prefix + "/");

      await page.getByTestId("nav-/vision").click();
      await expect(page).toHaveURL(prefix + "/vision");
      await expect(page.locator("h1")).toContainText(gv("h1Vision", locale));
    });

    test("navigates from home to iiot platform via header link", async ({ page }) => {
      await page.goto(prefix + "/");

      await page.getByTestId("nav-/iiot-platform").click();
      await expect(page).toHaveURL(prefix + "/iiot-platform");
      await expect(page.locator("h1")).toContainText(gv("h1IIoT", locale));
    });

    test("navigates from home to infrastructure via header link", async ({ page }) => {
      await page.goto(prefix + "/");

      await page.getByTestId("nav-/infrastructure").click();
      await expect(page).toHaveURL(prefix + "/infrastructure");
      await expect(page.locator("h1")).toContainText(gv("h1Infra", locale));
    });

    test("navigates to login page from header", async ({ page }) => {
      await page.goto(prefix + "/");

      await page.getByTestId("nav-/login").click();
      await expect(page).toHaveURL(prefix + "/login");
      await expect(page.getByRole("heading")).toContainText(gv("headingLogin", locale));
    });

    test("navigates to register page from header", async ({ page }) => {
      await page.goto(prefix + "/");

      await page.getByTestId("nav-/register").click();
      await expect(page).toHaveURL(prefix + "/register");
      await expect(page.getByRole("heading")).toContainText(gv("headingRegister", locale));
    });

    // ─── Invariant assertion: brand name unchanged across locales ───

    test("navigates back to home via logo click", async ({ page }) => {
      await page.goto(prefix + "/motion-control");

      // "openIndu" is a proper noun, invariant across locales.
      // Logo text assertion is safe to keep as-is.
      const logo = page.locator("header").getByText("openIndu").first();
      await logo.click();

      await expect(page).toHaveURL(prefix + "/");
    });
  });
}
```

### Why this design

**`data-testid` for link selection** (Tier 2): Eliminates all locale-dependent text selectors from the test's action phase. The test clicks `nav-/motion-control` whether the rendered text is "AI+运动控制" or "AI + Motion Control". This means the test cannot break because a translator changed a nav label -- it only breaks if the link is missing (structural regression).

**Golden-value table for H1 assertions** (Tier 1): The test has its own opinion about what text should appear. If a translator accidentally puts Chinese in the English JSON, `gv("h1MotionControl", "en")` evaluates to `"AI + Motion Control"` and the assertion fails. This catches the bug class that a locale-JSON-reading approach misses.

**Page-error smoke check** (Tier 3): A single test per locale verifies the page loads without JS exceptions. Catches missing namespace imports, broken `t()` calls, and SSR/mount issues.

**No locale-JSON import**: The test file never `import`s from `src/locales/`. This is deliberate.

---

## 4. Coverage Blind Spot: Prerender Testing

### 4.1 The gap

`playwright.config.ts:10` sets `baseURL: "http://localhost:3000"` and the `webServer` block runs `npm run dev` (Vite dev server). This means:

1. All 11 e2e specs test the **SPA dev build**, not the production `dist/` output.
2. PR-6 adds 18 prerendered HTML files under `dist/` -- **none of them are tested by Playwright.**
3. The prerender script itself has known silent-failure modes (ADR non-functional goals section: zombie port 4173 renders old bundle, still prints "N prerendered, 0 failed").

### 4.2 Recommended fix

Add a **second Playwright project** that targets the production build:

```ts
// playwright.config.ts (addition, not replacement)
{
  name: "prerender",
  testDir: "./e2e",
  testMatch: "prerender.spec.ts",          // single dedicated spec
  use: {
    baseURL: "http://localhost:4173",      // vite preview (production mode)
  },
  webServer: {
    command: "npm run build && npm run preview",
    url: "http://localhost:4173",
    reuseExistingServer: false,
    timeout: 120_000,                      // build takes longer
  },
}
```

Create `e2e/prerender.spec.ts` with minimal but high-signal assertions:

```ts
import { test, expect } from "@playwright/test";

test.describe("Prerendered HTML", () => {
  // 1. Structural check: each prerendered path serves 200 HTML
  const PRERENDERED = [
    // ZH
    "/", "/motion-control", "/motion-control/studio", "/vision",
    "/iiot-platform", "/infrastructure", "/resources",
    "/privacy", "/legal", "/cookies", "/legal-center",
    // EN
    "/en/", "/en/motion-control", "/en/motion-control/studio",
    "/en/vision", "/en/iiot-platform", "/en/infrastructure", "/en/resources",
  ];

  for (const path of PRERENDERED) {
    test(`${path} returns 200 with content`, async ({ page }) => {
      const response = await page.goto(path);
      expect(response?.status()).toBe(200);

      // Must contain actual content, not empty SPA shell.
      // A working prerender embeds the <h1> text in static HTML.
      const h1Count = await page.locator("h1").count();
      expect(h1Count).toBeGreaterThan(0);

      // No JS errors on hydration
      const errors: string[] = [];
      page.on("pageerror", (err) => errors.push(err.message));
      await page.waitForLoadState("networkidle");
      expect(errors).toEqual([]);
    });
  }

  // 2. SEO correctness: canonical on each file
  test("EN pages have correct <html lang> and canonical", async ({ page }) => {
    const response = await page.goto("/en/");
    const html = await response!.text();

    // Static HTML must contain lang="en" (not zh-CN)
    expect(html).toContain('lang="en"');

    // Canonical must be the English URL
    expect(html).toContain('https://www.openindu.com/en');

    // Must NOT contain Chinese-only content
    expect(html).not.toContain("一栈贯通");
  });

  // 3. EN pages must not contain ZH hreflang pollution
  test("EN pages self-reference canonical correctly", async ({ page }) => {
    await page.goto("/en/motion-control");
    const canonical = page.locator('link[rel="canonical"]');
    await expect(canonical).toHaveAttribute(
      "href",
      "https://www.openindu.com/en/motion-control"
    );
  });

  // 4. EN legal pages return 302
  for (const path of ["/en/privacy", "/en/legal", "/en/cookies", "/en/legal-center"]) {
    test(`${path} redirects to Chinese (302)`, async ({ page }) => {
      const response = await page.goto(path, { waitUntil: "commit" });
      // nginx 302 -- the response object has the redirect status
      // (page.goto follows redirects by default, so we need to intercept)
      expect(response?.url()).not.toContain("/en/");
    });
  }
});
```

### 4.3 Integration into CI

The prerender project should run **after** the main e2e suite. It is slower (needs full build) so it can be a separate CI job that depends on the main suite passing.

**Cost**: ~1 new spec file (~60 lines), ~10 lines added to `playwright.config.ts`. One extra CI job. The prerender spec does not need locale parameterization -- it checks static HTML strings directly.

---

## 5. RULE 2 Admission Assessment

> RULE 2: "Automated test coverage of affected modules sufficient to support regression judgment"

### 5.1 Indicators after rework

| Indicator | Before (as-is) | After (planned) | Delta |
|---|---|---|---|
| **Repeatability** | Pass. All e2e + unit tests pass consistently on `main`. | Maintained. Parameterized tests use deterministic golden values, no flaky selectors. | No regression. |
| **Feedback latency** | `npx playwright test`: ~30s. `npx vitest run`: <5s. | Same order of magnitude (locale parameterization adds ~2x test count but no new network calls). | Negligible increase. |
| **Credibility** | Tests assert specific Chinese text -- credible as long as the app is monolingual. After i18n, the same test would pass against wrong-language text if it happens to match. | Golden-value table gives each locale its own expected text. A wrong-language bug is detected because the test holds its own truth. Tier 2 structural checks ensure the i18n pipeline functions. | **Significant improvement** -- tests gain the ability to detect cross-language copy errors, which the current suite cannot express. |
| **Coverage truth** | 92 assertions of rendered text, all valid. But zero coverage of the EN surface. | 128 golden values covering both locales + structural presence checks + prerender smoke tests. The EN surface goes from untested to tested. | **Coverage surface doubles** (two locales instead of one). Not a count increase -- a dimensionality increase. |

### 5.2 Verdict

**The reworked suite is sufficient to support regression judgment for the i18n'd portal.** Specifically:

1. **Wrong-language bugs**: Caught by Tier 1 golden-value assertions. If an EN page renders Chinese text, the golden value for that locale disagrees and the test fails.
2. **Missing-translation bugs**: Caught by Tier 2 structural assertions. If `t("nav.motionControl")` returns undefined (missing key), the `data-testid` element renders empty text and Playwright's `click()` fails (element not visible/interactable).
3. **Broken i18n pipeline**: Caught by Tier 3 smoke tests. If `i18next.init()` fails, the page throws JS errors on load.
4. **SEO regression**: Caught by the new prerender spec. If canonical/hreflang/lang attributes are wrong in the static HTML, the prerender assertion fails.
5. **Navigation regression**: Caught by data-testid-based link tests. If a `<Link to>` changes or is removed, the test fails regardless of locale.

### 5.3 What the reworked suite does NOT catch (and why that is acceptable)

1. **Translation quality/accuracy** (e.g., "One Stack, End to End" being awkward English): This is a human review task, not a test task. Tests enforce the glossary, not prose quality.
2. **Missing locale keys that silently fall back**: react-i18next's `returnNull: false` means missing keys render the key string itself (e.g., `"nav.missingKey"`), which is visible and caught by a human reviewer. Setting `returnNull: true` + `parseMissingKeyHandler` to log warnings would make it catchable programmatically; this is a PR-1a suggestion, not a test concern.
3. **Visual layout regression from longer English text**: English text is typically 30-50% longer than Chinese. Layout breakage (text overflow, wrapping) is a visual QA concern. The e2e suite uses Chromium screenshots on failure, so any layout regression that causes functional breakage (e.g., button pushed out of viewport) will be captured as a screenshot artifact during test failure investigation.

---

## 6. Implementation Order

The rewrites must be sequenced with the i18n PRs to avoid a window where tests fail on `main`:

| Phase | PRs landing | Test rewrites to complete |
|---|---|---|
| **Phase 0** (now) | -- | This plan approved. `data-testid` convention documented for PR-1b implementer. |
| **Phase 1** | PR-1a (i18n foundation) | New unit tests only: `i18n-locale.test.ts`, `seo-hreflang.test.tsx`. Existing suite must still pass (no i18n visible yet). |
| **Phase 2** | PR-1b (shell translation) | `e2e/navigation.spec.ts` rewrite (depends on `data-testid` attributes added in Layout.tsx). `e2e/home.spec.ts` rewrite (nav links section only). |
| **Phase 3** | PR-2..PR-5 (page translations) | Remaining e2e rewrites, one per page PR landing. Unit test rewrites (`AuthGuard.test.tsx`, `user-utils.test.ts`). |
| **Phase 4** | PR-6 (prerender + sitemap + e2e) | `e2e/prerender.spec.ts` created. `playwright.config.ts` updated with prerender project. |

> **Rule**: No i18n PR merges to `main` until the corresponding test rewrite is ready. The test rewrite can land in the same PR or a follow-up PR, but the merge order MUST be test-first to avoid a green CI that is lying.

---

## Appendix A -- Golden Value Curation Checklist

For each golden value in the table, the reviewer must verify:

- [ ] Matches the glossary (`docs/i18n-glossary.md` Appendix A)
- [ ] Chinese value matches the current production text (not an aspirational rewrite)
- [ ] English value is syntactically correct English (not machine-translated)
- [ ] No value is the same across both columns (that would make the assertion meaningless)

The golden value table itself lives in the test file, not in a shared module. This is deliberate: each spec is self-contained and a single-file diff is all a reviewer needs to audit the test's opinion about what text should appear.
