"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  createOwnerResource,
  executeOwnerResourceAction,
  fetchOwnerResources,
  type OwnerResourceDomain,
} from "@/lib/owner-resources";

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Owner request failed";
}

export function useOwnerResource<T>(domain: OwnerResourceDomain) {
  const [items, setItems] = useState<T[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("Loading live owner data...");
  const actionInFlight = useRef(false);

  const load = useCallback(
    async (signal?: AbortSignal, silent = false) => {
      if (!silent) setLoading(true);
      try {
        const response = await fetchOwnerResources<T>(domain, signal);
        setItems(response.items);
        if (!silent) {
          setMessage(
            `Synchronized ${response.items.length} record${response.items.length === 1 ? "" : "s"}.`,
          );
        }
      } catch (error) {
        if (!(error instanceof DOMException && error.name === "AbortError")) {
          if (!silent) {
            setItems([]);
            setMessage(errorMessage(error));
          }
        }
      } finally {
        if (!silent) setLoading(false);
      }
    },
    [domain],
  );

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const refresh = useCallback(
    async (signal?: AbortSignal) => load(signal, true),
    [load],
  );

  const execute = useCallback(
    async (
      resourceId: string,
      action: string,
      payload: Record<string, unknown> = {},
    ) => {
      if (actionInFlight.current) return false;
      actionInFlight.current = true;
      setBusy(true);
      try {
        const response = await executeOwnerResourceAction<T>(
          domain,
          resourceId,
          action,
          payload,
        );
        setItems(response.items);
        setMessage(`${action} accepted; live records synchronized.`);
        return true;
      } catch (error) {
        setMessage(errorMessage(error));
        return false;
      } finally {
        actionInFlight.current = false;
        setBusy(false);
      }
    },
    [domain],
  );

  const create = useCallback(
    async (payload: Record<string, unknown>, id?: string) => {
      if (actionInFlight.current) return false;
      actionInFlight.current = true;
      setBusy(true);
      try {
        const response = await createOwnerResource<T>(domain, payload, id);
        setItems(response.items);
        setMessage("Owner resource saved and synchronized.");
        return true;
      } catch (error) {
        setMessage(errorMessage(error));
        return false;
      } finally {
        actionInFlight.current = false;
        setBusy(false);
      }
    },
    [domain],
  );

  return {
    items,
    loading,
    busy,
    message,
    reload: load,
    refresh,
    execute,
    create,
  };
}
