import { apiClient } from "./api-client";

export interface MetricPoint { id:string; name:string; resource:string; timestamp:string|null; value:number; labels:Record<string,string>; }
export interface MonitoringLog { id:string; timestamp:string|null; level:string; service:string; message:string; trace_id?:string|null; }
export interface AlertRow { id:string; title:string; description:string; severity:string; status:string; source:string; created_at?:string|null; }
export interface SecurityThreat { id:string; title:string; description:string; severity:string; status:string; source:string; source_ip?:string|null; detected_at?:string|null; }
export interface SecurityEvent { id:string; type:string; result?:string; user_id?:string|null; ip?:string|null; risk_score?:number; risk_level?:string; timestamp?:string|null; created_at?:string|null; }
export interface AuditRow { id:string; timestamp:string|null; actor:string; action:string; resource:string; metadata:Record<string,unknown>; }
export interface PolicyRow { id:string; name:string; status:string; rules:Record<string,unknown>; source:string; version?:number; }
export interface SessionRow { id:string; user_id:string; user:string; organization_id:string; expires_at:string; revoked_at?:string|null; ip_address?:string|null; user_agent?:string|null; active:boolean; created_at:string; }
export interface RuntimeContainer { id:string; name?:string; status:string; server?:string; image?:string; control_reason?:string; [key:string]:unknown; }
export interface DatabaseRow { id:string; name?:string; type:string; status:string; [key:string]:unknown; }
export interface ServerRow { id:string; name:string; hostname?:string; status:string; os?:string; provider?:string; location?:string; [key:string]:unknown; }

export const opsSecurityServices = {
  metrics() { return apiClient.get<Record<string, MetricPoint[]>>("/monitoring/metrics"); },
  logs(params?: Record<string,unknown>) { return apiClient.get<MonitoringLog[]>("/monitoring/logs", { params }); },
  alerts(params?: Record<string,unknown>) { return apiClient.get<AlertRow[]>("/monitoring/alerts", { params }); },
  securityThreats(params?: Record<string,unknown>) { return apiClient.get<SecurityThreat[]>("/security/threats", { params }); },
  securityEvents(params?: Record<string,unknown>) { return apiClient.get<SecurityEvent[]>("/security/events", { params }); },
  audit(params?: Record<string,unknown>) { return apiClient.get<AuditRow[]>("/security/audit", { params }); },
  policies() { return apiClient.get<PolicyRow[]>("/security/policies"); },
  sessions() { return apiClient.get<SessionRow[]>("/security/sessions"); },
  terminateSession(id:string) { return apiClient.delete<{message:string;session_id:string;revoked_at:string}>(`/security/sessions/${id}`); },
  containers() { return apiClient.get<RuntimeContainer[]>("/containers"); },
  databases() { return apiClient.get<DatabaseRow[]>("/databases"); },
  servers() { return apiClient.get<ServerRow[]>("/servers"); },
};
