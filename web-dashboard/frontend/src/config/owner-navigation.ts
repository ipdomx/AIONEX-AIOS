import type { LucideIcon } from "lucide-react";
import {
  Activity,
  AlertTriangle,
  ArchiveRestore,
  BarChart3,
  Bell,
  Building2,
  Cable,
  ClipboardCheck,
  Clock,
  Coins,
  CreditCard,
  FileCheck2,
  FileCog,
  FileText,
  FolderKanban,
  Gauge,
  Gavel,
  GitPullRequest,
  HeartPulse,
  KeyRound,
  LockKeyhole,
  Map,
  MessageCircle,
  PlugZap,
  RadioTower,
  Rocket,
  Search,
  ShieldCheck,
  ToggleRight,
  UserCog,
  Workflow,
} from "lucide-react";

export interface OwnerNavigationItem {
  id: string;
  label: string;
  description: string;
  href: string;
  icon: LucideIcon;
  badge?: number;
}

export interface OwnerNavigationGroup {
  id: string;
  label: string;
  icon: LucideIcon;
  items: OwnerNavigationItem[];
}

export const ownerRootNavigationItem: OwnerNavigationItem = {
  id: "owner",
  label: "Owner Center",
  description:
    "Open the complete Super Owner command center and module inventory.",
  href: "/owner",
  icon: Gauge,
};

export const ownerNavigationGroups: OwnerNavigationGroup[] = [
  {
    id: "owner-command",
    label: "Owner Command",
    icon: RadioTower,
    items: [
      {
        id: "owner-global-command",
        label: "Global Command",
        description:
          "Control the complete owner command surface and protected entities.",
        href: "/owner/global-command",
        icon: RadioTower,
      },
      {
        id: "owner-executive",
        label: "Executive Overview",
        description:
          "Review strategic status, risk, readiness, and pending decisions.",
        href: "/owner/executive",
        icon: Gauge,
      },
      {
        id: "owner-executive-bi",
        label: "Executive Intelligence",
        description:
          "Inspect executive metrics, trends, and owner-level recommendations.",
        href: "/owner/executive-bi",
        icon: BarChart3,
      },
      {
        id: "owner-runtime",
        label: "Live Ownership Data",
        description:
          "View projects, organizations, and users from the owner runtime.",
        href: "/owner/runtime",
        icon: Workflow,
      },
      {
        id: "owner-projects",
        label: "Project Command",
        description:
          "Monitor and govern every project from a single owner view.",
        href: "/owner/projects",
        icon: FolderKanban,
      },
      {
        id: "owner-organizations",
        label: "Organizations",
        description:
          "Manage tenants, plans, access boundaries, and restrictions.",
        href: "/owner/organizations",
        icon: Building2,
      },
      {
        id: "owner-search",
        label: "Global Search",
        description:
          "Search owner-visible projects, users, agents, and audit records.",
        href: "/owner/search",
        icon: Search,
      },
      {
        id: "owner-timeline",
        label: "Activity Timeline",
        description:
          "Review the unified chronology of important owner-visible activity.",
        href: "/owner/timeline",
        icon: Clock,
      },
      {
        id: "owner-realtime",
        label: "Realtime Monitoring",
        description: "Track live runtime metrics and operational events.",
        href: "/owner/realtime",
        icon: Activity,
      },
      {
        id: "owner-system-map",
        label: "Live System Map",
        description:
          "Inspect platform services, dependencies, and infrastructure topology.",
        href: "/owner/system-map",
        icon: Map,
      },
    ],
  },
  {
    id: "owner-governance",
    label: "Governance & Authority",
    icon: Gavel,
    items: [
      {
        id: "owner-approvals",
        label: "Approvals",
        description:
          "Approve or reject releases, services, meetings, and sensitive actions.",
        href: "/owner/approvals",
        icon: GitPullRequest,
        badge: 7,
      },
      {
        id: "owner-approvals-live",
        label: "Protected Approvals",
        description: "Use the connected protected approval workflow.",
        href: "/owner/approvals-live",
        icon: ShieldCheck,
      },
      {
        id: "owner-policies",
        label: "Policy Engine",
        description: "Control global policies and enforcement behavior.",
        href: "/owner/policies",
        icon: FileCog,
      },
      {
        id: "owner-services",
        label: "Service Control",
        description: "Enable, suspend, and govern platform services.",
        href: "/owner/services",
        icon: ToggleRight,
      },
      {
        id: "owner-billing",
        label: "Billing & Plans",
        description:
          "Manage subscriptions, plans, invoices, and account status.",
        href: "/owner/billing",
        icon: CreditCard,
      },
      {
        id: "owner-licensing",
        label: "Licensing",
        description: "Review enterprise licenses, seats, and entitlements.",
        href: "/owner/licensing",
        icon: KeyRound,
      },
      {
        id: "owner-costs",
        label: "Cost Governance",
        description:
          "Control budgets, usage limits, and suspension thresholds.",
        href: "/owner/costs",
        icon: Coins,
      },
      {
        id: "owner-compliance",
        label: "Compliance",
        description:
          "Review assurance controls, evidence, and framework status.",
        href: "/owner/compliance",
        icon: FileCheck2,
      },
      {
        id: "owner-compliance-runtime",
        label: "Compliance Runtime",
        description:
          "Inspect connected compliance controls and runtime evidence.",
        href: "/owner/compliance-runtime",
        icon: ClipboardCheck,
      },
      {
        id: "owner-councils",
        label: "Councils & Ministries",
        description:
          "Manage councils, ministries, votes, quorum, and decisions.",
        href: "/owner/governance",
        icon: Gavel,
      },
      {
        id: "owner-staff",
        label: "Staff Oversight",
        description:
          "Monitor internal staff performance, incidents, and supervision.",
        href: "/owner/staff",
        icon: UserCog,
      },
      {
        id: "owner-access",
        label: "Access Authority",
        description:
          "Control privileged roles, permissions, sessions, and suspensions.",
        href: "/owner/access",
        icon: KeyRound,
      },
      {
        id: "owner-audit",
        label: "Owner Audit",
        description:
          "Inspect owner decisions, staff actions, policies, and approvals.",
        href: "/owner/audit",
        icon: FileText,
      },
      {
        id: "owner-secrets",
        label: "Secrets & Keys",
        description:
          "Govern credentials, secret access, and rotation authority.",
        href: "/owner/secrets",
        icon: LockKeyhole,
      },
    ],
  },
  {
    id: "owner-operations",
    label: "Operations & Integration",
    icon: Activity,
    items: [
      {
        id: "owner-health",
        label: "System Health",
        description:
          "Verify platform readiness, dependencies, workers, and services.",
        href: "/owner/health",
        icon: HeartPulse,
      },
      {
        id: "owner-incidents",
        label: "Incident Command",
        description: "Coordinate operational and security incident response.",
        href: "/owner/incidents",
        icon: AlertTriangle,
        badge: 3,
      },
      {
        id: "owner-notifications",
        label: "Notifications",
        description:
          "Review project, approval, incident, staff, and system notifications.",
        href: "/owner/notifications",
        icon: Bell,
        badge: 24,
      },
      {
        id: "owner-notification-runtime",
        label: "Notification Runtime",
        description:
          "Configure event rules, audiences, channels, and escalation severity.",
        href: "/owner/notification-runtime",
        icon: Bell,
      },
      {
        id: "owner-communications",
        label: "Communications",
        description:
          "Control in-app, email, push, and owner-only WhatsApp delivery.",
        href: "/owner/communications",
        icon: MessageCircle,
      },
      {
        id: "owner-integrations",
        label: "Integrations",
        description:
          "Manage external services, providers, and connection status.",
        href: "/owner/integrations",
        icon: PlugZap,
      },
      {
        id: "owner-platform-integration",
        label: "Platform Connectivity",
        description:
          "Inspect live runtime, worker, knowledge, provider, and notification links.",
        href: "/owner/platform-integration",
        icon: Cable,
      },
      {
        id: "owner-entity-operations",
        label: "Owner Tools",
        description:
          "Run protected create, update, suspend, restore, and delete operations.",
        href: "/owner/operations",
        icon: Workflow,
      },
      {
        id: "owner-operations-integration",
        label: "Operations Connectivity",
        description:
          "Connect monitoring, logging, alerting, backups, and disaster recovery.",
        href: "/owner/operations-integration",
        icon: Activity,
      },
      {
        id: "owner-security-integration",
        label: "Security Integration",
        description:
          "Inspect identity, secrets, threat defense, and compliance connectivity.",
        href: "/owner/security-integration",
        icon: ShieldCheck,
      },
      {
        id: "owner-recovery",
        label: "Recovery Center",
        description:
          "Manage backups, restore validation, and disaster recovery drills.",
        href: "/owner/recovery",
        icon: ArchiveRestore,
      },
    ],
  },
  {
    id: "owner-runtime-release",
    label: "Runtime & Release",
    icon: Rocket,
    items: [
      {
        id: "owner-production-runtime",
        label: "Production Runtime",
        description:
          "Validate deployment-ready frontend, API, edge, and configuration runtime.",
        href: "/owner/production-runtime",
        icon: Workflow,
      },
      {
        id: "owner-release",
        label: "Release Authority",
        description:
          "Apply final quality, security, performance, and owner release gates.",
        href: "/owner/release",
        icon: Rocket,
      },
      {
        id: "owner-release-governance",
        label: "Release Governance",
        description:
          "Review release candidates, quality gates, approvals, and rollback.",
        href: "/owner/release-governance",
        icon: GitPullRequest,
      },
      {
        id: "owner-finalization",
        label: "Production Readiness",
        description:
          "Run final integration, security, reliability, and usability checks.",
        href: "/owner/finalization",
        icon: FileCheck2,
      },
      {
        id: "owner-final-platform-integration",
        label: "Final Platform Integration",
        description:
          "Verify end-to-end workflows, performance, security, and release closure.",
        href: "/owner/final-platform-integration",
        icon: ShieldCheck,
      },
      {
        id: "owner-completion",
        label: "Owner Inventory",
        description:
          "Open the consolidated inventory of every owner control surface.",
        href: "/owner/completion",
        icon: ClipboardCheck,
      },
    ],
  },
];

export const ownerNavigationItems = [
  ownerRootNavigationItem,
  ...ownerNavigationGroups.flatMap((group) => group.items),
];
