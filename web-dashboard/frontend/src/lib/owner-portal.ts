import { apiClient } from "@/lib/api-client";

export type PortalLocale = "ar" | "en" | "fr" | "de" | "es" | "tr";
export type LocalizedText = Record<PortalLocale, string>;
export type PortalAsset = {
  asset_id: string;
  filename: string;
  extension: string;
  media_type: string;
  size_bytes: number;
  sha256: string;
  public_url: string;
  uploaded_at: string;
  uploaded_by: string;
};
export type PortalConfiguration = {
  schema_version: 1;
  branding: {
    site_name: string;
    short_name: string;
    wordmark_suffix: string;
    logo_url: string;
    icon_url: string;
    favicon_url: string;
    logo_alt: LocalizedText;
    tagline: LocalizedText;
  };
  theme: {
    default_mode: "dark" | "light" | "system";
    page_color: string;
    page_deep_color: string;
    surface_color: string;
    text_color: string;
    muted_color: string;
    primary_color: string;
    secondary_color: string;
    success_color: string;
    warning_color: string;
    danger_color: string;
    heading_font_family: string;
    body_font_family: string;
    arabic_font_family: string;
    heading_font_url: string;
    body_font_url: string;
    arabic_font_url: string;
    radius_px: number;
    page_max_width_px: number;
    section_spacing_px: number;
    logo_size_px: number;
    button_style: "rounded" | "pill" | "square";
    background_grid: boolean;
    background_glow: boolean;
    background_image_url: string;
    background_image_position: "center" | "top" | "bottom" | "left" | "right";
    background_image_opacity: number;
  };
  navigation: Array<{
    id: string;
    href: string;
    label: LocalizedText;
    enabled: boolean;
    order: number;
    audience: "all" | "guest" | "authenticated";
    external: boolean;
  }>;
  pages: Record<
    string,
    {
      slug: string;
      enabled: boolean;
      navigation_label: LocalizedText;
      sections: Array<{
        id: string;
        type: string;
        enabled: boolean;
        order: number;
        content: Record<string, unknown>;
      }>;
      seo: {
        title: LocalizedText;
        description: LocalizedText;
        keywords: LocalizedText;
        image_url: string;
        noindex: boolean;
      };
    }
  >;
  pricing: {
    enabled: boolean;
    show_tax_note: boolean;
    default_currency: string;
    default_period: string;
    heading: LocalizedText;
    description: LocalizedText;
    tax_note: LocalizedText;
    plans: Array<{
      id: string;
      enabled: boolean;
      featured: boolean;
      order: number;
      name: LocalizedText;
      description: LocalizedText;
      badge: LocalizedText;
      periods: Array<{
        id: string;
        label: LocalizedText;
        months: number;
        price: number | null;
        compare_at_price: number | null;
        currency: string;
        enabled: boolean;
        checkout_provider?: "none" | "stripe" | "paddle" | "paypal" | "manual";
        checkout_reference: string;
      }>;
      features: LocalizedText[];
      limits: Record<string, number | string | boolean | null>;
      entitlements: string[];
      metering: Record<
        string,
        {
          included?: number;
          unit_size?: number;
          unit_price_minor?: number;
          currency?: string;
        }
      >;
      cta_label: LocalizedText;
      cta_url: string;
      checkout_provider: "none" | "stripe" | "paddle" | "paypal" | "manual";
      checkout_reference: string;
    }>;
    faq: Array<{ question: LocalizedText; answer: LocalizedText }>;
  };
  footer: {
    enabled: boolean;
    description: LocalizedText;
    security_note: LocalizedText;
    copyright_text: LocalizedText;
    columns: Array<{
      id: string;
      title: LocalizedText;
      links: Array<{
        id: string;
        href: string;
        label: LocalizedText;
        enabled: boolean;
        order: number;
        audience: "all" | "guest" | "authenticated";
        external: boolean;
      }>;
    }>;
  };
  announcement: {
    enabled: boolean;
    severity: "info" | "success" | "warning" | "critical";
    message: LocalizedText;
    link_label: LocalizedText;
    link_url: string;
    dismissible: boolean;
  };
  contact: {
    support_email: string;
    sales_email: string;
    phone: string;
    whatsapp_url: string;
    address: LocalizedText;
    social_links: Record<string, string>;
  };
  translation_overrides: Record<string, LocalizedText>;
  custom_metadata: Record<string, unknown>;
};

export type PortalPricingPlan = PortalConfiguration["pricing"]["plans"][number];

export type PortalRecordSnapshot = {
  resource_id: string;
  status: string;
  enabled: boolean;
  record_version: number;
  updated_at: string | null;
  configuration: PortalConfiguration;
  publication?: {
    version: number;
    published_at: string;
    published_by: string;
  };
};

export type PortalHistory = {
  version: number;
  resource_id: string;
  published_at: string;
  published_by: string;
  configuration: PortalConfiguration;
};

export type OwnerPortalSnapshot = {
  draft: PortalRecordSnapshot;
  published: PortalRecordSnapshot;
  history: PortalHistory[];
  assets: PortalAsset[];
  supported_locales: PortalLocale[];
  limits: {
    configuration_bytes: number;
    asset_bytes: number;
    history_entries: number;
  };
};

export const fetchOwnerPortal = (signal?: AbortSignal) =>
  apiClient.get<OwnerPortalSnapshot>("/owner/portal", { signal });

export const replaceOwnerPortalDraft = (configuration: PortalConfiguration) =>
  apiClient.put<{ draft: PortalRecordSnapshot }>("/owner/portal/draft", {
    configuration,
  });

export const publishOwnerPortal = () =>
  apiClient.post<{ published: PortalRecordSnapshot }>("/owner/portal/publish");

export const rollbackOwnerPortal = (version: number) =>
  apiClient.post<{ published: PortalRecordSnapshot }>(
    `/owner/portal/rollback/${version}`,
  );

export const resetOwnerPortalDraft = () =>
  apiClient.post<{ draft: PortalRecordSnapshot }>("/owner/portal/reset-draft");

export const uploadOwnerPortalAsset = (file: File) => {
  const data = new FormData();
  data.append("asset", file);
  return apiClient.post<PortalAsset>("/owner/portal/assets", data);
};

export const deleteOwnerPortalAsset = (assetId: string) =>
  apiClient.delete<void>(`/owner/portal/assets/${assetId}`);
