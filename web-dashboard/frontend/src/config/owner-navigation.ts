import type { LucideIcon } from "lucide-react";
import {
  Activity,
  AlertTriangle,
  ArchiveRestore,
  BadgeCheck,
  BarChart3,
  Bell,
  BellRing,
  Building2,
  CheckCircle2,
  ClipboardCheck,
  Clock3,
  Coins,
  Combine,
  CreditCard,
  Database,
  FileCheck2,
  FileCog,
  FolderKanban,
  Gauge,
  Gavel,
  GitPullRequest,
  HeartPulse,
  KeyRound,
  LockKeyhole,
  LifeBuoy,
  Map,
  MessageCircle,
  Network,
  Palette,
  PlugZap,
  RadioTower,
  Rocket,
  ScrollText,
  Search,
  Server,
  Shield,
  ShieldCheck,
  Terminal,
  ToggleRight,
  UserCog,
} from "lucide-react";

export type OwnerNavigationItem = {
  id: string;
  label: string;
  description: string;
  href: `/owner/${string}`;
  icon: LucideIcon;
};

export interface OwnerNavigationSection {
  id: string;
  label: string;
  icon: LucideIcon;
  items: OwnerNavigationItem[];
}

export const ownerNavigationSections: OwnerNavigationSection[] = [
  {
    id: "owner-overview-control",
    label: "Owner Control",
    icon: Gauge,
    items: [
      {
        id: "owner-executive",
        label: "Executive Overview",
        description:
          "Strategic platform status, risks, readiness, and decisions.",
        href: "/owner/executive",
        icon: Gauge,
      },
      {
        id: "owner-executive-bi",
        label: "Executive Intelligence",
        description:
          "Operational inventory, availability, and incident intelligence.",
        href: "/owner/executive-bi",
        icon: BarChart3,
      },
      {
        id: "owner-runtime",
        label: "Live Ownership Data",
        description: "Projects, organizations, and users across the platform.",
        href: "/owner/runtime",
        icon: Database,
      },
      {
        id: "owner-global-command",
        label: "Global Command",
        description: "Platform-wide operational commands and risk visibility.",
        href: "/owner/global-command",
        icon: RadioTower,
      },
      {
        id: "owner-portal",
        label: "VIP Portal Control",
        description:
          "Branding, theme, pages, pricing, assets, translations, publishing, and rollback.",
        href: "/owner/portal",
        icon: Palette,
      },
      {
        id: "owner-operations",
        label: "Entity Operations",
        description: "Protected project, organization, and user operations.",
        href: "/owner/operations",
        icon: Terminal,
      },
      {
        id: "owner-realtime",
        label: "Realtime Monitoring",
        description:
          "Auto-refreshed backend metrics and owner audit-event visibility.",
        href: "/owner/realtime",
        icon: Activity,
      },
      {
        id: "owner-timeline",
        label: "Global Timeline",
        description: "Unified owner activity across platform domains.",
        href: "/owner/timeline",
        icon: Clock3,
      },
      {
        id: "owner-system-map",
        label: "System Topology",
        description: "Latest backend-reported dependency nodes and health.",
        href: "/owner/system-map",
        icon: Map,
      },
      {
        id: "owner-health",
        label: "System Health",
        description:
          "Platform readiness, dependencies, and operational health.",
        href: "/owner/health",
        icon: HeartPulse,
      },
      {
        id: "owner-search",
        label: "Global Search",
        description:
          "Search owner-visible projects, services, policies, and records.",
        href: "/owner/search",
        icon: Search,
      },
    ],
  },
  {
    id: "owner-governance",
    label: "Owner Governance",
    icon: Gavel,
    items: [
      {
        id: "owner-projects",
        label: "Project Command",
        description: "Govern and review every project from one center.",
        href: "/owner/projects",
        icon: FolderKanban,
      },
      {
        id: "owner-organizations",
        label: "Organizations",
        description: "Organization plans, boundaries, access, and status.",
        href: "/owner/organizations",
        icon: Building2,
      },
      {
        id: "owner-policies",
        label: "Policy Engine",
        description: "Global policy scope, enforcement, and lifecycle.",
        href: "/owner/policies",
        icon: FileCog,
      },
      {
        id: "owner-approvals",
        label: "Approval Center",
        description: "Pending meeting requests requiring an owner decision.",
        href: "/owner/approvals",
        icon: GitPullRequest,
      },
      {
        id: "owner-approvals-live",
        label: "Approval Execution",
        description:
          "Protected meeting approve, reject, and request-changes workflow.",
        href: "/owner/approvals-live",
        icon: ClipboardCheck,
      },
      {
        id: "owner-councils",
        label: "Owner Decisions",
        description: "Durable owner decision records and approval state.",
        href: "/owner/governance",
        icon: Gavel,
      },
      {
        id: "owner-billing",
        label: "Billing & Plans",
        description: "Organization plan, seat, and access-status controls.",
        href: "/owner/billing",
        icon: CreditCard,
      },
      {
        id: "owner-licensing",
        label: "Licensing",
        description: "Organization plan, seat, suspension, and restore status.",
        href: "/owner/licensing",
        icon: BadgeCheck,
      },
      {
        id: "owner-compliance",
        label: "Compliance",
        description: "Framework controls, evidence, risk, and assurance.",
        href: "/owner/compliance",
        icon: FileCheck2,
      },
      {
        id: "owner-compliance-runtime",
        label: "Compliance Runtime",
        description: "Live compliance controls and owner attestations.",
        href: "/owner/compliance-runtime",
        icon: ShieldCheck,
      },
      {
        id: "owner-access",
        label: "Access Authority",
        description: "Owner identity, roles, permissions, and suspensions.",
        href: "/owner/access",
        icon: KeyRound,
      },
    ],
  },
  {
    id: "owner-services-security",
    label: "Owner Services & Security",
    icon: Shield,
    items: [
      {
        id: "owner-services",
        label: "Service Control",
        description: "Enable, suspend, and govern platform services.",
        href: "/owner/services",
        icon: ToggleRight,
      },
      {
        id: "owner-integrations",
        label: "Integrations Registry",
        description:
          "AI, cloud, source control, database, and channel integrations.",
        href: "/owner/integrations",
        icon: PlugZap,
      },
      {
        id: "owner-platform-integration",
        label: "Platform Integration",
        description:
          "Orchestration, workers, memory, providers, and notifications.",
        href: "/owner/platform-integration",
        icon: Network,
      },
      {
        id: "owner-secrets",
        label: "Secrets & Keys",
        description: "Masked credentials, rotation, revocation, and scope.",
        href: "/owner/secrets",
        icon: LockKeyhole,
      },
      {
        id: "owner-security-integration",
        label: "Security Integration",
        description:
          "Identity, secrets, threat defense, and compliance health.",
        href: "/owner/security-integration",
        icon: Shield,
      },
      {
        id: "owner-notifications",
        label: "Notifications",
        description:
          "Owner-visible project, approval, incident, and completion notices.",
        href: "/owner/notifications",
        icon: Bell,
      },
      {
        id: "owner-notification-runtime",
        label: "Notification Runtime",
        description:
          "Delivery rules for in-app, email, push, Telegram, and WhatsApp.",
        href: "/owner/notification-runtime",
        icon: BellRing,
      },
      {
        id: "owner-communications",
        label: "Communications",
        description: "Communication channels, routing, and delivery control.",
        href: "/owner/communications",
        icon: MessageCircle,
      },
      {
        id: "owner-support",
        label: "Support Command",
        description:
          "Durable support conversations, assignment, and resolution.",
        href: "/owner/support",
        icon: LifeBuoy,
      },
      {
        id: "owner-incidents",
        label: "Incident Command",
        description: "Operational and security incident coordination.",
        href: "/owner/incidents",
        icon: AlertTriangle,
      },
      {
        id: "owner-audit",
        label: "Owner Audit",
        description: "Owner decisions, staff actions, policies, and approvals.",
        href: "/owner/audit",
        icon: ScrollText,
      },
      {
        id: "owner-costs",
        label: "Cost Governance",
        description:
          "Budgets, limits, service usage, and suspension thresholds.",
        href: "/owner/costs",
        icon: Coins,
      },
    ],
  },
  {
    id: "owner-recovery-release",
    label: "Owner Recovery & Release",
    icon: Rocket,
    items: [
      {
        id: "owner-recovery",
        label: "Recovery Center",
        description:
          "Backups, restore validation, and disaster recovery drills.",
        href: "/owner/recovery",
        icon: ArchiveRestore,
      },
      {
        id: "owner-operations-integration",
        label: "Operations Integration",
        description:
          "Dependency health, alert, backup, and recovery readiness.",
        href: "/owner/operations-integration",
        icon: Activity,
      },
      {
        id: "owner-production-runtime",
        label: "Production Runtime",
        description: "Live backend dependency health and configured origins.",
        href: "/owner/production-runtime",
        icon: Server,
      },
      {
        id: "owner-release",
        label: "Release Authority",
        description: "Final quality, security, performance, and owner gates.",
        href: "/owner/release",
        icon: Rocket,
      },
      {
        id: "owner-release-governance",
        label: "Release Governance",
        description: "Release candidates, quality gates, and owner decisions.",
        href: "/owner/release-governance",
        icon: GitPullRequest,
      },
      {
        id: "owner-final-platform-integration",
        label: "Final Integration",
        description:
          "Live backend dependency and non-owner release-gate readiness.",
        href: "/owner/final-platform-integration",
        icon: Combine,
      },
      {
        id: "owner-finalization",
        label: "Production Finalization",
        description:
          "Integration, security, performance, reliability, and usability checks.",
        href: "/owner/finalization",
        icon: CheckCircle2,
      },
      {
        id: "owner-completion",
        label: "Completion Inventory",
        description: "Full owner capability and navigation completion check.",
        href: "/owner/completion",
        icon: ClipboardCheck,
      },
      {
        id: "owner-staff",
        label: "Staff Oversight",
        description: "Internal staff identity, role, organization, and status.",
        href: "/owner/staff",
        icon: UserCog,
      },
    ],
  },
];

export const ownerNavigationItems = ownerNavigationSections.flatMap(
  (section) => section.items,
);
