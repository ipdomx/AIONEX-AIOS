from pathlib import Path

root = Path(__file__).resolve().parents[2]

auth_path = root / 'web-dashboard/backend/app/api/v1/endpoints/auth.py'
text = auth_path.read_text()
text = text.replace(
    '    referrer: str | None = Field(default=None, max_length=500)\n',
    '    referrer: str | None = Field(default=None, max_length=500)\n'
    '    vendor: str | None = Field(default=None, max_length=160)\n'
    '    webdriver: bool | None = None\n',
)
auth_path.write_text(text)

test_path = root / 'web-dashboard/backend/tests/test_owner_dashboard_integration.py'
text = test_path.read_text()
route_marker = '    ("GET", "/api/v1/owner/finalization"),\n'
route_additions = (
    '    ("GET", "/api/v1/owner/free-tier"),\n'
    '    ("PATCH", "/api/v1/owner/free-tier"),\n'
)
if route_additions not in text:
    if route_marker not in text:
        raise SystemExit('owner route insertion point not found')
    text = text.replace(route_marker, route_marker + route_additions, 1)

needle = '''    ("PATCH", "/api/v1/owner/licenses/{license_id}"): {
        "action": "suspend",
    },
'''
replacement = needle + '''    ("PATCH", "/api/v1/owner/free-tier"): {
        "enabled": True,
    },
'''
mutation_section = text.split('OWNER_MUTATION_REQUESTS = {', 1)[1]
if '("PATCH", "/api/v1/owner/free-tier")' not in mutation_section:
    if needle not in text:
        raise SystemExit('mutation insertion point not found')
    text = text.replace(needle, replacement, 1)
test_path.write_text(text)

client = root / 'web-dashboard/frontend/src/lib/owner-free-tier.ts'
client.write_text('''import { apiClient } from "@/lib/api-client";

export type OwnerFreeTierPolicy = {
  enabled: boolean;
  project_limit: number;
  monthly_user_message_limit: number;
  monthly_assistant_response_limit: number;
  storage_limit_bytes: number;
  max_message_characters: number;
  registrations_per_ip_per_day: number;
  minimum_age: number;
  require_phone_verification: boolean;
  require_device_signals: boolean;
  one_account_per_network: boolean;
  one_account_per_device: boolean;
  telemetry_retention_days: number;
  consent_version: string;
  require_country: boolean;
  require_cookie_consent: boolean;
};

export type OwnerFreeAccount = {
  id: string;
  name: string;
  email: string;
  status: string;
  created_at: string;
  quota: Record<string, unknown>;
  registration: Record<string, unknown> | null;
};

export type OwnerFreeTierSnapshot = {
  policy: OwnerFreeTierPolicy;
  accounts: OwnerFreeAccount[];
  account_count: number;
};

export function fetchOwnerFreeTier(
  signal?: AbortSignal,
): Promise<OwnerFreeTierSnapshot> {
  return apiClient.get<OwnerFreeTierSnapshot>("/owner/free-tier", { signal });
}

export function updateOwnerFreeTier(
  updates: Partial<OwnerFreeTierPolicy>,
): Promise<OwnerFreeTierSnapshot> {
  return apiClient.patch<OwnerFreeTierSnapshot>("/owner/free-tier", updates);
}
''')

print('patched contract and owner client')
