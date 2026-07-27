export type OwnerEntityKind = "project" | "organization" | "user";
export type OwnerOperation = "create" | "update" | "suspend" | "restore" | "delete";

export type OwnerOperationRequest = {
  entity: OwnerEntityKind;
  operation: OwnerOperation;
  id?: string;
  payload?: Record<string, unknown>;
};

export type OwnerOperationResult = {
  ok: boolean;
  operationId: string;
  message: string;
  completedAt: string;
};

export async function executeOwnerOperation(request: OwnerOperationRequest, signal?: AbortSignal): Promise<OwnerOperationResult> {
  const endpoint = process.env.NEXT_PUBLIC_OWNER_API_URL ?? "/api/owner/operations";
  const response = await fetch(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(request),
    cache: "no-store",
    signal,
  });

  if (!response.ok) {
    throw new Error(`Owner operation failed with ${response.status}`);
  }

  const result = (await response.json()) as Partial<OwnerOperationResult>;
  return {
    ok: result.ok ?? true,
    operationId: result.operationId ?? crypto.randomUUID(),
    message: result.message ?? `${request.operation} completed for ${request.entity}.`,
    completedAt: result.completedAt ?? new Date().toISOString(),
  };
}
