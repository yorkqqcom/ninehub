const TOKEN_KEY = "ninehub.token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

export function obtainWatchToken(): string | null {
  return getToken();
}

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

function looksLikeHtml(text: string): boolean {
  const head = text.slice(0, 64).trim().toLowerCase();
  return head.startsWith("<!doctype") || head.startsWith("<html");
}

async function readJsonBody<T>(response: Response): Promise<T> {
  const text = await response.text();
  if (!text) {
    return undefined as T;
  }
  if (looksLikeHtml(text)) {
    throw new ApiError(
      `接口返回了网页而非 JSON（${response.url || "unknown"}）。请确认访问 http://127.0.0.1:8888/watch/ 且后端 API 正常。`,
      response.status || 502,
    );
  }
  try {
    return JSON.parse(text) as T;
  } catch {
    throw new ApiError("响应不是合法 JSON", response.status || 502);
  }
}

export async function apiRequest<T>(path: string, options: RequestInit = {}): Promise<T> {
  const origin = typeof window !== "undefined" ? window.location.origin : "";
  const apiPath = path.startsWith("/") ? path : `/${path}`;
  // Always hit /api/v1 on origin — never under /watch/ (SPA would return index.html)
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Accept: "application/json",
    ...(options.headers as Record<string, string> | undefined),
  };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  const response = await fetch(`${origin}${apiPath}`, {
    ...options,
    headers,
    cache: "no-store",
  });
  if (response.status === 401) {
    clearToken();
    const base = import.meta.env.BASE_URL || "/watch/";
    const login = `${base}login`.replace(/\/{2,}/g, "/");
    const here = window.location.pathname;
    if (!here.includes("/login")) {
      window.location.href = `${login}?redirect=${encodeURIComponent(here)}`;
    }
    throw new ApiError("未登录或会话过期", 401);
  }
  if (!response.ok) {
    let detail = response.statusText || `HTTP ${response.status}`;
    try {
      const body = await readJsonBody<{ detail?: unknown }>(response);
      if (body && typeof body === "object" && body.detail != null) {
        detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
      }
    } catch (err) {
      if (err instanceof ApiError) throw err;
    }
    throw new ApiError(detail, response.status);
  }
  if (response.status === 204) return undefined as T;
  return readJsonBody<T>(response);
}
