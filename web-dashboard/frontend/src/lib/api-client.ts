import axios, { AxiosError, AxiosInstance, AxiosRequestConfig } from "axios";

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


class ApiClient {
  private readonly client: AxiosInstance;
  private refreshPromise: Promise<boolean> | null = null;

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
    if (!this.refreshPromise) {
      this.refreshPromise = axios
        .post(
          `${API_BASE_URL}/auth/refresh`,
          {},
          {
            withCredentials: true,
            headers: { "X-Correlation-ID": createCorrelationId() },
          },
        )
        .then(() => true)
        .catch(() => {
          if (typeof window !== "undefined") {
            window.localStorage.removeItem("aionex.access_token");
            window.localStorage.removeItem("aionex.refresh_token");
            window.localStorage.removeItem("aionex.user");
          }
          return false;
        })
        .finally(() => {
          this.refreshPromise = null;
        });
    }
    return this.refreshPromise;
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
