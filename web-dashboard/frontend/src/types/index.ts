export interface User {
  id: string;
  email: string;
  name: string;
  avatar?: string;
  role: Role;
  status: "online" | "offline" | "busy" | "away";
  organizationId: string;
  workspaceId: string;
  permissions: Permission[];
  lastActive: string;
  createdAt: string;
  updatedAt: string;
}

export interface Role {
  id: string;
  name: string;
  slug: string;
  description: string;
  level: number;
  permissions: Permission[];
  isCustom: boolean;
  createdAt: string;
}

export interface Permission {
  id: string;
  name: string;
  slug: string;
  resource: string;
  action: "create" | "read" | "update" | "delete" | "execute" | "manage";
  description: string;
}

export interface Organization {
  id: string;
  name: string;
  slug: string;
  logo?: string;
  plan: "free" | "starter" | "pro" | "enterprise" | "custom";
  status: "active" | "suspended" | "pending";
  settings: OrganizationSettings;
  memberCount: number;
  createdAt: string;
}

export interface OrganizationSettings {
  timezone: string;
  language: string;
  theme: "dark" | "light" | "system";
  notifications: NotificationSettings;
  security: SecuritySettings;
}

export interface NotificationSettings {
  email: boolean;
  push: boolean;
  sms: boolean;
  webhook: boolean;
  digest: "realtime" | "hourly" | "daily" | "weekly";
}

export interface SecuritySettings {
  mfaRequired: boolean;
  ssoEnabled: boolean;
  ipWhitelist: string[];
  sessionTimeout: number;
  passwordPolicy: PasswordPolicy;
}

export interface PasswordPolicy {
  minLength: number;
  requireUppercase: boolean;
  requireLowercase: boolean;
  requireNumbers: boolean;
  requireSymbols: boolean;
  expiryDays: number;
}

export interface Workspace {
  id: string;
  name: string;
  slug: string;
  description?: string;
  organizationId: string;
  color: string;
  icon?: string;
  memberCount: number;
  projectCount: number;
  createdAt: string;
}

export interface Project {
  id: string;
  name: string;
  slug: string;
  description?: string;
  status: "planning" | "active" | "paused" | "completed" | "archived";
  priority: "low" | "medium" | "high" | "critical";
  progress: number;
  workspaceId: string;
  organizationId: string;
  ownerId: string;
  teamIds: string[];
  startDate?: string;
  endDate?: string;
  tags: string[];
  createdAt: string;
  updatedAt: string;
}

export interface AIAgent {
  id: string;
  name: string;
  slug: string;
  description?: string;
  avatar?: string;
  status: "idle" | "running" | "learning" | "error" | "paused";
  role: string;
  department: string;
  provider: string;
  model: string;
  tasksCompleted: number;
  tasksFailed: number;
  knowledgeCount: number;
  memoryUsage: number;
  performance: number;
  latency: number;
  cost: number;
  tokensUsed: number;
  createdAt: string;
  updatedAt: string;
}

export interface AIProvider {
  id: string;
  name: string;
  slug: string;
  type: "openai" | "anthropic" | "gemini" | "openrouter" | "ollama" | "mistral" | "cohere" | "xai" | "deepseek" | "groq" | "together" | "fireworks" | "huggingface" | "azure_openai" | "aws_bedrock" | "tripo3d" | "meshy";
  status: "connected" | "disconnected" | "error" | "rate_limited";
  apiKey?: string;
  baseUrl?: string;
  models: AIModel[];
  latency: number;
  costPer1kTokens: number;
  usageToday: number;
  usageLimit: number;
  lastUsed: string;
  createdAt: string;
}

export interface AIModel {
  id: string;
  name: string;
  providerId: string;
  contextWindow: number;
  maxTokens: number;
  supportsVision: boolean;
  supportsStreaming: boolean;
  supportsFunctionCalling: boolean;
  costPer1kInput: number;
  costPer1kOutput: number;
  status: "available" | "deprecated" | "beta";
}

export interface Workflow {
  id: string;
  name: string;
  slug: string;
  description?: string;
  status: "draft" | "active" | "paused" | "archived";
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  executionCount: number;
  successRate: number;
  avgExecutionTime: number;
  lastExecuted?: string;
  schedule?: string;
  createdBy: string;
  createdAt: string;
  updatedAt: string;
}

export interface WorkflowNode {
  id: string;
  type: string;
  position: { x: number; y: number };
  data: Record<string, unknown>;
}

export interface WorkflowEdge {
  id: string;
  source: string;
  target: string;
  type?: string;
  label?: string;
}

export interface Server {
  id: string;
  name: string;
  hostname: string;
  ip: string;
  status: "online" | "offline" | "maintenance" | "warning";
  os: string;
  cpu: ServerMetric;
  memory: ServerMetric;
  disk: ServerMetric;
  network: NetworkMetric;
  uptime: number;
  location: string;
  provider: string;
  cost: number;
  tags: string[];
  createdAt: string;
}

export interface ServerMetric {
  used: number;
  total: number;
  percentage: number;
  history: MetricPoint[];
}

export interface NetworkMetric {
  rx: number;
  tx: number;
  rxHistory: MetricPoint[];
  txHistory: MetricPoint[];
}

export interface MetricPoint {
  timestamp: string;
  value: number;
}

export interface Container {
  id: string;
  name: string;
  image: string;
  status: "running" | "stopped" | "restarting" | "error";
  serverId: string;
  cpu: number;
  memory: number;
  ports: PortMapping[];
  volumes: VolumeMapping[];
  env: Record<string, string>;
  restartCount: number;
  createdAt: string;
}

export interface PortMapping {
  host: number;
  container: number;
  protocol: "tcp" | "udp";
}

export interface VolumeMapping {
  host: string;
  container: string;
  mode: "rw" | "ro";
}

export interface KubernetesCluster {
  id: string;
  name: string;
  provider: string;
  version: string;
  status: "healthy" | "degraded" | "critical" | "offline";
  nodes: K8sNode[];
  pods: K8sPod[];
  services: K8sService[];
  deployments: K8sDeployment[];
  createdAt: string;
}

export interface K8sNode {
  id: string;
  name: string;
  role: "master" | "worker";
  status: "ready" | "notready" | "schedulingdisabled";
  cpu: number;
  memory: number;
  disk: number;
  pods: number;
}

export interface K8sPod {
  id: string;
  name: string;
  namespace: string;
  status: "running" | "pending" | "succeeded" | "failed" | "unknown";
  restarts: number;
  node: string;
  containers: number;
  cpu: number;
  memory: number;
}

export interface K8sService {
  id: string;
  name: string;
  namespace: string;
  type: "ClusterIP" | "NodePort" | "LoadBalancer" | "ExternalName";
  clusterIP: string;
  ports: ServicePort[];
}

export interface ServicePort {
  name: string;
  port: number;
  targetPort: number;
  protocol: string;
}

export interface K8sDeployment {
  id: string;
  name: string;
  namespace: string;
  replicas: number;
  available: number;
  updated: number;
  strategy: string;
  status: "progressing" | "available" | "failed";
}

export interface Database {
  id: string;
  name: string;
  type: "postgresql" | "mysql" | "mongodb" | "redis" | "elasticsearch" | "clickhouse";
  host: string;
  port: number;
  status: "connected" | "disconnected" | "error";
  size: number;
  connections: number;
  queriesPerSecond: number;
  slowQueries: number;
  replicationLag: number;
  backupStatus: "ok" | "warning" | "error";
  lastBackup: string;
  createdAt: string;
}

export interface LogEntry {
  id: string;
  timestamp: string;
  level: "debug" | "info" | "warning" | "error" | "critical";
  service: string;
  message: string;
  metadata?: Record<string, unknown>;
  traceId?: string;
  userId?: string;
  source: string;
}

export interface Alert {
  id: string;
  title: string;
  description: string;
  severity: "info" | "warning" | "critical" | "fatal";
  status: "active" | "acknowledged" | "resolved" | "suppressed";
  source: string;
  metric?: string;
  threshold?: number;
  currentValue?: number;
  assignedTo?: string;
  createdAt: string;
  resolvedAt?: string;
}

export interface Notification {
  id: string;
  type: "info" | "success" | "warning" | "error";
  title: string;
  message: string;
  read: boolean;
  action?: { label: string; url: string };
  createdAt: string;
}

export interface Task {
  id: string;
  title: string;
  description?: string;
  status: "todo" | "in_progress" | "review" | "done" | "cancelled";
  priority: "low" | "medium" | "high" | "urgent";
  assigneeId?: string;
  projectId?: string;
  tags: string[];
  dueDate?: string;
  estimatedHours?: number;
  actualHours?: number;
  createdAt: string;
  updatedAt: string;
}

export interface Meeting {
  id: string;
  title: string;
  description?: string;
  status: "scheduled" | "ongoing" | "completed" | "cancelled";
  startTime: string;
  endTime: string;
  organizerId: string;
  attendeeIds: string[];
  room?: string;
  link?: string;
  recording?: string;
  transcript?: string;
  aiSummary?: string;
  createdAt: string;
}

export interface KnowledgeDocument {
  id: string;
  title: string;
  content: string;
  type: "document" | "article" | "guide" | "faq" | "code" | "api";
  category: string;
  tags: string[];
  authorId: string;
  organizationId: string;
  workspaceId?: string;
  projectId?: string;
  version: number;
  status: "draft" | "published" | "archived";
  viewCount: number;
  aiSummary?: string;
  aiEmbeddings?: number[];
  relatedIds: string[];
  createdAt: string;
  updatedAt: string;
}

export interface SecurityEvent {
  id: string;
  timestamp: string;
  type: "login" | "logout" | "failed_login" | "permission_change" | "data_access" | "api_call" | "suspicious" | "breach";
  userId?: string;
  ip: string;
  userAgent: string;
  resource: string;
  action: string;
  result: "success" | "failure" | "blocked";
  riskScore: number;
  details?: Record<string, unknown>;
  geoLocation?: GeoLocation;
}

export interface GeoLocation {
  country: string;
  city: string;
  lat: number;
  lng: number;
}

export interface Invoice {
  id: string;
  number: string;
  organizationId: string;
  status: "draft" | "sent" | "paid" | "overdue" | "cancelled";
  amount: number;
  currency: string;
  items: InvoiceItem[];
  dueDate: string;
  paidAt?: string;
  createdAt: string;
}

export interface InvoiceItem {
  description: string;
  quantity: number;
  unitPrice: number;
  total: number;
}

export interface DashboardStats {
  totalUsers: number;
  totalOrganizations: number;
  totalProjects: number;
  totalAgents: number;
  activeAgents: number;
  totalWorkflows: number;
  activeWorkflows: number;
  totalServers: number;
  onlineServers: number;
  totalContainers: number;
  runningContainers: number;
  totalDatabases: number;
  healthyDatabases: number;
  alertsToday: number;
  criticalAlerts: number;
  tasksToday: number;
  completedTasks: number;
  meetingsToday: number;
  cpuUsage: number;
  memoryUsage: number;
  storageUsage: number;
  networkRx: number;
  networkTx: number;
  aiCostToday: number;
  aiTokensToday: number;
  apiCallsToday: number;
  apiErrorsToday: number;
}

export interface ChartData {
  labels: string[];
  datasets: ChartDataset[];
}

export interface ChartDataset {
  label: string;
  data: number[];
  color?: string;
  fill?: boolean;
  type?: "line" | "bar" | "area";
}

export interface SearchResult {
  id: string;
  type: "project" | "agent" | "workflow" | "document" | "user" | "server" | "task" | "log";
  title: string;
  subtitle?: string;
  icon?: string;
  url: string;
  metadata?: Record<string, unknown>;
}

export interface CommandItem {
  id: string;
  name: string;
  shortcut?: string;
  icon?: string;
  action: () => void;
  category: string;
}

export interface NavSection {
  id: string;
  label: string;
  icon: string;
  href?: string;
  children?: NavItem[];
  badge?: number;
  shortcut?: string;
}

export interface NavItem {
  id: string;
  label: string;
  icon: string;
  href: string;
  badge?: number;
  shortcut?: string;
}
