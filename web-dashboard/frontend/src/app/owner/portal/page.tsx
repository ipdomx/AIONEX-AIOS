/* eslint-disable @next/next/no-img-element */
"use client";

import {
  ArchiveRestore,
  Check,
  Copy,
  Eye,
  FileJson,
  Globe2,
  Image as ImageIcon,
  LoaderCircle,
  Palette,
  Plus,
  RefreshCw,
  Rocket,
  Save,
  Settings2,
  Trash2,
  Type,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import {
  deleteOwnerPortalAsset,
  fetchOwnerPortal,
  publishOwnerPortal,
  replaceOwnerPortalDraft,
  resetOwnerPortalDraft,
  rollbackOwnerPortal,
  uploadOwnerPortalAsset,
  type LocalizedText,
  type OwnerPortalSnapshot,
  type PortalConfiguration,
  type PortalLocale,
  type PortalPricingPlan,
} from "@/lib/owner-portal";

type Tab =
  | "branding"
  | "theme"
  | "navigation"
  | "pricing"
  | "pages"
  | "assets"
  | "communications"
  | "advanced";
const localeLabels: Record<PortalLocale, string> = {
  ar: "العربية",
  en: "English",
  fr: "Français",
  de: "Deutsch",
  es: "Español",
  tr: "Türkçe",
};
const tabs: Array<{ id: Tab; label: string; icon: typeof Palette }> = [
  { id: "branding", label: "Branding", icon: Type },
  { id: "theme", label: "Theme & Fonts", icon: Palette },
  { id: "navigation", label: "Navigation", icon: Globe2 },
  { id: "pricing", label: "Plans & Pricing", icon: Settings2 },
  { id: "pages", label: "Pages & SEO", icon: FileJson },
  { id: "assets", label: "Asset Library", icon: ImageIcon },
  { id: "communications", label: "Contact, Footer & Notice", icon: Globe2 },
  { id: "advanced", label: "Advanced & History", icon: ArchiveRestore },
];

const emptyLocalized = (): LocalizedText => ({
  ar: "",
  en: "",
  fr: "",
  de: "",
  es: "",
  tr: "",
});
const clone = <T,>(value: T): T => structuredClone(value);

function Field({
  label,
  children,
  note,
}: {
  label: string;
  children: React.ReactNode;
  note?: string;
}) {
  return (
    <label className="block">
      <span className="mb-2 block text-xs font-medium text-white/55">
        {label}
      </span>
      {children}
      {note && (
        <span className="mt-1.5 block text-[11px] text-white/30">{note}</span>
      )}
    </label>
  );
}
const inputClass =
  "w-full rounded-xl border border-white/10 bg-black/20 px-3.5 py-3 text-sm text-white outline-none focus:border-electric-300/45";
const buttonClass =
  "inline-flex items-center justify-center gap-2 rounded-xl px-4 py-2.5 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-50";

export default function OwnerPortalControlPage() {
  const [snapshot, setSnapshot] = useState<OwnerPortalSnapshot | null>(null);
  const [configuration, setConfiguration] =
    useState<PortalConfiguration | null>(null);
  const [locale, setLocale] = useState<PortalLocale>("ar");
  const [tab, setTab] = useState<Tab>("branding");
  const [message, setMessage] = useState("Loading owner portal control...");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [advancedText, setAdvancedText] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  async function load(signal?: AbortSignal) {
    setLoading(true);
    try {
      const data = await fetchOwnerPortal(signal);
      setSnapshot(data);
      setConfiguration(clone(data.draft.configuration));
      setAdvancedText(JSON.stringify(data.draft.configuration, null, 2));
      setDirty(false);
      setMessage(
        `Draft loaded. Published version ${data.published.publication?.version || data.published.record_version}.`,
      );
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError"))
        setMessage(
          error instanceof Error
            ? error.message
            : "Portal control failed to load.",
        );
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, []);

  function mutate(recipe: (next: PortalConfiguration) => void) {
    if (!configuration) return;
    const next = clone(configuration);
    recipe(next);
    setConfiguration(next);
    setAdvancedText(JSON.stringify(next, null, 2));
    setDirty(true);
  }

  function localized(value: LocalizedText, nextValue: string): LocalizedText {
    return { ...value, [locale]: nextValue };
  }

  async function save() {
    if (!configuration) return;
    setSaving(true);
    setMessage("Validating and saving the draft...");
    try {
      const result = await replaceOwnerPortalDraft(configuration);
      setConfiguration(clone(result.draft.configuration));
      setAdvancedText(JSON.stringify(result.draft.configuration, null, 2));
      setSnapshot((current) =>
        current ? { ...current, draft: result.draft } : current,
      );
      setDirty(false);
      setMessage("Draft saved. Public portal is unchanged until Publish.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Draft save failed.");
    } finally {
      setSaving(false);
    }
  }

  async function publish() {
    if (
      dirty &&
      !window.confirm(
        "The draft has unsaved changes. Publish the last saved draft instead?",
      )
    )
      return;
    if (
      !window.confirm(
        "Publish this portal configuration to all ai.vip-e.net visitors?",
      )
    )
      return;
    setSaving(true);
    setMessage("Publishing portal configuration...");
    try {
      const result = await publishOwnerPortal();
      setSnapshot((current) =>
        current ? { ...current, published: result.published } : current,
      );
      setMessage(
        `Published version ${result.published.publication?.version || result.published.record_version}. Changes become visible without uploading another ZIP.`,
      );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Publish failed.");
    } finally {
      setSaving(false);
    }
  }

  async function resetDraft() {
    if (
      !window.confirm(
        "Reset the draft to the safe AIONEX defaults? Published visitors will not be affected.",
      )
    )
      return;
    setSaving(true);
    try {
      const result = await resetOwnerPortalDraft();
      setConfiguration(clone(result.draft.configuration));
      setAdvancedText(JSON.stringify(result.draft.configuration, null, 2));
      setDirty(false);
      setSnapshot((current) =>
        current ? { ...current, draft: result.draft } : current,
      );
      setMessage("Draft reset to defaults.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Reset failed.");
    } finally {
      setSaving(false);
    }
  }

  const publishedVersion =
    snapshot?.published.publication?.version ||
    snapshot?.published.record_version ||
    0;
  const planCount =
    configuration?.pricing.plans.filter((item) => item.enabled).length || 0;
  const navCount =
    configuration?.navigation.filter((item) => item.enabled).length || 0;

  if (loading && !configuration)
    return (
      <div className="flex min-h-[50vh] items-center justify-center gap-3 text-white/50">
        <LoaderCircle className="h-5 w-5 animate-spin" /> Loading portal
        control...
      </div>
    );
  if (!configuration)
    return <div className="glass-card p-6 text-red-300">{message}</div>;

  return (
    <div className="space-y-6 pb-20">
      <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
        <div>
          <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-electric-500/20 bg-electric-500/10 px-3 py-1 text-xs text-electric-300">
            <Palette className="h-3.5 w-3.5" /> VIP Portal Control
          </div>
          <h1 className="text-3xl font-bold text-white">
            Complete ai.vip-e.net Control Center
          </h1>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-white/45">
            Brand, colors, fonts, logos, icons, navigation, all translated text
            overrides, pages, SEO, plans, subscription periods, pricing,
            visibility, assets, drafts, publishing, and rollback.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <a
            href="https://ai.vip-e.net/ar/"
            target="_blank"
            rel="noreferrer"
            className={`${buttonClass} border border-white/10 bg-white/[0.04] text-white/70`}
          >
            <Eye className="h-4 w-4" /> Open portal
          </a>
          <button
            onClick={() => void load()}
            disabled={saving}
            className={`${buttonClass} border border-white/10 bg-white/[0.04] text-white/70`}
          >
            <RefreshCw className="h-4 w-4" /> Refresh
          </button>
          <button
            onClick={() => void save()}
            disabled={saving || !dirty}
            className={`${buttonClass} bg-blue-500 text-white`}
          >
            <Save className="h-4 w-4" /> Save draft
          </button>
          <button
            onClick={() => void publish()}
            disabled={saving}
            className={`${buttonClass} bg-gradient-to-r from-electric-500 to-violet-500 text-white`}
          >
            <Rocket className="h-4 w-4" /> Publish
          </button>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-4">
        {[
          ["Published version", publishedVersion],
          ["Draft version", snapshot?.draft.record_version || 0],
          ["Visible plans", planCount],
          ["Navigation items", navCount],
        ].map(([label, value]) => (
          <div key={String(label)} className="glass-card p-4">
            <div className="text-xs text-white/35">{label}</div>
            <div className="mt-2 text-2xl font-bold text-white">{value}</div>
          </div>
        ))}
      </div>
      <div
        className={`rounded-xl border px-4 py-3 text-xs ${dirty ? "border-amber-500/20 bg-amber-500/10 text-amber-200" : "border-electric-500/20 bg-electric-500/10 text-electric-200"}`}
      >
        {message}
        {dirty && " — Unsaved changes."}
      </div>

      <div className="flex flex-wrap gap-2 rounded-2xl border border-white/[0.07] bg-white/[0.02] p-2">
        {tabs.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            type="button"
            onClick={() => setTab(id)}
            className={`${buttonClass} ${tab === id ? "bg-white text-ink-950" : "text-white/55 hover:bg-white/[0.05]"}`}
          >
            <Icon className="h-4 w-4" />
            {label}
          </button>
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-white/35">Editing language:</span>
        {snapshot?.supported_locales.map((item) => (
          <button
            key={item}
            onClick={() => setLocale(item)}
            className={`rounded-lg px-3 py-2 text-xs ${locale === item ? "bg-electric-500 text-white" : "border border-white/10 text-white/55"}`}
          >
            {localeLabels[item]}
          </button>
        ))}
      </div>

      {tab === "branding" && (
        <BrandingEditor
          configuration={configuration}
          locale={locale}
          mutate={mutate}
          localized={localized}
          inputClass={inputClass}
        />
      )}
      {tab === "theme" && (
        <ThemeEditor
          configuration={configuration}
          mutate={mutate}
          inputClass={inputClass}
        />
      )}
      {tab === "navigation" && (
        <NavigationEditor
          configuration={configuration}
          locale={locale}
          mutate={mutate}
          localized={localized}
          inputClass={inputClass}
        />
      )}
      {tab === "pricing" && (
        <PricingEditor
          configuration={configuration}
          locale={locale}
          mutate={mutate}
          localized={localized}
          inputClass={inputClass}
        />
      )}
      {tab === "pages" && (
        <PagesEditor
          configuration={configuration}
          locale={locale}
          mutate={mutate}
          localized={localized}
          inputClass={inputClass}
        />
      )}
      {tab === "assets" && (
        <AssetsEditor
          snapshot={snapshot}
          setSnapshot={setSnapshot}
          mutate={mutate}
          fileRef={fileRef}
          setMessage={setMessage}
          inputClass={inputClass}
        />
      )}
      {tab === "communications" && (
        <CommunicationsEditor
          configuration={configuration}
          locale={locale}
          mutate={mutate}
          localized={localized}
          inputClass={inputClass}
          setMessage={setMessage}
        />
      )}
      {tab === "advanced" && (
        <AdvancedEditor
          advancedText={advancedText}
          setAdvancedText={setAdvancedText}
          setConfiguration={setConfiguration}
          setDirty={setDirty}
          snapshot={snapshot}
          resetDraft={resetDraft}
          setMessage={setMessage}
          setSaving={setSaving}
        />
      )}
    </div>
  );
}

function BrandingEditor({
  configuration,
  locale,
  mutate,
  localized,
  inputClass,
}: {
  configuration: PortalConfiguration;
  locale: PortalLocale;
  mutate: (fn: (next: PortalConfiguration) => void) => void;
  localized: (value: LocalizedText, next: string) => LocalizedText;
  inputClass: string;
}) {
  const b = configuration.branding;
  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <div className="glass-card space-y-5 p-6">
        <h2 className="text-lg font-semibold text-white">Identity</h2>
        <Field label="Site name">
          <input
            className={inputClass}
            value={b.site_name}
            onChange={(e) =>
              mutate((n) => {
                n.branding.site_name = e.target.value;
              })
            }
          />
        </Field>
        <Field label="Short wordmark">
          <input
            className={inputClass}
            value={b.short_name}
            onChange={(e) =>
              mutate((n) => {
                n.branding.short_name = e.target.value;
              })
            }
          />
        </Field>
        <Field label="Wordmark suffix">
          <input
            className={inputClass}
            value={b.wordmark_suffix}
            onChange={(e) =>
              mutate((n) => {
                n.branding.wordmark_suffix = e.target.value;
              })
            }
          />
        </Field>
        <Field label={`Tagline — ${localeLabels[locale]}`}>
          <textarea
            className={`${inputClass} min-h-24`}
            value={b.tagline[locale]}
            onChange={(e) =>
              mutate((n) => {
                n.branding.tagline = localized(
                  n.branding.tagline,
                  e.target.value,
                );
              })
            }
          />
        </Field>
        <Field label={`Logo alt text — ${localeLabels[locale]}`}>
          <input
            className={inputClass}
            value={b.logo_alt[locale]}
            onChange={(e) =>
              mutate((n) => {
                n.branding.logo_alt = localized(
                  n.branding.logo_alt,
                  e.target.value,
                );
              })
            }
          />
        </Field>
      </div>
      <div className="glass-card space-y-5 p-6">
        <h2 className="text-lg font-semibold text-white">Logo & icons</h2>
        {(["logo_url", "icon_url", "favicon_url"] as const).map((key) => (
          <Field
            key={key}
            label={key.replaceAll("_", " ")}
            note="Use a static / path or an uploaded /api/v1/portal/assets/... URL."
          >
            <input
              className={inputClass}
              value={b[key]}
              onChange={(e) =>
                mutate((n) => {
                  n.branding[key] = e.target.value;
                })
              }
            />
          </Field>
        ))}
        <div className="rounded-2xl border border-white/10 bg-black/30 p-8 text-center">
          <img
            src={b.logo_url}
            alt="Preview"
            className="mx-auto h-24 w-24 object-contain"
          />
          <p className="mt-4 text-xl font-bold text-white">
            {b.short_name}{" "}
            <span className="text-electric-300">{b.wordmark_suffix}</span>
          </p>
          <p className="mt-2 text-sm text-white/45">{b.tagline[locale]}</p>
        </div>
      </div>
    </div>
  );
}

function ThemeEditor({
  configuration,
  mutate,
  inputClass,
}: {
  configuration: PortalConfiguration;
  mutate: (fn: (next: PortalConfiguration) => void) => void;
  inputClass: string;
}) {
  const theme = configuration.theme;
  const colors = [
    "page_color",
    "page_deep_color",
    "surface_color",
    "text_color",
    "muted_color",
    "primary_color",
    "secondary_color",
    "success_color",
    "warning_color",
    "danger_color",
  ] as const;
  return (
    <div className="grid gap-5 xl:grid-cols-[1.2fr_.8fr]">
      <div className="glass-card p-6">
        <h2 className="text-lg font-semibold text-white">Colors</h2>
        <div className="mt-5 grid gap-4 sm:grid-cols-2">
          {colors.map((key) => (
            <Field key={key} label={key.replaceAll("_", " ")}>
              <div className="flex gap-2">
                <input
                  type="color"
                  className="h-12 w-14 rounded-lg border border-white/10 bg-transparent"
                  value={theme[key].slice(0, 7)}
                  onChange={(e) =>
                    mutate((n) => {
                      n.theme[key] = e.target.value;
                    })
                  }
                />
                <input
                  className={inputClass}
                  value={theme[key]}
                  onChange={(e) =>
                    mutate((n) => {
                      n.theme[key] = e.target.value;
                    })
                  }
                />
              </div>
            </Field>
          ))}
        </div>
      </div>
      <div className="space-y-5">
        <div className="glass-card space-y-4 p-6">
          <h2 className="text-lg font-semibold text-white">Fonts</h2>
          {(
            [
              "heading_font_family",
              "body_font_family",
              "arabic_font_family",
              "heading_font_url",
              "body_font_url",
              "arabic_font_url",
            ] as const
          ).map((key) => (
            <Field key={key} label={key.replaceAll("_", " ")}>
              <input
                className={inputClass}
                value={String(theme[key])}
                onChange={(e) =>
                  mutate((n) => {
                    (n.theme[key] as string) = e.target.value;
                  })
                }
              />
            </Field>
          ))}
        </div>
        <div className="glass-card grid gap-4 p-6 sm:grid-cols-2">
          {(
            [
              "radius_px",
              "page_max_width_px",
              "section_spacing_px",
              "logo_size_px",
            ] as const
          ).map((key) => (
            <Field key={key} label={key.replaceAll("_", " ")}>
              <input
                type="number"
                className={inputClass}
                value={theme[key]}
                onChange={(e) =>
                  mutate((n) => {
                    n.theme[key] = Number(e.target.value);
                  })
                }
              />
            </Field>
          ))}
          <Field label="Button style">
            <select
              className={inputClass}
              value={theme.button_style}
              onChange={(e) =>
                mutate((n) => {
                  n.theme.button_style = e.target
                    .value as typeof theme.button_style;
                })
              }
            >
              <option value="rounded">Rounded</option>
              <option value="pill">Pill</option>
              <option value="square">Square</option>
            </select>
          </Field>
          <Field label="Background image URL">
            <input
              className={inputClass}
              value={theme.background_image_url}
              onChange={(e) =>
                mutate((n) => {
                  n.theme.background_image_url = e.target.value;
                })
              }
            />
          </Field>
          <Field label="Background position">
            <select
              className={inputClass}
              value={theme.background_image_position}
              onChange={(e) =>
                mutate((n) => {
                  n.theme.background_image_position = e.target
                    .value as typeof theme.background_image_position;
                })
              }
            >
              {["center", "top", "bottom", "left", "right"].map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Background image opacity">
            <input
              type="number"
              min="0"
              max="1"
              step="0.05"
              className={inputClass}
              value={theme.background_image_opacity}
              onChange={(e) =>
                mutate((n) => {
                  n.theme.background_image_opacity = Number(e.target.value);
                })
              }
            />
          </Field>
          <Field label="Default mode">
            <select
              className={inputClass}
              value={theme.default_mode}
              onChange={(e) =>
                mutate((n) => {
                  n.theme.default_mode = e.target
                    .value as typeof theme.default_mode;
                })
              }
            >
              <option value="dark">Dark</option>
              <option value="light">Light</option>
              <option value="system">System</option>
            </select>
          </Field>
          {(["background_grid", "background_glow"] as const).map((key) => (
            <label
              key={key}
              className="flex items-center gap-3 text-sm text-white/60"
            >
              <input
                type="checkbox"
                checked={theme[key]}
                onChange={(e) =>
                  mutate((n) => {
                    n.theme[key] = e.target.checked;
                  })
                }
              />
              {key.replaceAll("_", " ")}
            </label>
          ))}
        </div>
      </div>
    </div>
  );
}

function NavigationEditor({
  configuration,
  locale,
  mutate,
  localized,
  inputClass,
}: {
  configuration: PortalConfiguration;
  locale: PortalLocale;
  mutate: (fn: (next: PortalConfiguration) => void) => void;
  localized: (value: LocalizedText, next: string) => LocalizedText;
  inputClass: string;
}) {
  return (
    <div className="space-y-4">
      {configuration.navigation
        .sort((a, b) => a.order - b.order)
        .map((item, index) => (
          <div
            key={item.id}
            className="glass-card grid gap-4 p-5 lg:grid-cols-[1fr_1.3fr_1fr_auto]"
          >
            <Field label="ID">
              <input
                className={inputClass}
                value={item.id}
                onChange={(e) =>
                  mutate((n) => {
                    n.navigation[index].id = e.target.value;
                  })
                }
              />
            </Field>
            <Field label={`Label — ${localeLabels[locale]}`}>
              <input
                className={inputClass}
                value={item.label[locale]}
                onChange={(e) =>
                  mutate((n) => {
                    n.navigation[index].label = localized(
                      n.navigation[index].label,
                      e.target.value,
                    );
                  })
                }
              />
            </Field>
            <Field label="Link">
              <input
                className={inputClass}
                value={item.href}
                onChange={(e) =>
                  mutate((n) => {
                    n.navigation[index].href = e.target.value;
                  })
                }
              />
            </Field>
            <div className="flex items-end gap-2">
              <label className="flex items-center gap-2 pb-3 text-xs text-white/50">
                <input
                  type="checkbox"
                  checked={item.enabled}
                  onChange={(e) =>
                    mutate((n) => {
                      n.navigation[index].enabled = e.target.checked;
                    })
                  }
                />
                Visible
              </label>
              <button
                className="mb-1 rounded-lg p-2 text-red-300 hover:bg-red-500/10"
                onClick={() =>
                  mutate((n) => {
                    n.navigation.splice(index, 1);
                  })
                }
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </div>
            <Field label="Order">
              <input
                type="number"
                className={inputClass}
                value={item.order}
                onChange={(e) =>
                  mutate((n) => {
                    n.navigation[index].order = Number(e.target.value);
                  })
                }
              />
            </Field>
            <Field label="Audience">
              <select
                className={inputClass}
                value={item.audience}
                onChange={(e) =>
                  mutate((n) => {
                    n.navigation[index].audience = e.target
                      .value as typeof item.audience;
                  })
                }
              >
                <option value="all">All</option>
                <option value="guest">Guests</option>
                <option value="authenticated">Authenticated</option>
              </select>
            </Field>
            <label className="flex items-center gap-2 text-xs text-white/50">
              <input
                type="checkbox"
                checked={item.external}
                onChange={(e) =>
                  mutate((n) => {
                    n.navigation[index].external = e.target.checked;
                  })
                }
              />
              Open as external link
            </label>
          </div>
        ))}
      <button
        className={`${buttonClass} border border-electric-500/20 bg-electric-500/10 text-electric-300`}
        onClick={() =>
          mutate((n) => {
            n.navigation.push({
              id: `item-${n.navigation.length + 1}`,
              href: "/",
              label: emptyLocalized(),
              enabled: true,
              order: (n.navigation.length + 1) * 10,
              audience: "all",
              external: false,
            });
          })
        }
      >
        <Plus className="h-4 w-4" />
        Add navigation item
      </button>
    </div>
  );
}

function PricingEditor({
  configuration,
  locale,
  mutate,
  localized,
  inputClass,
}: {
  configuration: PortalConfiguration;
  locale: PortalLocale;
  mutate: (fn: (next: PortalConfiguration) => void) => void;
  localized: (value: LocalizedText, next: string) => LocalizedText;
  inputClass: string;
}) {
  const p = configuration.pricing;
  return (
    <div className="space-y-5">
      <div className="glass-card grid gap-4 p-6 lg:grid-cols-3">
        <Field label={`Page heading — ${localeLabels[locale]}`}>
          <input
            className={inputClass}
            value={p.heading[locale]}
            onChange={(e) =>
              mutate((n) => {
                n.pricing.heading = localized(
                  n.pricing.heading,
                  e.target.value,
                );
              })
            }
          />
        </Field>
        <Field label={`Description — ${localeLabels[locale]}`}>
          <input
            className={inputClass}
            value={p.description[locale]}
            onChange={(e) =>
              mutate((n) => {
                n.pricing.description = localized(
                  n.pricing.description,
                  e.target.value,
                );
              })
            }
          />
        </Field>
        <Field label="Default currency">
          <input
            className={inputClass}
            value={p.default_currency}
            maxLength={3}
            onChange={(e) =>
              mutate((n) => {
                n.pricing.default_currency = e.target.value.toUpperCase();
              })
            }
          />
        </Field>
        <label className="flex items-center gap-2 text-sm text-white/55">
          <input
            type="checkbox"
            checked={p.enabled}
            onChange={(e) =>
              mutate((n) => {
                n.pricing.enabled = e.target.checked;
              })
            }
          />
          Pricing page enabled
        </label>
        <label className="flex items-center gap-2 text-sm text-white/55">
          <input
            type="checkbox"
            checked={p.show_tax_note}
            onChange={(e) =>
              mutate((n) => {
                n.pricing.show_tax_note = e.target.checked;
              })
            }
          />
          Show tax note
        </label>
      </div>
      {p.plans.map((plan, index) => (
        <PlanEditor
          key={plan.id}
          plan={plan}
          index={index}
          locale={locale}
          mutate={mutate}
          localized={localized}
          inputClass={inputClass}
        />
      ))}
      <button
        className={`${buttonClass} border border-electric-500/20 bg-electric-500/10 text-electric-300`}
        onClick={() =>
          mutate((n) => {
            n.pricing.plans.push({
              id: `plan-${n.pricing.plans.length + 1}`,
              enabled: false,
              featured: false,
              order: (n.pricing.plans.length + 1) * 10,
              name: emptyLocalized(),
              description: emptyLocalized(),
              badge: emptyLocalized(),
              periods: [
                {
                  id: "monthly",
                  label: { ...emptyLocalized(), en: "Monthly", ar: "شهري" },
                  months: 1,
                  price: null,
                  compare_at_price: null,
                  currency: n.pricing.default_currency,
                  enabled: true,
                },
              ],
              features: [],
              limits: {},
              entitlements: [],
              cta_label: {
                ...emptyLocalized(),
                en: "Choose plan",
                ar: "اختر الخطة",
              },
              cta_url: "/register",
              checkout_provider: "none",
              checkout_reference: "",
            });
          })
        }
      >
        <Plus className="h-4 w-4" />
        Add plan
      </button>
    </div>
  );
}

function PlanEditor({
  plan,
  index,
  locale,
  mutate,
  localized,
  inputClass,
}: {
  plan: PortalPricingPlan;
  index: number;
  locale: PortalLocale;
  mutate: (fn: (next: PortalConfiguration) => void) => void;
  localized: (value: LocalizedText, next: string) => LocalizedText;
  inputClass: string;
}) {
  return (
    <div
      className={`glass-card p-6 ${plan.featured ? "ring-1 ring-electric-400/30" : ""}`}
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-lg font-semibold text-white">
            {plan.name[locale] || plan.id}
          </h3>
          <p className="text-xs text-white/35">Plan ID: {plan.id}</p>
        </div>
        <div className="flex gap-4 text-xs text-white/50">
          <label>
            <input
              type="checkbox"
              checked={plan.enabled}
              onChange={(e) =>
                mutate((n) => {
                  n.pricing.plans[index].enabled = e.target.checked;
                })
              }
            />{" "}
            Enabled
          </label>
          <label>
            <input
              type="checkbox"
              checked={plan.featured}
              onChange={(e) =>
                mutate((n) => {
                  n.pricing.plans[index].featured = e.target.checked;
                })
              }
            />{" "}
            Featured
          </label>
          <button
            className="text-red-300"
            onClick={() =>
              mutate((n) => {
                n.pricing.plans.splice(index, 1);
              })
            }
          >
            <Trash2 className="h-4 w-4" />
          </button>
        </div>
      </div>
      <div className="mt-5 grid gap-4 lg:grid-cols-4">
        <Field label="Plan ID">
          <input
            className={inputClass}
            value={plan.id}
            onChange={(e) =>
              mutate((n) => {
                n.pricing.plans[index].id = e.target.value;
              })
            }
          />
        </Field>
        <Field label={`Name — ${localeLabels[locale]}`}>
          <input
            className={inputClass}
            value={plan.name[locale]}
            onChange={(e) =>
              mutate((n) => {
                n.pricing.plans[index].name = localized(
                  n.pricing.plans[index].name,
                  e.target.value,
                );
              })
            }
          />
        </Field>
        <Field label={`Badge — ${localeLabels[locale]}`}>
          <input
            className={inputClass}
            value={plan.badge[locale]}
            onChange={(e) =>
              mutate((n) => {
                n.pricing.plans[index].badge = localized(
                  n.pricing.plans[index].badge,
                  e.target.value,
                );
              })
            }
          />
        </Field>
        <Field label="Order">
          <input
            type="number"
            className={inputClass}
            value={plan.order}
            onChange={(e) =>
              mutate((n) => {
                n.pricing.plans[index].order = Number(e.target.value);
              })
            }
          />
        </Field>
        <Field label={`Description — ${localeLabels[locale]}`}>
          <textarea
            className={`${inputClass} min-h-24`}
            value={plan.description[locale]}
            onChange={(e) =>
              mutate((n) => {
                n.pricing.plans[index].description = localized(
                  n.pricing.plans[index].description,
                  e.target.value,
                );
              })
            }
          />
        </Field>
        <Field label={`CTA label — ${localeLabels[locale]}`}>
          <input
            className={inputClass}
            value={plan.cta_label[locale]}
            onChange={(e) =>
              mutate((n) => {
                n.pricing.plans[index].cta_label = localized(
                  n.pricing.plans[index].cta_label,
                  e.target.value,
                );
              })
            }
          />
        </Field>
        <Field label="CTA URL">
          <input
            className={inputClass}
            value={plan.cta_url}
            onChange={(e) =>
              mutate((n) => {
                n.pricing.plans[index].cta_url = e.target.value;
              })
            }
          />
        </Field>
        <Field label="Checkout provider">
          <select
            className={inputClass}
            value={plan.checkout_provider}
            onChange={(e) =>
              mutate((n) => {
                n.pricing.plans[index].checkout_provider = e.target
                  .value as typeof plan.checkout_provider;
              })
            }
          >
            {["none", "stripe", "paddle", "paypal", "manual"].map((v) => (
              <option key={v} value={v}>
                {v}
              </option>
            ))}
          </select>
        </Field>
      </div>
      <h4 className="mt-6 text-sm font-semibold text-white">
        Subscription periods
      </h4>
      <div className="mt-3 grid gap-3 xl:grid-cols-2">
        {plan.periods.map((period, periodIndex) => (
          <div
            key={period.id}
            className="rounded-2xl border border-white/[0.07] bg-black/20 p-4"
          >
            <div className="grid gap-3 sm:grid-cols-4">
              <Field label="Period ID">
                <input
                  className={inputClass}
                  value={period.id}
                  onChange={(e) =>
                    mutate((n) => {
                      n.pricing.plans[index].periods[periodIndex].id =
                        e.target.value;
                    })
                  }
                />
              </Field>
              <Field label={`Label — ${locale}`}>
                <input
                  className={inputClass}
                  value={period.label[locale]}
                  onChange={(e) =>
                    mutate((n) => {
                      n.pricing.plans[index].periods[periodIndex].label =
                        localized(
                          n.pricing.plans[index].periods[periodIndex].label,
                          e.target.value,
                        );
                    })
                  }
                />
              </Field>
              <Field label="Months">
                <input
                  type="number"
                  className={inputClass}
                  value={period.months}
                  onChange={(e) =>
                    mutate((n) => {
                      n.pricing.plans[index].periods[periodIndex].months =
                        Number(e.target.value);
                    })
                  }
                />
              </Field>
              <Field label="Currency">
                <input
                  className={inputClass}
                  value={period.currency}
                  onChange={(e) =>
                    mutate((n) => {
                      n.pricing.plans[index].periods[periodIndex].currency =
                        e.target.value.toUpperCase();
                    })
                  }
                />
              </Field>
              <Field label="Price">
                <input
                  type="number"
                  step="0.01"
                  className={inputClass}
                  value={period.price ?? ""}
                  onChange={(e) =>
                    mutate((n) => {
                      n.pricing.plans[index].periods[periodIndex].price =
                        e.target.value === "" ? null : Number(e.target.value);
                    })
                  }
                />
              </Field>
              <Field label="Compare price">
                <input
                  type="number"
                  step="0.01"
                  className={inputClass}
                  value={period.compare_at_price ?? ""}
                  onChange={(e) =>
                    mutate((n) => {
                      n.pricing.plans[index].periods[
                        periodIndex
                      ].compare_at_price =
                        e.target.value === "" ? null : Number(e.target.value);
                    })
                  }
                />
              </Field>
              <label className="flex items-center gap-2 text-xs text-white/50">
                <input
                  type="checkbox"
                  checked={period.enabled}
                  onChange={(e) =>
                    mutate((n) => {
                      n.pricing.plans[index].periods[periodIndex].enabled =
                        e.target.checked;
                    })
                  }
                />
                Enabled
              </label>
              <button
                className="text-red-300"
                onClick={() =>
                  mutate((n) => {
                    n.pricing.plans[index].periods.splice(periodIndex, 1);
                  })
                }
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </div>
          </div>
        ))}
      </div>
      <button
        className="mt-3 text-xs text-electric-300"
        onClick={() =>
          mutate((n) => {
            n.pricing.plans[index].periods.push({
              id: `period-${n.pricing.plans[index].periods.length + 1}`,
              label: emptyLocalized(),
              months: 1,
              price: null,
              compare_at_price: null,
              currency: n.pricing.default_currency,
              enabled: true,
            });
          })
        }
      >
        + Add subscription period
      </button>
      <h4 className="mt-6 text-sm font-semibold text-white">
        Features — {localeLabels[locale]}
      </h4>
      <div className="mt-3 space-y-2">
        {plan.features.map((feature, featureIndex) => (
          <div key={featureIndex} className="flex gap-2">
            <input
              className={inputClass}
              value={feature[locale]}
              onChange={(e) =>
                mutate((n) => {
                  n.pricing.plans[index].features[featureIndex] = localized(
                    n.pricing.plans[index].features[featureIndex],
                    e.target.value,
                  );
                })
              }
            />
            <button
              className="text-red-300"
              onClick={() =>
                mutate((n) => {
                  n.pricing.plans[index].features.splice(featureIndex, 1);
                })
              }
            >
              <Trash2 className="h-4 w-4" />
            </button>
          </div>
        ))}
      </div>
      <button
        className="mt-3 text-xs text-electric-300"
        onClick={() =>
          mutate((n) => {
            n.pricing.plans[index].features.push(emptyLocalized());
          })
        }
      >
        + Add feature
      </button>
    </div>
  );
}

function PagesEditor({
  configuration,
  locale,
  mutate,
  localized,
  inputClass,
}: {
  configuration: PortalConfiguration;
  locale: PortalLocale;
  mutate: (fn: (next: PortalConfiguration) => void) => void;
  localized: (value: LocalizedText, next: string) => LocalizedText;
  inputClass: string;
}) {
  return (
    <div className="space-y-5">
      {Object.entries(configuration.pages).map(([key, page]) => (
        <div key={key} className="glass-card p-6">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-lg font-semibold text-white">{key}</h3>
              <p className="text-xs text-white/35">/{page.slug}</p>
            </div>
            <label className="text-xs text-white/50">
              <input
                type="checkbox"
                checked={page.enabled}
                onChange={(e) =>
                  mutate((n) => {
                    n.pages[key].enabled = e.target.checked;
                  })
                }
              />{" "}
              Enabled
            </label>
          </div>
          <div className="mt-5 grid gap-4 lg:grid-cols-3">
            <Field label={`Navigation label — ${localeLabels[locale]}`}>
              <input
                className={inputClass}
                value={page.navigation_label[locale]}
                onChange={(e) =>
                  mutate((n) => {
                    n.pages[key].navigation_label = localized(
                      n.pages[key].navigation_label,
                      e.target.value,
                    );
                  })
                }
              />
            </Field>
            <Field label={`SEO title — ${localeLabels[locale]}`}>
              <input
                className={inputClass}
                value={page.seo.title[locale]}
                onChange={(e) =>
                  mutate((n) => {
                    n.pages[key].seo.title = localized(
                      n.pages[key].seo.title,
                      e.target.value,
                    );
                  })
                }
              />
            </Field>
            <Field label={`SEO description — ${localeLabels[locale]}`}>
              <textarea
                className={`${inputClass} min-h-24`}
                value={page.seo.description[locale]}
                onChange={(e) =>
                  mutate((n) => {
                    n.pages[key].seo.description = localized(
                      n.pages[key].seo.description,
                      e.target.value,
                    );
                  })
                }
              />
            </Field>
            <Field label="SEO image URL">
              <input
                className={inputClass}
                value={page.seo.image_url}
                onChange={(e) =>
                  mutate((n) => {
                    n.pages[key].seo.image_url = e.target.value;
                  })
                }
              />
            </Field>
            <label className="flex items-center gap-2 text-xs text-white/50">
              <input
                type="checkbox"
                checked={page.seo.noindex}
                onChange={(e) =>
                  mutate((n) => {
                    n.pages[key].seo.noindex = e.target.checked;
                  })
                }
              />
              No index
            </label>
          </div>
          <Field
            label="Page sections JSON"
            note="Safe structured sections only. Scripts and executable HTML are rejected."
          >
            <textarea
              className={`${inputClass} mt-4 min-h-64 font-mono text-xs`}
              value={JSON.stringify(page.sections, null, 2)}
              onChange={(e) => {
                try {
                  const parsed = JSON.parse(e.target.value);
                  mutate((n) => {
                    n.pages[key].sections = parsed;
                  });
                } catch {}
              }}
            />
          </Field>
        </div>
      ))}
      <div className="glass-card p-6">
        <h3 className="text-lg font-semibold text-white">
          Translation overrides
        </h3>
        <p className="mt-2 text-xs text-white/40">
          Override any client translation using keys such as{" "}
          <code>home.titleLead</code>, <code>nav.login</code>,{" "}
          <code>projects.title</code>, or <code>register.title</code>.
        </p>
        <textarea
          className={`${inputClass} mt-4 min-h-72 font-mono text-xs`}
          value={JSON.stringify(configuration.translation_overrides, null, 2)}
          onChange={(e) => {
            try {
              const parsed = JSON.parse(e.target.value);
              mutate((n) => {
                n.translation_overrides = parsed;
              });
            } catch {}
          }}
        />
      </div>
    </div>
  );
}

function AssetsEditor({
  snapshot,
  setSnapshot,
  mutate,
  fileRef,
  setMessage,
  inputClass,
}: {
  snapshot: OwnerPortalSnapshot | null;
  setSnapshot: React.Dispatch<React.SetStateAction<OwnerPortalSnapshot | null>>;
  mutate: (fn: (next: PortalConfiguration) => void) => void;
  fileRef: React.RefObject<HTMLInputElement>;
  setMessage: (value: string) => void;
  inputClass: string;
}) {
  const [uploading, setUploading] = useState(false);
  const assets = snapshot?.assets || [];
  async function upload(file?: File) {
    if (!file) return;
    setUploading(true);
    try {
      const asset = await uploadOwnerPortalAsset(file);
      setSnapshot((c) =>
        c
          ? {
              ...c,
              assets: [
                asset,
                ...c.assets.filter((x) => x.asset_id !== asset.asset_id),
              ],
            }
          : c,
      );
      setMessage(`Asset uploaded: ${asset.filename}`);
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }
  return (
    <div className="space-y-5">
      <div className="glass-card p-6">
        <h2 className="text-lg font-semibold text-white">
          Upload image, icon, logo, or WOFF2 font
        </h2>
        <p className="mt-2 text-xs text-white/40">
          Accepted: PNG, JPEG, WebP, ICO, sanitized SVG, WOFF2. Files are stored
          outside Git and served through the public API.
        </p>
        <input
          ref={fileRef}
          type="file"
          accept="image/png,image/jpeg,image/webp,image/x-icon,image/svg+xml,font/woff2"
          className="mt-5 block text-xs text-white/50"
          onChange={(e) => void upload(e.target.files?.[0])}
        />
        {uploading && (
          <LoaderCircle className="mt-3 h-5 w-5 animate-spin text-electric-300" />
        )}
      </div>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {assets.map((asset) => (
          <div key={asset.asset_id} className="glass-card p-5">
            {asset.media_type.startsWith("image/") ? (
              <img
                src={asset.public_url}
                alt=""
                className="h-32 w-full rounded-xl bg-black/20 object-contain"
              />
            ) : (
              <div className="flex h-32 items-center justify-center rounded-xl bg-black/20 text-2xl font-bold">
                FONT
              </div>
            )}
            <p className="mt-4 truncate text-sm font-semibold text-white">
              {asset.filename}
            </p>
            <p className="mt-1 text-[11px] text-white/30">
              {(asset.size_bytes / 1024).toFixed(1)} KB · {asset.media_type}
            </p>
            <input
              readOnly
              className={`${inputClass} mt-3 text-[10px]`}
              value={asset.public_url}
            />
            <div className="mt-3 flex flex-wrap gap-2">
              <button
                className="rounded-lg border border-white/10 px-2.5 py-2 text-xs text-white/55"
                onClick={() =>
                  void navigator.clipboard.writeText(asset.public_url)
                }
              >
                <Copy className="mr-1 inline h-3.5 w-3.5" />
                Copy
              </button>
              {asset.media_type.startsWith("image/") && (
                <>
                  <button
                    className="rounded-lg border border-electric-500/20 px-2.5 py-2 text-xs text-electric-300"
                    onClick={() =>
                      mutate((n) => {
                        n.branding.logo_url = asset.public_url;
                      })
                    }
                  >
                    Use logo
                  </button>
                  <button
                    className="rounded-lg border border-electric-500/20 px-2.5 py-2 text-xs text-electric-300"
                    onClick={() =>
                      mutate((n) => {
                        n.branding.icon_url = asset.public_url;
                      })
                    }
                  >
                    Use icon
                  </button>
                </>
              )}
              <button
                className="rounded-lg border border-red-500/20 px-2.5 py-2 text-xs text-red-300"
                onClick={async () => {
                  if (!window.confirm("Delete this unused asset?")) return;
                  try {
                    await deleteOwnerPortalAsset(asset.asset_id);
                    setSnapshot((c) =>
                      c
                        ? {
                            ...c,
                            assets: c.assets.filter(
                              (x) => x.asset_id !== asset.asset_id,
                            ),
                          }
                        : c,
                    );
                  } catch (e) {
                    setMessage(
                      e instanceof Error ? e.message : "Delete failed",
                    );
                  }
                }}
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function CommunicationsEditor({
  configuration,
  locale,
  mutate,
  localized,
  inputClass,
  setMessage,
}: {
  configuration: PortalConfiguration;
  locale: PortalLocale;
  mutate: (fn: (next: PortalConfiguration) => void) => void;
  localized: (value: LocalizedText, next: string) => LocalizedText;
  inputClass: string;
  setMessage: (value: string) => void;
}) {
  const contact = configuration.contact;
  const announcement = configuration.announcement;
  const footer = configuration.footer;
  return (
    <div className="space-y-5">
      <div className="grid gap-5 xl:grid-cols-2">
        <div className="glass-card space-y-4 p-6">
          <h2 className="text-lg font-semibold text-white">Contact details</h2>
          <Field label="Support email">
            <input
              className={inputClass}
              value={contact.support_email}
              onChange={(e) =>
                mutate((n) => {
                  n.contact.support_email = e.target.value;
                })
              }
            />
          </Field>
          <Field label="Sales email">
            <input
              className={inputClass}
              value={contact.sales_email}
              onChange={(e) =>
                mutate((n) => {
                  n.contact.sales_email = e.target.value;
                })
              }
            />
          </Field>
          <Field label="Phone">
            <input
              className={inputClass}
              value={contact.phone}
              onChange={(e) =>
                mutate((n) => {
                  n.contact.phone = e.target.value;
                })
              }
            />
          </Field>
          <Field label="WhatsApp HTTPS URL">
            <input
              className={inputClass}
              value={contact.whatsapp_url}
              onChange={(e) =>
                mutate((n) => {
                  n.contact.whatsapp_url = e.target.value;
                })
              }
            />
          </Field>
          <Field label={`Address — ${localeLabels[locale]}`}>
            <textarea
              className={`${inputClass} min-h-24`}
              value={contact.address[locale]}
              onChange={(e) =>
                mutate((n) => {
                  n.contact.address = localized(
                    n.contact.address,
                    e.target.value,
                  );
                })
              }
            />
          </Field>
          <Field
            label="Social links JSON"
            note='Example: {"facebook":"https://...","instagram":"https://..."}'
          >
            <textarea
              className={`${inputClass} min-h-32 font-mono text-xs`}
              value={JSON.stringify(contact.social_links, null, 2)}
              onChange={(e) => {
                try {
                  const parsed = JSON.parse(e.target.value) as Record<
                    string,
                    string
                  >;
                  mutate((n) => {
                    n.contact.social_links = parsed;
                  });
                } catch {
                  setMessage("Social links JSON is not valid yet.");
                }
              }}
            />
          </Field>
        </div>
        <div className="glass-card space-y-4 p-6">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold text-white">
              Announcement bar
            </h2>
            <label className="text-xs text-white/50">
              <input
                type="checkbox"
                checked={announcement.enabled}
                onChange={(e) =>
                  mutate((n) => {
                    n.announcement.enabled = e.target.checked;
                  })
                }
              />{" "}
              Enabled
            </label>
          </div>
          <Field label="Severity">
            <select
              className={inputClass}
              value={announcement.severity}
              onChange={(e) =>
                mutate((n) => {
                  n.announcement.severity = e.target
                    .value as typeof announcement.severity;
                })
              }
            >
              {["info", "success", "warning", "critical"].map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </Field>
          <Field label={`Message — ${localeLabels[locale]}`}>
            <textarea
              className={`${inputClass} min-h-24`}
              value={announcement.message[locale]}
              onChange={(e) =>
                mutate((n) => {
                  n.announcement.message = localized(
                    n.announcement.message,
                    e.target.value,
                  );
                })
              }
            />
          </Field>
          <Field label={`Link label — ${localeLabels[locale]}`}>
            <input
              className={inputClass}
              value={announcement.link_label[locale]}
              onChange={(e) =>
                mutate((n) => {
                  n.announcement.link_label = localized(
                    n.announcement.link_label,
                    e.target.value,
                  );
                })
              }
            />
          </Field>
          <Field label="Link URL">
            <input
              className={inputClass}
              value={announcement.link_url}
              onChange={(e) =>
                mutate((n) => {
                  n.announcement.link_url = e.target.value;
                })
              }
            />
          </Field>
          <label className="flex items-center gap-2 text-xs text-white/50">
            <input
              type="checkbox"
              checked={announcement.dismissible}
              onChange={(e) =>
                mutate((n) => {
                  n.announcement.dismissible = e.target.checked;
                })
              }
            />{" "}
            Visitors may dismiss it
          </label>
        </div>
      </div>
      <div className="glass-card space-y-4 p-6">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-white">Footer</h2>
          <label className="text-xs text-white/50">
            <input
              type="checkbox"
              checked={footer.enabled}
              onChange={(e) =>
                mutate((n) => {
                  n.footer.enabled = e.target.checked;
                })
              }
            />{" "}
            Enabled
          </label>
        </div>
        <div className="grid gap-4 lg:grid-cols-3">
          <Field label={`Description — ${localeLabels[locale]}`}>
            <textarea
              className={`${inputClass} min-h-24`}
              value={footer.description[locale]}
              onChange={(e) =>
                mutate((n) => {
                  n.footer.description = localized(
                    n.footer.description,
                    e.target.value,
                  );
                })
              }
            />
          </Field>
          <Field label={`Security note — ${localeLabels[locale]}`}>
            <textarea
              className={`${inputClass} min-h-24`}
              value={footer.security_note[locale]}
              onChange={(e) =>
                mutate((n) => {
                  n.footer.security_note = localized(
                    n.footer.security_note,
                    e.target.value,
                  );
                })
              }
            />
          </Field>
          <Field label={`Copyright — ${localeLabels[locale]}`}>
            <textarea
              className={`${inputClass} min-h-24`}
              value={footer.copyright_text[locale]}
              onChange={(e) =>
                mutate((n) => {
                  n.footer.copyright_text = localized(
                    n.footer.copyright_text,
                    e.target.value,
                  );
                })
              }
            />
          </Field>
        </div>
        <Field
          label="Footer columns and links JSON"
          note="Use this advanced field to add, remove, order, translate, or redirect every footer link."
        >
          <textarea
            className={`${inputClass} min-h-72 font-mono text-xs`}
            value={JSON.stringify(footer.columns, null, 2)}
            onChange={(e) => {
              try {
                const parsed = JSON.parse(
                  e.target.value,
                ) as typeof footer.columns;
                mutate((n) => {
                  n.footer.columns = parsed;
                });
              } catch {
                setMessage("Footer columns JSON is not valid yet.");
              }
            }}
          />
        </Field>
      </div>
    </div>
  );
}

function AdvancedEditor({
  advancedText,
  setAdvancedText,
  setConfiguration,
  setDirty,
  snapshot,
  resetDraft,
  setMessage,
  setSaving,
}: {
  advancedText: string;
  setAdvancedText: (v: string) => void;
  setConfiguration: (v: PortalConfiguration) => void;
  setDirty: (v: boolean) => void;
  snapshot: OwnerPortalSnapshot | null;
  resetDraft: () => Promise<void>;
  setMessage: (v: string) => void;
  setSaving: (v: boolean) => void;
}) {
  function apply() {
    try {
      const parsed = JSON.parse(advancedText) as PortalConfiguration;
      setConfiguration(parsed);
      setDirty(true);
      setMessage("Advanced JSON applied locally. Save draft to validate it.");
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Invalid JSON");
    }
  }
  return (
    <div className="grid gap-5 xl:grid-cols-[1.4fr_.6fr]">
      <div className="glass-card p-6">
        <h2 className="text-lg font-semibold text-white">
          Complete configuration JSON
        </h2>
        <p className="mt-2 text-xs text-white/40">
          This is the advanced control surface for every safe configuration
          field. Executable scripts and unsafe URLs are rejected by the backend.
        </p>
        <textarea
          className={`${inputClass} mt-5 min-h-[650px] font-mono text-xs`}
          value={advancedText}
          onChange={(e) => setAdvancedText(e.target.value)}
        />
        <button
          className={`${buttonClass} mt-4 bg-blue-500 text-white`}
          onClick={apply}
        >
          <Check className="h-4 w-4" />
          Apply JSON locally
        </button>
      </div>
      <div className="space-y-5">
        <div className="glass-card p-6">
          <h2 className="text-lg font-semibold text-white">
            Publication history
          </h2>
          <div className="mt-4 space-y-3">
            {snapshot?.history.map((item) => (
              <div
                key={item.version}
                className="rounded-xl border border-white/[0.07] bg-black/20 p-4"
              >
                <p className="font-semibold text-white">
                  Version {item.version}
                </p>
                <p className="mt-1 text-[11px] text-white/35">
                  {item.published_at || "Unknown time"}
                </p>
                <button
                  className="mt-3 text-xs text-amber-300"
                  onClick={async () => {
                    if (
                      !window.confirm(
                        `Publish rollback from version ${item.version}?`,
                      )
                    )
                      return;
                    setSaving(true);
                    try {
                      await rollbackOwnerPortal(item.version);
                      setMessage(
                        `Rollback from version ${item.version} published. Reloading...`,
                      );
                      window.location.reload();
                    } catch (e) {
                      setMessage(
                        e instanceof Error ? e.message : "Rollback failed",
                      );
                    } finally {
                      setSaving(false);
                    }
                  }}
                >
                  <ArchiveRestore className="mr-1 inline h-3.5 w-3.5" />
                  Rollback and publish
                </button>
              </div>
            ))}
          </div>
        </div>
        <button
          className={`${buttonClass} w-full border border-red-500/20 bg-red-500/10 text-red-300`}
          onClick={() => void resetDraft()}
        >
          <Trash2 className="h-4 w-4" />
          Reset draft to defaults
        </button>
      </div>
    </div>
  );
}
