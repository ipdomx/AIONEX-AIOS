export interface OrganizationSummary {
  id: string;
  name: string;
  plan: string;
}

export interface User {
  id: string;
  email: string;
  name: string;
  role: string;
  status: string;
  permissions: string[];
  organization: OrganizationSummary;
  avatar?: string | null;
}

export interface LoginResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
  user: User;
}

export interface FreeTierPublicPolicy {
  enabled: boolean;
  plan: "free";
  limits: {
    projects: number;
    user_messages_per_month: number;
    assistant_responses_per_month: number;
    storage_bytes: number;
    max_message_characters: number;
  };
  consent_version: string;
  identity: {
    minimum_age: number;
    phone_verification_required: boolean;
    device_signals_required: boolean;
    one_account_per_network: boolean;
    one_account_per_device: boolean;
  };
  required_registration_data: string[];
}

export interface FirebasePhoneConfiguration {
  provider: "firebase";
  enabled: boolean;
  admin_verification_ready: boolean;
  web_config: {
    apiKey: string;
    authDomain: string;
    projectId: string;
    storageBucket?: string;
    messagingSenderId?: string;
    appId: string;
    measurementId?: string;
  } | null;
}

export interface FirebasePhoneReadiness {
  provider: "firebase";
  ready: boolean;
  diagnostics_available: boolean;
  project_id: string;
  phone_number: string;
  country_code: string;
  provider_enabled: boolean | null;
  sms_region_allowed: boolean | null;
  origin_authorized: boolean | null;
  detail: string;
}

export type OAuthProviderId = "google" | "apple" | "facebook" | "x" | "instagram";

export interface OAuthProvider {
  id: OAuthProviderId;
  label: string;
  firebase_provider: string;
  enabled: boolean;
}

export interface FirebaseSocialConfiguration {
  provider: "firebase";
  enabled: boolean;
  web_config: FirebasePhoneConfiguration["web_config"];
  providers: OAuthProvider[];
}

export interface SocialRegistrationPreparation {
  registration_token: string;
  provider: OAuthProviderId;
  email: string;
  name: string | null;
  expires_in: number;
}

export interface PasskeyConfiguration {
  enabled: boolean;
  rp_id: string;
  rp_name: string;
  timeout_ms: number;
}

export interface PasskeyCeremonyOptions {
  ceremony_id: string;
  public_key: Record<string, unknown>;
}

export interface PasskeyCredentialSummary {
  id: string;
  nickname: string;
  transports: string[];
  device_type: string | null;
  backed_up: boolean;
  created_at: string;
  last_used_at: string | null;
}

export interface RegistrationTelemetry {
  timezone?: string;
  language?: string;
  platform?: string;
  user_agent?: string;
  screen?: string;
  screen_width?: number;
  screen_height?: number;
  color_depth?: number;
  device_memory_gb?: number;
  hardware_concurrency?: number;
  max_touch_points?: number;
  cookie_enabled?: boolean;
  do_not_track?: boolean;
  connection_type?: string;
  effective_type?: string;
  downlink_mbps?: number;
  rtt_ms?: number;
  save_data?: boolean;
  referrer?: string;
  vendor?: string;
  webdriver?: boolean;
}

export interface FreeRegistrationPayload {
  username: string;
  name: string;
  email: string;
  password: string;
  birth_date: string;
  country_code: string;
  phone_number: string;
  firebase_id_token?: string;
  social_registration_token?: string;
  consent_accepted: boolean;
  consent_version: string;
  telemetry: RegistrationTelemetry;
}

export interface FreeTierStatus {
  plan: string;
  free_tier: boolean;
  enabled?: boolean;
  limits?: Record<string, number>;
  usage?: Record<string, number>;
  remaining?: Record<string, number>;
  period_started_at?: string;
  period_ends_at?: string;
}

export interface AccountSettings {
  profile: {
    id: string;
    name: string;
    email: string;
    role: string;
    organization: string;
    avatar: string | null;
  };
  preferences: {
    language?: string;
    timezone?: string;
    theme?: "dark" | "light" | "system";
    email_notifications?: boolean;
    push_notifications?: boolean;
    [key: string]: unknown;
  };
  security: {
    mfa_policy_enabled: boolean;
    active_sessions: number;
    password_min_length: number;
  };
  free_tier: FreeTierStatus | null;
}

export interface Workspace {
  id: string;
  name: string;
  slug: string;
  organization_id: string;
  description?: string | null;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface Project {
  id: string;
  name: string;
  slug: string;
  description?: string | null;
  status: string;
  priority: string;
  progress: number;
  workspace_id: string;
  workspace: string;
  owner_id: string;
  owner: string;
  team_count: number;
  task_count: number;
  tags: string[];
  created_at: string;
  updated_at: string;
}

export interface CreateProjectPayload {
  name: string;
  description: string | null;
  priority: "low" | "medium" | "high" | "critical";
  workspace_id: string;
  tags: string[];
}
