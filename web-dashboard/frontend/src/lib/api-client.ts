import axios, { AxiosError, AxiosInstance, AxiosRequestConfig } from "axios";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

export interface ApiErrorShape {
  detail?: string;
  code?: string;
  message?: string;
}

class ApiClient {
  private readonly client: AxiosInstance;

  constructor() {
    this.client = axios.create({
      baseURL: API_BASE_URL,
      timeout: 15000,
      headers: { "Content-Type": "application/json" },
      withCredentials: true,
    });

    this.client.interceptors.request.use((config) => {
      if (typeof window !== "undefined") {
        const token = window.localStorage.getItem("aionex.access_token");
        if (token) {
          config.headers.Authorization = `Bearer ${token}`;
        }
      }
      config.headers["X-Correlation-ID"] = crypto.randomUUID();
      return config;
    });
  }

  async request<T>(config: AxiosRequestConfig): Promise<T> {
    try {
      const response = await this.client.request<T>(config);
      return response.data;
    } catch (error) {
      const axiosError = error as AxiosError<ApiErrorShape>;
      const payload = axiosError.response?.data;
      const message = payload?.detail || payload?.message || axiosError.message || "Request failed";
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
export { API_BASE_URL };
