import { readFileSync } from "node:fs";

const source = readFileSync(new URL("../src/lib/ops-security-services.ts", import.meta.url), "utf8");
const required = [
  '"/infrastructure/containers"',
  '"/infrastructure/databases"',
  '"/infrastructure/servers"',
];
const forbidden = [
  'get<RuntimeContainer[]>("/containers")',
  'get<DatabaseRow[]>("/databases")',
  'get<ServerRow[]>("/servers")',
];
for (const contract of required) {
  if (!source.includes(contract)) throw new Error(`Missing Owner infrastructure API contract: ${contract}`);
}
for (const legacy of forbidden) {
  if (source.includes(legacy)) throw new Error(`Legacy Owner infrastructure API path returned: ${legacy}`);
}
console.log("Owner infrastructure API contracts: PASS");
