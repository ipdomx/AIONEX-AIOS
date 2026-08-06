export type PortalLocale = "ar" | "en" | "fr" | "de" | "es" | "tr";
export type LocalizedPortalText = Record<PortalLocale, string>;

export type PortalBranding = {
  site_name: string;
  short_name: string;
  wordmark_suffix: string;
  logo_url: string;
  icon_url: string;
  favicon_url: string;
  logo_alt: LocalizedPortalText;
  tagline: LocalizedPortalText;
};

export type PortalTheme = {
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

export type PortalNavigationItem = {
  id: string;
  href: string;
  label: LocalizedPortalText;
  enabled: boolean;
  order: number;
  audience: "all" | "guest" | "authenticated";
  external: boolean;
};

export type PortalSection = {
  id: string;
  type:
    | "hero"
    | "features"
    | "steps"
    | "cta"
    | "rich-text"
    | "image-text"
    | "stats"
    | "faq"
    | "logo-cloud"
    | "contact"
    | "pricing";
  enabled: boolean;
  order: number;
  content: Record<string, unknown>;
};

export type PortalPage = {
  slug: string;
  enabled: boolean;
  navigation_label: LocalizedPortalText;
  sections: PortalSection[];
  seo: {
    title: LocalizedPortalText;
    description: LocalizedPortalText;
    keywords: LocalizedPortalText;
    image_url: string;
    noindex: boolean;
  };
};

export type PortalBillingPeriod = {
  id: string;
  label: LocalizedPortalText;
  months: number;
  price: number | null;
  compare_at_price: number | null;
  currency: string;
  enabled: boolean;
  checkout_provider?: "none" | "stripe" | "paddle" | "paypal" | "manual";
  checkout_reference: string;
};

export type PortalPricingPlan = {
  id: string;
  enabled: boolean;
  featured: boolean;
  order: number;
  name: LocalizedPortalText;
  description: LocalizedPortalText;
  badge: LocalizedPortalText;
  periods: PortalBillingPeriod[];
  features: LocalizedPortalText[];
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
  cta_label: LocalizedPortalText;
  cta_url: string;
  checkout_provider: "none" | "stripe" | "paddle" | "paypal" | "manual";
  checkout_reference: string;
};

export type PortalConfiguration = {
  schema_version: 1;
  branding: PortalBranding;
  theme: PortalTheme;
  navigation: PortalNavigationItem[];
  pages: Record<string, PortalPage>;
  pricing: {
    enabled: boolean;
    show_tax_note: boolean;
    default_currency: string;
    default_period: string;
    heading: LocalizedPortalText;
    description: LocalizedPortalText;
    tax_note: LocalizedPortalText;
    plans: PortalPricingPlan[];
    faq: Array<{
      question: LocalizedPortalText;
      answer: LocalizedPortalText;
    }>;
  };
  footer: {
    enabled: boolean;
    description: LocalizedPortalText;
    security_note: LocalizedPortalText;
    copyright_text: LocalizedPortalText;
    columns: Array<{
      id: string;
      title: LocalizedPortalText;
      links: PortalNavigationItem[];
    }>;
  };
  announcement: {
    enabled: boolean;
    severity: "info" | "success" | "warning" | "critical";
    message: LocalizedPortalText;
    link_label: LocalizedPortalText;
    link_url: string;
    dismissible: boolean;
  };
  contact: {
    support_email: string;
    sales_email: string;
    phone: string;
    whatsapp_url: string;
    address: LocalizedPortalText;
    social_links: Record<string, string>;
  };
  translation_overrides: Record<string, LocalizedPortalText>;
  custom_metadata: Record<string, unknown>;
};

export type PublishedPortalConfiguration = {
  configuration: PortalConfiguration;
  publication: {
    version: number;
    published_at: string;
    published_by: string;
  };
};
