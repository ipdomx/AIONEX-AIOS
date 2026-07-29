import { apiClient } from "@/lib/api-client";

export type OwnerEntityKind = "project" | "organization" | "user";
export type OwnerOperation =
  "create" | "update" | "suspend" | "restore" | "delete";

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

export async function executeOwnerOperation(
  request: OwnerOperationRequest,
  signal?: AbortSignal,
): Promise<OwnerOperationResult> {
  return apiClient.post<OwnerOperationResult>("/owner/operations", request, {
    signal,
  });
}
