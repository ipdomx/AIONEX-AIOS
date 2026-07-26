import axios, { AxiosError, AxiosInstance, AxiosRequestConfig } from "axios";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "/api/v1";
const ACCESS_TOKEN_KEY = "aionex.access_token";
const REFRESH_TOKEN_KEY = "aionex.refresh_token";

export interface ApiErrorShape {
  detail?: string | { message?: string };
  code?: string;
  message?: string;
}

function createCorrelationId(): string {
  const cryptoApi = typeof globalThis !== "undefined" ? globalThis.crypto : undefined;
  if (cryptoApi && typeof cryptoApi.randomUUID === "function") return cryptoApi.randomUUID();
  if (cryptoApi && typeof cryptoApi.getRandomValues === "function") {
    const bytes = new Uint8Array(16);
    cryptoApi.getRandomValues(bytes);
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    const hex = Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
  }
  return `aionex-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}

function browserStorage(): Storage | null {
  return typeof window !== "undefined" ? window.localStorage : null;
}

class ApiClient {
  private readonly client: AxiosInstance;
  private refreshPromise: Promise<string | null> | null = null;

  constructor() {
    this.client = axios.create({
      baseURL: API_BASE_URL,
      timeout: 15000,
      headers: { "Content-Type": "application/json" },
      withCredentials: true,
    });

    this.client.interceptors.request.use((config) => {
      const storage = browserStorage();
      const token = storage?.getItem(ACCESS_TOKEN_KEY);
      if (token) config.headers.Authorization = `Bearer ${token}`;
      config.headers["X-Correlation-ID"] = createCorrelationId();
      return config;
    });

    this.client.interceptors.response.use(
      (response) => response,
      async (error: AxiosError<ApiErrorShape>) => {
        const original = error.config as (AxiosRequestConfig & { _retry?: boolean }) | undefined;
        if (error.response?.status === 401 && original && !original._retry && !String(original.url).includes("/auth/")) {
          original._retry = true;
          const token = await this.refreshAccessToken();
          if (token) {
            original.headers = { ...(original.headers || {}), Authorization: `Bearer ${token}` };
            return this.client.request(original);
          }
        }
        return Promise.reject(error);
      },
    );
  }

  private async refreshAccessToken(): Promise<string | null> {
    const storage = browserStorage();
    const refreshToken = storage?.getItem(REFRESH_TOKEN_KEY);
    if (!storage || !refreshToken) return null;
    if (!this.refreshPromise) {
      this.refreshPromise = axios
        .post(`${API_BASE_URL}/auth/refresh`, { refresh_token: refreshToken }, { headers: { "X-Correlation-ID": createCorrelationId() } })
        .then((response) => {
          const accessToken = response.data?.access_token as string | undefined;
          const nextRefreshToken = response.data?.refresh_token as string | undefined;
          if (!accessToken) return null;
          storage.setItem(ACCESS_TOKEN_KEY, accessToken);
          if (nextRefreshToken) storage.setItem(REFRESH_TOKEN_KEY, nextRefreshToken);
          return accessToken;
        })
        .catch(() => {
          storage.removeItem(ACCESS_TOKEN_KEY);
          storage.removeItem(REFRESH_TOKEN_KEY);
          storage.removeItem("aionex.user");
          return null;
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
      const axiosError = error as AxiosError<ApiErrorShape>;
      const payload = axiosError.response?.data;
      const detail = payload?.detail;
      const message = typeof detail === "string"
        ? detail
        : detail?.message || payload?.message || axiosError.message || "Request failed";
      throw new Error(message);
    }
  }

  get<T>(url: string, config?: AxiosRequestConfig): Promise<T> {
    return this.request<T>({ ...config, method: "GET", url });
  }

  post<T>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<T> {
    return this.request<T>({ ...config, method: "POST", url, data });
  }

  put<T>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<T> {
    return this.request<T>({ ...config, method: "PUT", url, data });
  }

  delete<T>(url: string, config?: AxiosRequestConfig): Promise<T> {
    return this.request<T>({ ...config, method: "DELETE", url });
  }
}

export const apiClient = new ApiClient();
export { API_BASE_URL, createCorrelationId };
