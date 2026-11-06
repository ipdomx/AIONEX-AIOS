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

export type SecurityProfile = "passive" | "standard" | "advanced" | "elite";

export type SecurityAccessLevel =
  | "standard"
  | "advanced"
  | "elite"
  | "autonomous"
  | "owner"
  | "subscriber";

export type SecurityVerificationMethod = "http_file" | "dns_txt";

export interface SecurityLabLimits {
  max_verified_targets: number;
  max_scans_per_month: number;
  max_concurrent_scans: number;
}

export interface SecurityLabUsage {
  targets: number;
  verified_targets: number;
  scans_this_month: number;
  active_scans: number;
  period_start: string;
  period_end: string;
}

export interface SecurityLabAccess {
  enabled: boolean;
  granted: boolean;
  level: SecurityAccessLevel | null;
  profiles: SecurityProfile[];
  deep_validation_requires_clone: boolean;
  source?: "owner" | "grant" | "subscription" | null;
  denial_code?: string | null;
  upgrade_required?: boolean;
  plan_code?: string | null;
  entitled_plans?: string[];
  limits?: SecurityLabLimits | null;
  usage?: SecurityLabUsage;
  reports_available?: boolean;
  verification?: {
    methods: SecurityVerificationMethod[];
    http_file_path: string;
    dns_record_prefix: string;
    dns_value_prefix: string;
    reverify_after_days: number;
  };
}

export interface SecurityVerificationInstructions {
  method: string;
  path: string;
  url?: string;
  challenge: string;
  methods?: {
    http_file: {
      method: "http_file";
      available: boolean;
      path: string;
      url: string;
      content: string;
    };
    dns_txt: {
      method: "dns_txt";
      available: boolean;
      record_name: string | null;
      record_type: "TXT";
      record_value: string;
    };
  };
}

export interface SecurityScanReport {
  scan: SecurityScanRecord;
  target: {
    id: string;
    origin: string;
    hostname: string;
    verification_method: string;
    verified_at: string | null;
  } | null;
  severity_counts: Record<string, number>;
  findings_by_severity: Record<string, SecurityFindingRecord[]>;
  generated_at: string;
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
}

export interface SecurityTargetRecord {
  id: string;
  project_id: string | null;
  kind: string;
  origin: string;
  hostname: string;
  authorization_status: string;
  verification_method: string;
  active_scan_allowed: boolean;
  status: string;
  metadata: Record<string, unknown>;
  verified_at: string | null;
}

export interface SecurityScanRecord {
  id: string;
  project_id: string | null;
  target_id: string;
  requested_by_id: string | null;
  profile: SecurityProfile;
  status: string;
  execution_mode: string;
  tool_plan: SecurityTool[];
  summary: {
    finding_count?: number;
    severity?: Record<string, number>;
    deep_validation?: Record<string, unknown> | null;
    [key: string]: unknown;
  };
  error_code: string | null;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string | null;
}

export interface SecurityFindingRecord {
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

export interface SecurityRemediationRecord {
  id: string;
  project_id: string | null;
  finding_id: string;
  requested_by_id: string | null;
  status: string;
  worktree_ref: string | null;
  plan: Record<string, unknown>;
  regression_result: Record<string, unknown>;
  retest_scan_id: string | null;
  verified_fixed_at: string | null;
  created_at: string | null;
  updated_at: string | null;
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

export type Phase36Maturity =
  | "specified"
  | "source_built"
  | "locally_executed"
  | "provider_connected"
  | "runtime_verified"
  | "scaled"
  | "production_ready";

export interface Phase36Capability {
  capability_id: string;
  category: string;
  title: string;
  owner_batch: string;
  maturity: Phase36Maturity;
  evidence: string[];
  external_gates: string[];
}

export interface Phase36Batch {
  batch_id: string;
  sequence: number;
  title: string;
  status: "complete" | "in_progress" | "planned";
  capabilities: Phase36Capability[];
}

export interface Phase36ProgramSnapshot {
  program: string;
  authoritative: boolean;
  minimum_concurrent_users: number;
  current_batch: string | null;
  total_capabilities: number;
  production_ready_capabilities: number;
  completion: number;
  maturity_order: Phase36Maturity[];
  maturity_counts: Record<Phase36Maturity, number>;
  batches: Phase36Batch[];
}

export interface ProjectExecutionResult {
  success: boolean;
  phase?: number | string;
  mode?: "full" | "planning" | "provider_neutral" | "3d_full";
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
    three_d_web?: string;
    three_d_web_sha256?: string;
  };
  owner_approval?: {
    approved: boolean;
    approved_by_id: string;
    approved_at: string;
    receipt: string;
    receipt_sha256: string;
  };
  three_d_web?: {
    mode: "3d_full";
    runtime: string;
    production_build_passed: boolean;
    asset_count: number;
    asset_providers: string[];
    autonomous_asset_generation_used: boolean;
    autonomous_asset_generation_status: string;
    autonomous_asset_generation_degraded: boolean;
    autonomous_asset_generation_message?: string | null;
    procedural_fallback_used: boolean;
    bundle_bytes: number;
    asset_bytes: number;
    browser_qa_passed: boolean;
    performance_passed: boolean;
    release_ready: boolean;
    release_reasons: string[];
    aggregate_sha256: string;
    build_manifest_sha256: string;
    delivery_path: string;
  };
  all_governance_layers_executed?: boolean;
  model_claims_used_as_execution_proof?: boolean;
  comparison?: {
    available?: boolean;
    winner_by_quality?: string | null;
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
  mode: "full" | "planning" | "provider_neutral" | "3d_full";
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


export interface UserTelegramStatus {
  configured: boolean;
  linked: boolean;
  bot_username: string | null;
  telegram_username: string | null;
  linked_at: string | null;
  link_current: boolean;
  challenge_active: boolean;
  challenge_expires_at: string | null;
}

export interface UserTelegramChallenge {
  code: string;
  expires_at: string;
  expires_in_seconds: number;
  bot_username: string | null;
  deep_link: string | null;
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

export interface PaidCampaignBudgetAssessment {
  recommendation: string;
  rationale: string;
  user_total_budget_minor: number;
  user_daily_budget_minor: number;
  observed_cpa_minor: number | null;
  observed_roas: number;
  user_max_cpa_minor: number | null;
  user_min_roas: number | null;
  owner_approval_required: boolean;
  advisory_only: boolean;
  analysis_basis: string;
  real_performance_data_used: boolean;
  guaranteed_results: boolean;
  budget_mutated: boolean;
  automatic_execution_allowed: boolean;
}

export interface PaidCampaign {
  id: string;
  name: string;
  objective: string;
  status: string;
  approval_status: string;
  owner_approval_required: boolean;
  aios_advice_only: boolean;
  user_budget_preserved: boolean;
  currency: string;
  total_budget_minor: number;
  daily_budget_cap_minor: number;
  simulated_spend_minor: number;
  real_spend_allowed: boolean;
  live_provider_call: boolean;
  live_campaign_mutation: boolean;
  automatic_budget_increase_allowed: boolean;
  delivery_stage:
    | "aios_analysis"
    | "awaiting_owner"
    | "owner_approved"
    | "live_plan_ready"
    | "provider_preparation"
    | "paused_on_meta"
    | "manual_review";
  live_plan_prepared: boolean;
  provider_prepared: boolean;
  manual_review_required: boolean;
  spend_executed: boolean;
  automatic_execution_allowed: false;
}

export interface PaidCampaignAdAccount {
  id: string;
  provider: string;
  display_name: string;
  currency: string;
  live_objectives: string[];
}

export interface PaidCampaignReadiness {
  ads_manage_allowed: boolean;
  social_accounts_allowed: boolean;
  linked_ad_accounts: PaidCampaignAdAccount[];
  campaigns_visible: boolean;
  ads_management_visible?: boolean;
  reason: string;
  live_provider_mutation_allowed: false;
  automatic_execution_allowed: false;
  objectives: Record<string, "live-meta-ready" | "analysis-only">;
}

export interface PaidCampaignPreparationInput {
  campaign_name: string;
  objective: string;
  social_account_id: string;
  total_budget_minor: number;
  daily_budget_cap_minor: number;
  max_cpa_minor?: number | null;
  min_roas?: number | null;
  target_countries: string[];
  placements: string[];
  bid_strategy?: string;
  headline?: string;
  body?: string;
  destination_url?: string | null;
  days?: number;
}

export interface PaidCampaignPreparationResult {
  campaign: PaidCampaign;
  ad_set_id: string;
  creative_id: string;
  ad_id: string;
  simulation_id: string;
  decision: string;
  reason_codes: string[];
  metrics: Record<string, unknown>;
  budget_assessment: PaidCampaignBudgetAssessment;
  owner_approval_required: true;
  aios_advice_only: true;
  automatic_execution_allowed: false;
  real_spend_allowed: false;
  live_provider_call: false;
  live_campaign_mutation: false;
}

export type SocialProviderStatus = "configured" | "not_configured" | "coming_soon";

export interface SocialProvider {
  key: string;
  display_name: string;
  status: SocialProviderStatus;
  reason: string | null;
  connectable: boolean;
  account_providers: string[];
  scopes: string[];
  capabilities: Record<string, string[]>;
  supports_pkce: boolean;
}

export interface SocialConnection {
  id: string;
  provider: string;
  external_user_id: string;
  display_name: string;
  avatar_url: string | null;
  requested_scopes: string[];
  granted_scopes: string[];
  token_expires_at: string | null;
  status: "pending_selection" | "active" | "revoked" | string;
  health_state: string;
  health_reasons: string[];
  last_health_at: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface SocialAsset {
  asset_id: string;
  provider: "facebook" | "instagram" | string;
  account_kind: string;
  external_id: string;
  display_name: string;
  handle: string | null;
  avatar_url: string | null;
  linked_external_id: string | null;
  tasks: string[];
  connected: boolean;
  connectable: boolean;
}

export interface SocialAccount {
  id: string;
  connection_id: string | null;
  provider: "facebook" | "instagram" | string;
  connector: string | null;
  account_kind: string;
  external_account_id: string;
  display_name: string;
  handle: string | null;
  avatar_url: string | null;
  scopes: string[];
  linked_external_id: string | null;
  status: string;
  health_state: string;
  health_reasons: string[];
  token_expires_at: string | null;
  last_health_at: string | null;
  credential_stored: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export interface SocialConnectResult {
  items: SocialAccount[];
  skipped: { asset_id: string; reason: string }[];
}

export interface SocialDisconnectResult {
  account: SocialAccount;
  connection_revoked: boolean;
  provider_revoked: boolean;
}

// --- Social publishing (P3 3.3-3.5). Results carry Graph ids, never tokens.

export type SocialPostType = "text" | "link" | "image" | "carousel" | "video" | "reel";

export type SocialPostStatus =
  | "draft"
  | "scheduled"
  | "publishing"
  | "published"
  | "partially_failed"
  | "failed"
  | "canceled";

export type SocialTargetStatus =
  | "pending"
  | "publishing"
  | "retry_wait"
  | "published"
  | "failed"
  | "canceled";

export interface SocialPostAttempt {
  attempt_number: number;
  outcome: string;
  transient: boolean;
  error_code: string | null;
  error_message: string | null;
  remote_post_id: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface SocialPostTarget {
  id: string;
  account_id: string | null;
  provider: "facebook" | "instagram" | string;
  account_name: string;
  overrides: { caption?: string; share_to_feed?: boolean };
  status: SocialTargetStatus;
  attempts: number;
  max_attempts: number;
  next_attempt_at: string | null;
  remote_post_id: string | null;
  permalink: string | null;
  error_code: string | null;
  error_message: string | null;
  published_at: string | null;
  last_attempt_at: string | null;
  attempt_log?: SocialPostAttempt[];
}

export interface SocialPost {
  id: string;
  status: SocialPostStatus;
  post_type: SocialPostType;
  caption: string;
  link_url: string | null;
  media: { ref: string }[];
  scheduled_at: string | null;
  timezone: string;
  retry_policy: { max_attempts?: number; backoff_seconds?: number };
  published_at: string | null;
  canceled_at: string | null;
  created_at: string | null;
  updated_at: string | null;
  targets: SocialPostTarget[];
}

export interface SocialPostInput {
  post_type: SocialPostType;
  caption: string;
  link_url?: string | null;
  media: string[];
  account_ids: string[];
  overrides?: Record<string, { caption?: string; share_to_feed?: boolean }>;
  timezone: string;
  retry_policy?: { max_attempts: number; backoff_seconds: number };
  client_idempotency_key?: string;
}

export interface SocialValidationIssue {
  code: string;
  severity: "error" | "warning";
  field: string;
}

export interface SocialValidationReport {
  valid: boolean;
  targets: {
    target_id: string | null;
    account_id: string | null;
    provider: string;
    issues: SocialValidationIssue[];
  }[];
  media: {
    ref: string;
    kind: string;
    media_type: string;
    size_bytes: number;
    width: number | null;
    height: number | null;
    duration_ms: number | null;
  }[];
}

export interface SocialMediaItem {
  ref: string;
  id: string;
  source: "upload" | "studio";
  kind: "image" | "video" | string;
  filename: string;
  title?: string;
  media_type: string;
  size_bytes: number;
  width: number | null;
  height: number | null;
  duration_ms: number | null;
  created_at: string | null;
}

export interface SocialAiAssistResult {
  caption: string;
  hashtags: string[];
  mode: "draft" | "improve" | "hashtags";
  language: string;
  model: string;
  provider: string;
  aionex_ai: boolean;
}

// --- P4 Meta Ads for users (roadmap 4.1-4.5). Tokens never reach the browser.

export interface AdsAccess {
  allowed: boolean;
  level: "owner" | "grant" | "subscriber" | null;
  source: string | null;
  reason: string;
  plan_code: string | null;
  entitlement: string;
  activation_enabled: boolean;
  daily_cap_minor: number;
  lifetime_cap_minor: number;
  max_ad_accounts: number;
  max_active_campaigns: number;
  owner_token_fallback: boolean;
  live_verified: boolean;
  activation_phrase: string;
}

export interface AdsConnection {
  id: string;
  display_name: string;
  status: string;
  ads_scopes_granted: string[];
  ads_scopes_missing: string[];
  can_read: boolean;
  can_manage: boolean;
  token_expires_at: string | null;
}

export interface AdsAvailableAccount {
  ad_account_id: string;
  name: string;
  currency: string;
  timezone_name: string;
  account_status: number;
  active: boolean;
  business_name: string | null;
  linked: boolean;
}

export interface AdAccountLink {
  id: string;
  ad_account_id: string;
  name: string;
  currency: string;
  timezone_name: string;
  account_status: number;
  business_name: string | null;
  source: "oauth" | "owner_token";
  connection_id: string | null;
  status: string;
  cpa_target_minor: number | null;
  insights_synced_through: string | null;
  last_sync_at: string | null;
  next_sync_at: string | null;
  throttle_until: string | null;
  sync_state: string;
  sync_error: string | null;
  created_at: string | null;
}

export interface AdsKpi {
  value: number | null;
  previous: number | null;
  change_pct: number | null;
}

export interface AdsMetrics {
  spend: number;
  impressions: number;
  reach: number;
  clicks: number;
  link_clicks: number;
  conversions: number;
  conversion_value: number;
  ctr: number | null;
  cpc: number | null;
  cpm: number | null;
  cpa: number | null;
  roas: number | null;
  frequency: number | null;
}

export interface AdsCampaignMetrics extends AdsMetrics {
  campaign_id: string;
  name: string;
}

export interface AdsBreakdownMetrics extends AdsMetrics {
  value: string;
}

export interface AdsTrendPoint {
  day: string;
  spend: number;
  impressions: number;
  clicks: number;
  conversions: number;
  ctr: number | null;
  cpa: number | null;
  roas: number | null;
}

export interface AdsAlert {
  type: "spend_spike" | "cpa_above_target" | "frequency_fatigue" | string;
  severity: "warning" | "info" | string;
  campaign_id?: string;
  name?: string;
  evidence: Record<string, number | string | null>;
}

export interface AdsDashboard {
  link: AdAccountLink;
  currency: string;
  period: { from: string; to: string };
  previous_period: { from: string; to: string };
  kpis: Record<string, AdsKpi>;
  trend: AdsTrendPoint[];
  campaigns: { basis: "roas" | "cpa" | "ctr"; top: AdsCampaignMetrics[]; bottom: AdsCampaignMetrics[]; count: number };
  breakdowns: Record<string, AdsBreakdownMetrics[]>;
  alerts: AdsAlert[];
  has_data: boolean;
  synced_through: string | null;
  simulated: false;
  live_verified: boolean;
}

export interface AdsRecommendation {
  type: "budget_shift" | "creative_fatigue" | "audience" | "bid_or_schedule" | "other";
  title: string;
  action: string;
  rationale: string;
  evidence: Record<string, number>;
  advisory_only: true;
  auto_apply: false;
}

export interface AdsRecommendationRun {
  id: string;
  link_id: string;
  period: { from: string; to: string };
  provider: string;
  model: string;
  aionex_ai: boolean;
  items: AdsRecommendation[];
  rejected: number;
  advisory_only: true;
  auto_apply: false;
  created_at: string | null;
}

export type AdsObjective = "traffic" | "awareness" | "engagement";

export interface AdsCampaign {
  id: string;
  link_id: string;
  name: string;
  objective: AdsObjective | string;
  status: "draft" | "provisioning" | "paused" | "active" | "auto_paused" | "failed" | string;
  currency: string;
  daily_budget_minor: number | null;
  lifetime_budget_minor: number | null;
  start_time: string | null;
  end_time: string | null;
  targeting: Record<string, unknown>;
  creative: Record<string, unknown>;
  provisioned: boolean;
  meta_campaign_id: string | null;
  spend_to_date: number;
  spend_today: number;
  activated_at: string | null;
  paused_at: string | null;
  pause_reason: string | null;
  error_code: string | null;
  created_at: string | null;
  live_verified: boolean;
}

export interface AdsCampaignInput {
  link_id: string;
  name: string;
  objective: AdsObjective;
  daily_budget_minor?: number | null;
  lifetime_budget_minor?: number | null;
  start_time?: string | null;
  end_time?: string | null;
  targeting: {
    countries: string[];
    age_min: number;
    age_max: number;
    genders: number[];
    publisher_platforms: ("facebook" | "instagram")[];
  };
  creative: {
    source: "upload" | "studio" | "post";
    media_ref?: string | null;
    post_target_id?: string | null;
    page_account_id?: string | null;
    instagram_account_id?: string | null;
    message?: string;
    headline?: string;
    link_url?: string | null;
    call_to_action?: string;
  };
  client_idempotency_key: string;
}

export interface AdsUsage {
  currency: string;
  spend_today: number;
  spend_lifetime: number;
  active_daily_budgets_minor: number;
  active_campaigns: number;
  daily_cap_minor: number;
  lifetime_cap_minor: number;
}
