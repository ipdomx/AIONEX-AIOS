import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test, type Page } from "@playwright/test";

async function denyVipSession(page: Page) {
  for (const path of ["auth/me", "auth/refresh"]) {
    await page.route(`**/api/v1/${path}`, async (route) => {
      await route.fulfill({ status: 401, contentType: "application/json", body: JSON.stringify({ detail: "Not authenticated" }) });
    });
  }
}

test("VIP login renders the live authentication form", async ({ page }) => {
  await denyVipSession(page);
  await page.goto("/en/login");
  await expect(page.getByRole("heading", { name: "Welcome back" })).toBeVisible();
  await expect(page.getByLabel("Email address")).toBeVisible();
  await expect(page.getByLabel("Password")).toBeVisible();
  await expect(page.getByRole("button", { name: "Sign in", exact: true })).toBeVisible();
});

test("protected Security Lab redirects an unauthenticated user to login", async ({ page }) => {
  await denyVipSession(page);
  await page.goto("/en/security-lab");
  await expect(page).toHaveURL(/\/en\/login$/);
  await expect(page.getByRole("heading", { name: "Welcome back" })).toBeVisible();
});

test("Arabic login keeps the RTL boundary and mobile layout", async ({ page }) => {
  await denyVipSession(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/ar/login");
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  const layout = await page.evaluate(() => ({
    documentOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
    bodyOverflow: document.body.scrollWidth > document.body.clientWidth + 1,
    emailFontSize: Number.parseFloat(getComputedStyle(document.querySelector<HTMLInputElement>("#login-email")!).fontSize),
    passwordFontSize: Number.parseFloat(getComputedStyle(document.querySelector<HTMLInputElement>("#login-password")!).fontSize),
  }));
  expect(layout.documentOverflow).toBe(false);
  expect(layout.bodyOverflow).toBe(false);
  expect(layout.emailFontSize).toBeGreaterThanOrEqual(16);
  expect(layout.passwordFontSize).toBeGreaterThanOrEqual(16);
});

test("VIP public mobile pages do not create root horizontal overflow", async ({ page }) => {
  await denyVipSession(page);
  await page.setViewportSize({ width: 390, height: 844 });
  for (const path of ["/ar/login", "/ar/forgot-password", "/ar/about", "/ar/pricing", "/en/login", "/en/forgot-password", "/en/about", "/en/pricing"]) {
    await page.goto(path);
    const layout = await page.evaluate(() => ({
      documentWidth: document.documentElement.clientWidth,
      documentScrollWidth: document.documentElement.scrollWidth,
      bodyWidth: document.body.clientWidth,
      bodyScrollWidth: document.body.scrollWidth,
    }));
    expect(layout.documentScrollWidth, path).toBeLessThanOrEqual(layout.documentWidth + 1);
    expect(layout.bodyScrollWidth, path).toBeLessThanOrEqual(layout.bodyWidth + 1);
  }
});

async function allowVipSession(page: Page) {
  await page.route("**/api/v1/auth/me", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: "user-campaign-test",
        email: "campaign@example.invalid",
        name: "Campaign User",
        role: "User",
        status: "active",
        permissions: ["academy:read", "academy:write", "academy:assess"],
        organization: { id: "org-campaign-test", name: "Campaign Test", plan: "professional" },
      }),
    });
  });
}

test("campaign navigation stays hidden until an advertising account is ready", async ({ page }) => {
  await allowVipSession(page);
  await page.route("**/api/v1/growth-social/paid-campaigns/readiness", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        ads_manage_allowed: false,
        social_accounts_allowed: false,
        linked_ad_accounts: [],
        campaigns_visible: false,
        reason: "ads-manage-not-entitled",
        live_provider_mutation_allowed: false,
        automatic_execution_allowed: false,
        objectives: { traffic: "live-meta-ready", sales: "analysis-only", leads: "analysis-only", awareness: "analysis-only" },
      }),
    });
  });
  await page.goto("/en/dashboard");
  await expect(page.getByRole("link", { name: "Campaigns" })).toHaveCount(0);
  await page.goto("/en/campaigns");
  await expect(page).toHaveURL(/\/en\/dashboard$/);
});

test("campaign form derives provider and currency from the linked advertising account", async ({ page }) => {
  await allowVipSession(page);
  await page.route("**/api/v1/growth-social/paid-campaigns/readiness", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        ads_manage_allowed: true,
        social_accounts_allowed: true,
        linked_ad_accounts: [{ id: "ad-account-1", provider: "facebook", display_name: "Meta Ads UAE", currency: "EUR", live_objectives: ["traffic"] }],
        campaigns_visible: true,
        reason: "ready",
        live_provider_mutation_allowed: false,
        automatic_execution_allowed: false,
        objectives: { traffic: "live-meta-ready", sales: "analysis-only", leads: "analysis-only", awareness: "analysis-only" },
      }),
    });
  });
  await page.route("**/api/v1/growth-social/paid-campaigns", async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items: [] }) });
      return;
    }
    await route.continue();
  });
  await page.goto("/en/campaigns");
  await expect(page.locator('select:has(option[value="ad-account-1"])')).toHaveValue("ad-account-1");
  await expect(page.locator('option[value="ad-account-1"]')).toContainText("Meta Ads UAE · facebook");
  await expect(page.getByText("Advertising account currency")).toBeVisible();
  await expect(page.getByText("EUR", { exact: true })).toBeVisible();
  await expect(page.locator('option[value="USD"]')).toHaveCount(0);
  await expect(page.locator('option[value="traffic"]')).toContainText("Meta live-path ready");
  await expect(page.locator('option[value="sales"]')).toContainText("Analysis only");
});

test("projects surface shows the truthful Phase 36 expansion contract", async ({ page }) => {
  await allowVipSession(page);
  await page.route("**/api/v1/projects", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
  });
  await page.route("**/api/v1/workspaces", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
  });
  await page.route("**/api/v1/auth/free-tier", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ plan: "pro", free_tier: false }),
    });
  });
  await page.route("**/api/v1/capabilities/phase36", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        program: "Phase 36 — Universal Capability, Creative Media & 1000+ User Scale",
        authoritative: true,
        minimum_concurrent_users: 1000,
        current_batch: "36H",
        total_capabilities: 60,
        production_ready_capabilities: 1,
        completion: 2,
        maturity_order: [
          "specified",
          "source_built",
          "locally_executed",
          "provider_connected",
          "runtime_verified",
          "scaled",
          "production_ready",
        ],
        maturity_counts: {
          specified: 8,
          source_built: 15,
          locally_executed: 13,
          provider_connected: 0,
          runtime_verified: 23,
          scaled: 0,
          production_ready: 1,
        },
        batches: [],
      }),
    });
  });
  await page.route("**/api/v1/growth-social/paid-campaigns/readiness", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        ads_manage_allowed: false,
        social_accounts_allowed: false,
        linked_ad_accounts: [],
        campaigns_visible: false,
        reason: "ads-manage-not-entitled",
        live_provider_mutation_allowed: false,
        automatic_execution_allowed: false,
        objectives: {},
      }),
    });
  });

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/en/projects");
  await expect(page.getByText("Phase 36 expansion status")).toBeVisible();
  await expect(page.getByText("36H", { exact: true })).toBeVisible();
  await expect(page.getByText("1,000", { exact: true })).toBeVisible();
  await expect(page.getByText("1/60", { exact: true })).toBeVisible();
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
  );
  expect(overflow).toBe(false);
});

async function mockPhase36MStudio(page: Page) {
  await allowVipSession(page);
  await page.route("**/api/v1/portal/published", async (route) => {
    const localized = { ar: "", en: "", fr: "", de: "", es: "", tr: "" };
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        configuration: {
          schema_version: 1,
          branding: {
            site_name: "AIONEX AIOS",
            short_name: "AIONEX",
            wordmark_suffix: "AIOS",
            logo_url: "",
            icon_url: "",
            favicon_url: "",
            logo_alt: localized,
            tagline: localized,
          },
          theme: {
            default_mode: "dark",
            page_color: "#03050A",
            page_deep_color: "#02040A",
            surface_color: "#0A1020",
            text_color: "#FFFFFF",
            muted_color: "#94A3B8",
            primary_color: "#38BDF8",
            secondary_color: "#8B5CF6",
            success_color: "#22C55E",
            warning_color: "#F59E0B",
            danger_color: "#EF4444",
            heading_font_family: "system-ui",
            body_font_family: "system-ui",
            arabic_font_family: "system-ui",
            heading_font_url: "",
            body_font_url: "",
            arabic_font_url: "",
            radius_px: 16,
            page_max_width_px: 1280,
            section_spacing_px: 64,
            logo_size_px: 42,
            button_style: "rounded",
            background_grid: false,
            background_glow: false,
            background_image_url: "",
            background_image_position: "center",
            background_image_opacity: 0,
          },
          navigation: [],
          pages: {},
          pricing: {
            enabled: false,
            show_tax_note: false,
            default_currency: "USD",
            default_period: "monthly",
            heading: localized,
            description: localized,
            tax_note: localized,
            plans: [],
            faq: [],
          },
          footer: {
            enabled: false,
            description: localized,
            security_note: localized,
            copyright_text: localized,
            columns: [],
          },
          announcement: {
            enabled: false,
            severity: "info",
            message: localized,
            link_label: localized,
            link_url: "",
            dismissible: true,
          },
          contact: {
            support_email: "",
            sales_email: "",
            phone: "",
            whatsapp_url: "",
            address: localized,
            social_links: {},
          },
          translation_overrides: {},
          custom_metadata: {},
        },
        publication: { version: 0, published_at: new Date().toISOString(), published_by: "phase36m-e2e" },
      }),
    });
  });
  await page.route("**/index.txt**", async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    const locale = pathname.split("/").filter(Boolean)[0] || "en";
    const artifact = resolve(process.cwd(), "../../vip-frontend/out", locale, "index.txt");
    await route.fulfill({
      status: 200,
      contentType: "text/x-component",
      body: readFileSync(artifact, "utf8"),
    });
  });
  await page.route("**/api/v1/security-lab/access", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        enabled: false,
        granted: false,
        level: null,
        profiles: [],
        deep_validation_requires_clone: true,
      }),
    });
  });
  await page.route("**/api/v1/growth-social/paid-campaigns/readiness", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        ads_manage_allowed: false,
        social_accounts_allowed: false,
        linked_ad_accounts: [],
        campaigns_visible: false,
        reason: "not-configured",
        live_provider_mutation_allowed: false,
        automatic_execution_allowed: false,
        objectives: {},
      }),
    });
  });
  await page.route("**/api/v1/studio/hub", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        generated_at: new Date().toISOString(),
        provider_mode: "provider_neutral",
        jobs: { completed: 1 },
        active_assets: 1,
        capabilities: [
          {
            capability_id: "design-image",
            title: "Design, Image & Brand",
            category: "creative",
            launch_surface: "studio",
            departments: ["ui-ux", "image", "branding"],
            phase36_capability_ids: ["image-generation-editing"],
            supported_plans: ["free", "starter", "professional", "enterprise"],
            required_permissions: [],
            runtime_launchable: true,
            activation_reason: null,
            maturities: ["runtime_verified"],
            external_gates: [],
            policy_source: "owner",
            available: true,
            availability_reason: "available",
            organization_plan: "professional",
            policy: {
              enabled: true,
              eligible_plans: ["enterprise"],
              daily_job_limit: 20,
              max_concurrent_jobs: 3,
              max_attempts: 2,
              max_cost_usd: 0,
              provider_mode: "provider_neutral",
              moderation_mode: "strict",
              version: 3,
            },
          },
          {
            capability_id: "music-song",
            title: "Music & Song",
            category: "creative",
            launch_surface: "studio-gated",
            departments: [],
            phase36_capability_ids: ["song-production"],
            supported_plans: ["starter", "professional", "enterprise"],
            required_permissions: [],
            runtime_launchable: false,
            activation_reason: "external_activation_required",
            maturities: ["source_built"],
            external_gates: ["ace-step-open-song-runtime-acceptance"],
            policy_source: "owner",
            available: false,
            availability_reason: "external_activation_required",
            organization_plan: "professional",
            policy: {
              enabled: true,
              eligible_plans: ["enterprise"],
              daily_job_limit: 5,
              max_concurrent_jobs: 1,
              max_attempts: 1,
              max_cost_usd: 0,
              provider_mode: "provider_neutral",
              moderation_mode: "strict",
              version: 1,
            },
          },
          {
            capability_id: "courses",
            title: "Courses & Academy",
            category: "education",
            launch_surface: "academy",
            departments: [],
            phase36_capability_ids: ["course-factory", "learning-assessment-certification"],
            supported_plans: ["starter", "professional", "enterprise"],
            required_permissions: ["academy:read"],
            runtime_launchable: true,
            activation_reason: null,
            maturities: ["runtime_verified", "production_ready"],
            external_gates: [],
            policy_source: "owner",
            available: true,
            availability_reason: "available",
            organization_plan: "professional",
            policy: {
              enabled: true,
              eligible_plans: ["starter", "professional", "enterprise"],
              daily_job_limit: 20,
              max_concurrent_jobs: 2,
              max_attempts: 2,
              max_cost_usd: 0,
              provider_mode: "provider_neutral",
              moderation_mode: "strict",
              version: 2,
            },
          },
          {
            capability_id: "sector-solutions",
            title: "Business & Sector Solutions",
            category: "sectors",
            launch_surface: "studio-sectors",
            departments: [],
            phase36_capability_ids: ["universal-sector-packs"],
            supported_plans: ["free", "starter", "professional", "enterprise"],
            required_permissions: [],
            runtime_launchable: true,
            activation_reason: null,
            maturities: ["runtime_verified"],
            external_gates: [],
            policy_source: "owner",
            available: true,
            availability_reason: "available",
            organization_plan: "professional",
            policy: {
              enabled: true,
              eligible_plans: ["free", "starter", "professional", "enterprise"],
              daily_job_limit: 20,
              max_concurrent_jobs: 2,
              max_attempts: 2,
              max_cost_usd: 0,
              provider_mode: "provider_neutral",
              moderation_mode: "standard",
              version: 1,
            },
          },
        ],
      }),
    });
  });
  await page.route("**/api/v1/studio/departments", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        count: 3,
        provider_mode: "provider_neutral",
        provider_activation_batch: "29J",
        departments: [
          { id: "text", name: "Text Studio", asset_type: "text", outputs: ["manuscript", "export"] },
          { id: "image", name: "Image Studio", asset_type: "image", outputs: ["editable SVG", "prompt pack"] },
          { id: "branding", name: "Branding Studio", asset_type: "branding", outputs: ["brand strategy", "identity tokens", "usage guide"] },
        ],
      }),
    });
  });
  await page.route("**/api/v1/workspaces**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        {
          id: "workspace-e2e",
          name: "Phase 36M Workspace",
          slug: "phase-36m-workspace",
          organization_id: "org-campaign-test",
          description: null,
          status: "active",
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
      ]),
    });
  });
  await page.route("**/api/v1/studio/sector-packs", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        capability: {
          capability_id: "sector-solutions",
          title: "Business & Sector Solutions",
          category: "sectors",
          launch_surface: "studio-sectors",
          departments: [],
          phase36_capability_ids: ["universal-sector-packs"],
          supported_plans: ["free", "starter", "professional", "enterprise"],
          required_permissions: [],
          runtime_launchable: true,
          activation_reason: null,
          maturities: ["runtime_verified"],
          external_gates: [],
          policy_source: "owner",
          available: true,
          availability_reason: "available",
          organization_plan: "professional",
          policy: {
            enabled: true,
            eligible_plans: ["free", "starter", "professional", "enterprise"],
            daily_job_limit: 20,
            max_concurrent_jobs: 2,
            max_attempts: 2,
            max_cost_usd: 0,
            provider_mode: "provider_neutral",
            moderation_mode: "standard",
            version: 1,
          },
        },
        packs: [
          {
            key: "professional-services",
            title: "Professional Services",
            objective: "Run governed professional client work.",
            audience: "Professional service teams",
            roles: ["owner", "professional", "reviewer"],
            entity_count: 4,
            workflow_count: 2,
            workflows: ["Client intake", "Professional review"],
            safety_boundaries: ["Human review remains authoritative"],
            external_gates: [],
            domain_blueprint: { schema_version: 3, sector_key: "professional-services" },
          },
        ],
        custom_composer: {
          capability_id: "custom-domain-composer",
          schema_version: 3,
          launch_surface: "projects",
          description: "Governed Domain Blueprint v3 composer",
        },
      }),
    });
  });
  await page.route("**/api/v1/projects**", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
  });
  await page.route("**/api/v1/studio/jobs**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        {
          id: "studio-job-e2e",
          project_id: null,
          revision_of_asset_id: null,
          department: "branding",
          output_kind: "branding",
          title: "Governed Brand Kit",
          brief: "Create a governed brand kit",
          language: "en",
          style: "modern",
          target: null,
          programming_language: null,
          change_note: null,
          provider_mode: "provider_neutral",
          provider: null,
          model: null,
          status: "completed",
          progress: 100,
          safety_status: "passed",
          safety_findings: [],
          request_metadata: { external_cost_usd: 0, studio_capability_id: "design-image" },
          result_metadata: { external_cost_usd: 0 },
          error_code: null,
          error_message: null,
          attempts: 1,
          max_attempts: 2,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
      ]),
    });
  });
  await page.route("**/api/v1/studio/assets**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        {
          id: "studio-asset-e2e",
          job_id: "studio-job-e2e",
          project_id: null,
          department: "branding",
          asset_type: "branding",
          title: "Governed Brand Kit",
          filename: "governed-brand-kit.zip",
          media_type: "application/zip",
          checksum: "a".repeat(64),
          size_bytes: 2048,
          status: "active",
          current_revision: 2,
          metadata: {},
          attached_project_ids: [],
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
      ]),
    });
  });
}

test("Phase 36M unified Studio is mobile-safe in all six locales and surfaces governed runtime evidence", async ({ page }) => {
  await mockPhase36MStudio(page);
  const consoleErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  await page.setViewportSize({ width: 390, height: 844 });
  for (const locale of ["ar", "en", "fr", "de", "es", "tr"]) {
    await page.goto(`/${locale}/studio`);
    await expect(page.locator("html")).toHaveAttribute("lang", locale);
    if (locale === "ar") await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
    await expect(page.getByText("Governed Brand Kit", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("$0.000000", { exact: true })).toBeVisible();
    await expect(page.getByText("passed", { exact: true })).toBeVisible();
    await expect(page.getByText("r2", { exact: true })).toBeVisible();
    const layout = await page.evaluate(() => ({
      documentOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
      bodyOverflow: document.body.scrollWidth > document.body.clientWidth + 1,
    }));
    expect(layout.documentOverflow, locale).toBe(false);
    expect(layout.bodyOverflow, locale).toBe(false);
  }
  expect(consoleErrors).toEqual([]);
});


async function mockPhase36MAcademy(page: Page) {
  await page.unroute("**/api/v1/auth/me");
  await page.route("**/api/v1/auth/me", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: "user-campaign-test",
        email: "academy@example.invalid",
        name: "Academy User",
        role: "User",
        status: "active",
        permissions: ["academy:read", "academy:write", "academy:assess"],
        organization: { id: "org-campaign-test", name: "Campaign Test", plan: "professional" },
      }),
    });
  });
  const course = {
    id: "course-e2e",
    organization_id: "org-campaign-test",
    code: "P36M-ACADEMY",
    title: "Governed Course",
    description: "Six-locale governed course package acceptance.",
    competencies: ["governance", "review"],
    passing_score: 80,
    status: "active",
    version: 2,
    created_by_id: "user-campaign-test",
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };
  const packageRow = (status: string) => ({
    id: "package-e2e",
    course_id: course.id,
    status,
    version: 2,
    lesson_count: 12,
    request: { locales: ["ar", "en", "fr", "de", "es", "tr"] },
    curriculum: { modules: 3 },
    citations: [],
    review: status === "approved" ? { approved: true, notes: "browser acceptance" } : {},
    archive_sha256: "b".repeat(64),
    manifest_sha256: "c".repeat(64),
    archive_bytes: 4096,
    download_ready: true,
    site_ready: true,
    error_code: null,
    completed_at: new Date().toISOString(),
    reviewed_at: status === "approved" ? new Date().toISOString() : null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  });

  await page.route("**/api/v1/academy/**", async (route) => {
    const url = new URL(route.request().url());
    const method = route.request().method();
    if (url.pathname === "/api/v1/academy/courses" && method === "GET") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([course]) });
      return;
    }
    if (url.pathname === `/api/v1/academy/courses/${course.id}/packages` && method === "GET") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([packageRow("review_pending")]) });
      return;
    }
    if (url.pathname === "/api/v1/academy/packages/package-e2e/review" && method === "POST") {
      const body = route.request().postDataJSON() as { approved?: boolean };
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(packageRow(body.approved ? "approved" : "rejected")),
      });
      return;
    }
    if (url.pathname === "/api/v1/academy/packages/package-e2e/download" && method === "GET") {
      await route.fulfill({
        status: 200,
        contentType: "application/zip",
        headers: { "content-disposition": 'attachment; filename="course-e2e-v2.zip"' },
        body: "PK-phase36m-academy-e2e",
      });
      return;
    }
    await route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ detail: "Unhandled Academy E2E route" }) });
  });
}

test("Phase 36M Studio launches the governed Academy user surface with review evidence", async ({ page }) => {
  await mockPhase36MStudio(page);
  await mockPhase36MAcademy(page);
  const consoleErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/en/studio");
  const coursesButton = page.getByRole("button", { name: "Courses", exact: true });
  await expect(coursesButton).toBeEnabled();
  await coursesButton.click();
  await expect(page).toHaveURL(/\/en\/academy\/?$/);
  // The test harness serves an output:standalone build through `next start`, so use a
  // document navigation after proving the Studio launch target before asserting page content.
  await page.goto("/en/academy");
  await expect(page.getByRole("heading", { name: "Academy & Course Factory", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Governed Course", exact: true })).toBeVisible();
  await expect(page.getByText("Package v2", { exact: true })).toBeVisible();
  await expect(page.getByText(/SHA-256 b{16,}/)).toBeVisible();

  page.once("dialog", async (dialog) => {
    await dialog.accept("browser acceptance");
  });
  await page.getByRole("button", { name: "Approve", exact: true }).click();
  await expect(page.getByText("Course package approved.", { exact: true })).toBeVisible();
  await expect(page.getByText("approved", { exact: true })).toBeVisible();

  const layout = await page.evaluate(() => ({
    documentOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
    bodyOverflow: document.body.scrollWidth > document.body.clientWidth + 1,
  }));
  expect(layout.documentOverflow).toBe(false);
  expect(layout.bodyOverflow).toBe(false);
  expect(consoleErrors).toEqual([]);
});

test("Phase 36M Academy is a permission-gated mobile course-factory surface", async ({ page }) => {
  await mockPhase36MStudio(page);
  await page.unroute("**/api/v1/auth/me");
  await page.route("**/api/v1/auth/me", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: "academy-user-e2e",
        email: "academy@example.invalid",
        name: "Academy User",
        role: "User",
        status: "active",
        permissions: ["academy:read", "academy:write", "academy:assess"],
        organization: { id: "academy-org-e2e", name: "Academy Org", plan: "enterprise" },
      }),
    });
  });
  await page.route("**/api/v1/academy/courses?limit=200", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        {
          id: "academy-course-e2e",
          organization_id: "academy-org-e2e",
          code: "AIONEX-36M",
          title: "Governed Studio Operations",
          description: "Six-locale governed course package acceptance.",
          competencies: ["governance", "evidence"],
          passing_score: 80,
          status: "active",
          version: 1,
          created_by_id: "academy-user-e2e",
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
      ]),
    });
  });
  await page.route("**/api/v1/academy/courses/academy-course-e2e/packages", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        {
          id: "academy-package-e2e",
          course_id: "academy-course-e2e",
          status: "review_pending",
          version: 2,
          lesson_count: 4,
          request: {},
          curriculum: {},
          citations: [],
          review: { status: "pending", approved: false },
          archive_sha256: "b".repeat(64),
          manifest_sha256: "c".repeat(64),
          archive_bytes: 119706,
          download_ready: true,
          site_ready: true,
          error_code: null,
          completed_at: new Date().toISOString(),
          reviewed_at: null,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
      ]),
    });
  });
  const consoleErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/en/academy");
  await expect(page.getByRole("heading", { name: "Academy & Course Factory", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Governed Studio Operations", exact: true })).toBeVisible();
  await expect(page.getByText("Package v2", { exact: true })).toBeVisible();
  await expect(page.getByText(/SHA-256 b{64}/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Download ZIP" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Approve" })).toBeVisible();
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
  );
  expect(overflow).toBe(false);
  expect(consoleErrors).toEqual([]);
});
