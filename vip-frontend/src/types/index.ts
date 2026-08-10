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

export interface MFAChallengeResponse {
  mfa_required: true;
  challenge_token: string;
  expires_in: number;
}

export type LoginAttempt = LoginResponse | MFAChallengeResponse;

export interface MFAStatus {
  enabled: boolean;
  backup_codes_remaining: number;
  verified_at: string | null;
}

export interface MFASetup {
  secret: string;
  qr_code: string;
  backup_codes: string[];
}

export interface AccountSession {
  id: string;
  created_at: string;
  updated_at: string;
  expires_at: string;
  revoked_at: string | null;
  active: boolean;
  ip_address: string | null;
  user_agent: string | null;
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

export type OAuthProviderId =
  "google" | "apple" | "facebook" | "x" | "instagram";

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
    mfa_enabled?: boolean;
    mfa_backup_codes_remaining?: number;
    passkey_count?: number;
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

export interface ThreeDAccess {
  eligible: boolean;
  plan_code: string;
  required_entitlement: string;
  monthly_quota: number;
  monthly_used: number;
  monthly_remaining: number;
  active_jobs: number;
  max_concurrent_jobs: number;
  max_input_megabytes: number;
  max_texture_size: number;
  compression_policy: "compat" | "meshopt";
  signed_url_ttl_seconds: number;
  owner_managed: true;
  service_enabled: boolean;
  jurisdiction_country: string | null;
  jurisdiction_source: string;
  model_provider: "hunyuan3d" | "triposr" | string;
  model_disclosure: {
    provider: string;
    model: string;
    operator: string;
    license: string;
    territory_limited: boolean;
    tencent_affiliation: boolean | null;
    machine_generated: boolean;
    terms_version: string;
  };
  third_party_terms_version: string;
  third_party_terms_required: boolean;
}

export interface ThreeDArtifact {
  id: string;
  filename: string;
  media_type: "model/gltf-binary" | string;
  size_bytes: number;
  sha256: string;
  status: string;
  metadata: {
    pipeline?: string | null;
    seed?: number | null;
    mesh_count?: number | null;
    material_count?: number | null;
    pbr_material_count?: number | null;
    texture_count?: number | null;
    texture_size_limit?: number | null;
    compression_policy?: string | null;
    optimization_ratio?: number | null;
    pre_optimization_bytes?: number | null;
    post_optimization_bytes?: number | null;
    timings?: Record<string, number>;
    provider_delay_ms?: number | null;
    provider_execution_ms?: number | null;
    fallback_used?: boolean;
    fallback_provider?: string | null;
    model_revision?: string | null;
    source_revision?: string | null;
    license?: string | null;
    provider?: string | null;
    jurisdiction_country?: string | null;
    terms_version?: string | null;
  };
  expires_at: string | null;
}

export type ThreeDJobStatus =
  | "queued"
  | "running"
  | "cancel_requested"
  | "needs_clarification"
  | "completed"
  | "failed"
  | "cancelled";

export interface ThreeDGenerationJob {
  id: string;
  project_id: string;
  workspace_id: string;
  organization_id: string;
  requested_by_id: string;
  status: ThreeDJobStatus;
  stage: string;
  progress: number;
  provider: string;
  provider_job_id: string | null;
  attempts: number;
  max_attempts: number;
  estimated_cost_usd: number;
  metering_status: string;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  cancel_requested_at: string | null;
  cancelled_at: string | null;
  completed_at: string | null;
  has_artifact: boolean;
  artifact: ThreeDArtifact | null;
}

export interface ThreeDArtifactLinks {
  job_id: string;
  artifact_id: string;
  filename: string;
  media_type: string;
  size_bytes: number;
  sha256: string;
  view_url: string;
  download_url: string;
  expires_in: number;
  expires_at: string;
}

export interface ProjectWorkforceResult {
  worker_id: string;
  role: string;
  department: string;
  ministry_id: string;
  employment_state: string;
  assignment_state: string;
  success_count: number;
  failure_count: number;
  quality: number;
  operational_health: number;
  trust: number;
  learning: number;
  recommendation: string;
  restrictions: string[];
  warnings: string[];
  certifications: string[];
  training: {
    course_id: string;
    score: number;
    passed: boolean;
  };
}

export interface ProjectExecutionResult {
  success: boolean;
  phase?: number | string;
  mode?: "full" | "planning" | "provider_neutral";
  status: string;
  provider: string;
  model?: string | null;
  artifacts_count?: number;
  requests_count: number;
  retries_count: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  calculated_cost: number;
  budget_cap: number;
  total_duration: number;
  approved: boolean;
  readiness_score: number;
  blocking_findings: string[];
  rework_plan: string[];
  governance?: Record<string, unknown>;
  external_research?: {
    research_question?: string;
    summary?: string;
    verified_facts?: Array<{
      claim: string;
      source_urls: string[];
      confidence: number;
    }>;
    sources?: Array<{ url: string; title: string; domain: string }>;
    search_calls?: number;
  } | null;
  web_search_calls?: number;
  workforce?: ProjectWorkforceResult[];
  engineering_review?: Record<string, unknown>;
  security_review?: Record<string, unknown>;
  integration_review?: Record<string, unknown>;
  release_review?: Record<string, unknown>;
  delivery_package?: {
    path?: string;
    manifest?: string;
    manifest_sha256?: string;
    files_count?: number;
    contains_executable_product?: boolean;
    owner_approval_receipt?: string;
    owner_approval_receipt_sha256?: string;
  };
  owner_approval?: {
    approved: boolean;
    approved_by_id: string;
    approved_at: string;
    receipt: string;
    receipt_sha256: string;
  };
  all_governance_layers_executed?: boolean;
  model_claims_used_as_execution_proof?: boolean;
  comparison?: {
    available?: boolean;
    winner_by_quality?: string | null;
    offline_mock_readiness?: number | null;
    local_model_readiness?: number | null;
    openai_readiness?: number | null;
  };
  fallback_used: boolean;
  production_modified: boolean;
  recovered_from_existing_evidence?: boolean;
}

export interface ProjectExecution {
  id: string;
  project_id: string;
  workspace_id: string;
  organization_id: string;
  requested_by_id: string;
  mode: "full" | "planning" | "provider_neutral";
  provider: "openai" | "provider-neutral";
  model?: string | null;
  status: "queued" | "running" | "completed" | "failed";
  stage: string;
  progress: number;
  budget_cap_usd: number;
  calculated_cost_usd?: number | null;
  requests_count: number;
  retries_count: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  approved?: boolean | null;
  review_status?: string;
  rework_count?: number;
  paused_at?: string | null;
  cancelled_at?: string | null;
  version?: number;
  readiness_score?: number | null;
  result?: ProjectExecutionResult | null;
  error_code?: string | null;
  error_message?: string | null;
  evidence_available: boolean;
  created_at: string;
  updated_at: string;
  started_at?: string | null;
  completed_at?: string | null;
}

export interface CreateProjectPayload {
  name: string;
  description: string | null;
  priority: "low" | "medium" | "high" | "critical";
  workspace_id: string;
  tags: string[];
}

export interface BillingProviderReadiness {
  id: string;
  configured: boolean;
  mode: string;
  capabilities: string[];
  status: "ready" | "unconfigured" | "blocked" | string;
}

export interface BillingCatalogPeriod {
  id: string;
  label: Record<string, string>;
  months: number;
  amount_minor: number | null;
  compare_at_minor: number | null;
  currency: string;
  enabled: boolean;
  provider: string;
  checkout_available: boolean;
}

export interface BillingCatalogPlan {
  code: string;
  name: Record<string, string>;
  description: Record<string, string>;
  enabled: boolean;
  featured: boolean;
  order: number;
  features: Array<Record<string, string>>;
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
  cta_label: Record<string, string>;
  checkout_provider: string;
  periods: BillingCatalogPeriod[];
}

export interface BillingCatalog {
  enabled: boolean;
  default_currency: string;
  default_period: string;
  show_tax_note: boolean;
  heading: Record<string, string>;
  description: Record<string, string>;
  tax_note: Record<string, string>;
  faq: Array<{
    question: Record<string, string>;
    answer: Record<string, string>;
  }>;
  source_version: number;
  plans: BillingCatalogPlan[];
  providers: BillingProviderReadiness[];
}

export interface BillingSubscriptionSummary {
  id: string;
  provider: string;
  source: "web" | "mobile_store" | string;
  provider_label: string;
  management_url: string | null;
  status: string;
  cancel_at_period_end: boolean;
  current_period_start: string | null;
  current_period_end: string | null;
  canceled_at: string | null;
}

export interface BillingInvoiceSummary {
  id: string;
  number: string;
  provider: string;
  status: string;
  currency: string;
  subtotal_minor: number;
  discount_minor: number;
  tax_minor: number;
  total_minor: number;
  amount_paid_minor: number;
  amount_refunded_minor: number;
  line_items: Array<Record<string, unknown>>;
  created_at: string;
  paid_at: string | null;
}

export interface BillingTransactionSummary {
  id: string;
  provider: string;
  type: string;
  status: string;
  amount_minor: number;
  currency: string;
  created_at: string;
  completed_at: string | null;
}

export interface BillingWalletSummary {
  id: string;
  currency: string;
  balance_minor: number;
  status: string;
}

export interface BillingSummary {
  account: {
    id: string;
    status: string;
    licensed_seats: number;
    plan: string | null;
    plan_name: string | null;
    limits: Record<string, number | string | boolean | null>;
    entitlements: string[];
    usage: Record<string, number>;
    current_period_end: string | null;
  };
  subscription: BillingSubscriptionSummary | null;
  invoices: BillingInvoiceSummary[];
  transactions: BillingTransactionSummary[];
  wallet: BillingWalletSummary;
  catalog_version: number;
}

export interface BillingPaymentMethod {
  id: string;
  provider: string;
  type: string;
  brand: string | null;
  last4: string | null;
  expiry_month: number | null;
  expiry_year: number | null;
  is_default: boolean;
}

export interface BillingCheckout {
  id: string;
  provider: string;
  status: string;
  checkout_url: string | null;
  expires_at: string | null;
  completed_at: string | null;
  summary: {
    subtotal_minor?: number;
    discount_minor?: number;
    tax_minor?: number;
    total_minor?: number;
    currency?: string;
    plan_code?: string;
    period_code?: string;
    instructions?: Record<string, string | number | null>;
  };
}

export type NotificationChannelId =
  "in_app" | "email" | "push" | "telegram" | "whatsapp";

export interface NotificationDelivery {
  id: string;
  notification_id: string;
  channel: NotificationChannelId;
  status: string;
  attempt_count: number;
  max_attempts: number;
  next_attempt_at: string | null;
  provider_message_id: string | null;
  error_code: string | null;
  delivered_at: string | null;
  acknowledged_at: string | null;
  dead_lettered_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface PortalNotification {
  id: string;
  organization_id: string;
  user_id: string;
  type: string;
  category: string;
  event_key: string;
  audience: string;
  title: string;
  message: string;
  severity: "info" | "success" | "warning" | "critical";
  source_type: string | null;
  source_id: string | null;
  correlation_id: string | null;
  payload: Record<string, unknown>;
  read: boolean;
  archived: boolean;
  read_at: string | null;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
  deliveries: NotificationDelivery[];
}

export interface CommunicationChannelReadiness {
  id: NotificationChannelId;
  name: string;
  configured: boolean;
  ready: boolean;
  status: "ready" | "unconfigured";
  reason: string;
  owner_only: boolean;
  capabilities: string[];
}

export interface CommunicationEndpoint {
  id: string;
  channel: Exclude<NotificationChannelId, "in_app">;
  label: string;
  status: string;
  verified: boolean;
  verified_at: string | null;
  last_used_at: string | null;
  masked_address: string;
  created_at: string;
  updated_at: string;
}

export interface NotificationPreference {
  id: string;
  category: string;
  enabled: boolean;
  channels: NotificationChannelId[];
  minimum_severity: "info" | "success" | "warning" | "critical";
  quiet_hours_start: string | null;
  quiet_hours_end: string | null;
  timezone: string;
  digest_mode: "immediate" | "hourly" | "daily";
  updated_at: string;
}

export interface SupportTicketMessage {
  id: string;
  support_request_id: string;
  sender_id: string | null;
  visibility: "requester" | "internal";
  message: string;
  attachments: Array<Record<string, unknown>>;
  created_at: string;
}

export interface SupportTicket {
  id: string;
  organization_id: string;
  requester_id: string;
  assigned_to_id: string | null;
  subject: string;
  category: string;
  priority: string;
  status: string;
  message_count: number | null;
  last_message_at: string;
  escalated_at: string | null;
  resolved_at: string | null;
  closed_at: string | null;
  created_at: string;
  updated_at: string;
  messages?: SupportTicketMessage[];
}
export type SecurityProfile = "passive" | "standard" | "advanced" | "elite";

export interface SecurityLabAccess {
  enabled: boolean;
  granted: boolean;
  level: "standard" | "advanced" | "elite" | "autonomous" | "owner" | null;
  profiles: SecurityProfile[];
  deep_validation_requires_clone: boolean;
}

export interface SecurityTool {
  id: string;
  category: string;
  adapter: string;
  builtin: boolean;
  active: boolean;
  intrusive: boolean;
  requires_source: boolean;
  requires_clone: boolean;
  description: string;
  available: boolean;
  runtime?: Record<string, unknown> | null;
}

export interface SecurityTarget {
  id: string;
  project_id: string | null;
  kind: "managed_project" | "external_authorized" | "security_clone" | string;
  origin: string;
  hostname: string;
  authorization_status: string;
  verification_method: string | null;
  active_scan_allowed: boolean;
  status: string;
  metadata: Record<string, unknown>;
  verified_at: string | null;
}

export interface SecurityScan {
  id: string;
  project_id: string | null;
  target_id: string;
  requested_by_id: string;
  profile: SecurityProfile;
  status: string;
  execution_mode: string;
  tool_plan: Array<Record<string, unknown>>;
  summary: {
    finding_count?: number;
    severity?: Record<string, number>;
    engines?: Array<Record<string, unknown>>;
    [key: string]: unknown;
  };
  error_code: string | null;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string | null;
}

export interface SecurityFinding {
  id: string;
  scan_id: string;
  target_id: string;
  source: string;
  category: string;
  title: string;
  severity: string;
  confidence: number;
  state: string;
  fingerprint: string;
  cwe: string | null;
  owasp: string | null;
  location: string | null;
  evidence: Record<string, unknown>;
  remediation: string | null;
  verified_at: string | null;
  resolved_at: string | null;
}

export interface SecurityRemediation {
  id: string;
  project_id: string | null;
  finding_id: string;
  requested_by_id: string | null;
  status: string;
  plan: Record<string, unknown>;
  patch_evidence: Record<string, unknown>;
  regression_result: Record<string, unknown>;
  retest_scan_id: string | null;
  created_at: string | null;
  updated_at: string | null;
}
