import axios, { AxiosError, AxiosInstance, AxiosRequestConfig } from "axios";

import {
  createRefreshGate,
  parseRetryAfterMs,
  RefreshFailure,
} from "@/lib/auth-refresh-gate";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "/api/v1";

export interface ApiErrorShape {
  detail?: string | { message?: string };
  code?: string;
  message?: string;
}

function createCorrelationId(): string {
  const cryptoApi =
    typeof globalThis !== "undefined" ? globalThis.crypto : undefined;
  if (cryptoApi && typeof cryptoApi.randomUUID === "function")
    return cryptoApi.randomUUID();
  if (cryptoApi && typeof cryptoApi.getRandomValues === "function") {
    const bytes = new Uint8Array(16);
    cryptoApi.getRandomValues(bytes);
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    const hex = Array.from(bytes, (value) =>
      value.toString(16).padStart(2, "0"),
    ).join("");
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
  }
  return `aionex-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}

const SESSION_STORAGE_KEYS = [
  "aionex.access_token",
  "aionex.refresh_token",
  "aionex.user",
] as const;

function hasSessionHint(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return Boolean(window.localStorage.getItem("aionex.user"));
  } catch {
    return false;
  }
}

function clearStoredSession(): void {
  if (typeof window === "undefined") return;
  try {
    for (const key of SESSION_STORAGE_KEYS) window.localStorage.removeItem(key);
  } catch {
    // Storage may be blocked by browser privacy settings.
  }
}

class ApiClient {
  private readonly client: AxiosInstance;
  // Single-flight refresh: never for anonymous visitors, never retried after
  // a failure (terminal failures clear the session once, all failures back off).
  private readonly refreshGate = createRefreshGate<true>({
    hasSessionHint,
    clearSession: clearStoredSession,
  });

  constructor() {
    this.client = axios.create({
      baseURL: API_BASE_URL,
      timeout: 15000,
      headers: { "Content-Type": "application/json" },
      withCredentials: true,
    });

    this.client.interceptors.request.use((config) => {
      if (typeof FormData !== "undefined" && config.data instanceof FormData) {
        delete config.headers["Content-Type"];
      }
      config.headers["X-Correlation-ID"] = createCorrelationId();
      return config;
    });

    this.client.interceptors.response.use(
      (response) => response,
      async (error: AxiosError<ApiErrorShape>) => {
        const original = error.config as
          (AxiosRequestConfig & { _retry?: boolean }) | undefined;
        if (
          error.response?.status === 401 &&
          original &&
          !original._retry &&
          !String(original.url).includes("/auth/")
        ) {
          original._retry = true;
          const refreshed = await this.refreshAccessToken();
          if (refreshed) return this.client.request(original);
        }
        return Promise.reject(error);
      },
    );
  }

  private async refreshAccessToken(): Promise<boolean> {
    const refreshed = await this.refreshGate.run(async () => {
      try {
        await axios.post(
          `${API_BASE_URL}/auth/refresh`,
          {},
          {
            withCredentials: true,
            headers: { "X-Correlation-ID": createCorrelationId() },
          },
        );
        return true as const;
      } catch (error) {
        const response = (error as AxiosError).response;
        if (!response) throw new RefreshFailure(null);
        const retryAfter = response.headers?.["retry-after"];
        throw new RefreshFailure(
          response.status,
          parseRetryAfterMs(typeof retryAfter === "string" ? retryAfter : null),
        );
      }
    });
    return refreshed === true;
  }

  /** Lift any refresh backoff after an explicit, successful sign-in. */
  resetRefreshBackoff(): void {
    this.refreshGate.reset();
  }

  async request<T>(config: AxiosRequestConfig): Promise<T> {
    try {
      const response = await this.client.request<T>(config);
      return response.data;
    } catch (error) {
      if (axios.isCancel(error)) {
        throw new DOMException("The request was aborted", "AbortError");
      }
      const axiosError = error as AxiosError<ApiErrorShape>;
      const payload = axiosError.response?.data;
      const detail = payload?.detail;
      const message =
        typeof detail === "string"
          ? detail
          : detail?.message ||
            payload?.message ||
            axiosError.message ||
            "Request failed";
      throw new Error(message);
    }
  }

  get<T>(url: string, config?: AxiosRequestConfig): Promise<T> {
    return this.request<T>({ ...config, method: "GET", url });
  }

  post<T>(
    url: string,
    data?: unknown,
    config?: AxiosRequestConfig,
  ): Promise<T> {
    return this.request<T>({ ...config, method: "POST", url, data });
  }

  put<T>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<T> {
    return this.request<T>({ ...config, method: "PUT", url, data });
  }

  patch<T>(
    url: string,
    data?: unknown,
    config?: AxiosRequestConfig,
  ): Promise<T> {
    return this.request<T>({ ...config, method: "PATCH", url, data });
  }

  delete<T>(url: string, config?: AxiosRequestConfig): Promise<T> {
    return this.request<T>({ ...config, method: "DELETE", url });
  }
}

export const apiClient = new ApiClient();
export { API_BASE_URL, createCorrelationId };
