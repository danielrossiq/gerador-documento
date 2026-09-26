// Cliente HTTP da API. Mesma origem (/api via rewrite do Next): cookie HttpOnly de sessão + cabeçalho CSRF.

export class ApiError extends Error {
  status: number;
  code: string;
  details?: unknown;
  requestId?: string;
  constructor(status: number, code: string, message: string, details?: unknown, requestId?: string) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
    this.requestId = requestId;
  }
}

function csrfToken(): string {
  if (typeof document === "undefined") return "";
  const m = document.cookie.match(/(?:^|;\s*)minuta_csrf=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : "";
}

export const AUTH_EXPIRED_EVENT = "minuta:auth-expired";

type Opts = { headers?: Record<string, string>; signal?: AbortSignal };

async function request<T>(method: string, path: string, body?: unknown, opts: Opts = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json", ...(opts.headers ?? {}) };
  let payload: BodyInit | undefined;
  if (body instanceof FormData) payload = body;
  else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  if (method !== "GET") {
    const t = csrfToken();
    if (t) headers["X-CSRF-Token"] = t;
  }
  let res: Response;
  try {
    res = await fetch(`/api/v1${path}`, { method, headers, body: payload, credentials: "same-origin", signal: opts.signal });
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new ApiError(0, "NETWORK_ERROR", "Sem conexão com o servidor. Verifique sua internet e tente novamente.");
  }
  if (res.status === 204) return undefined as T;
  const ct = res.headers.get("content-type") ?? "";
  const data = ct.includes("application/json") ? await res.json().catch(() => null) : null;
  if (!res.ok) {
    const err = (data as { error?: { code: string; message: string; details?: unknown; request_id?: string } } | null)?.error;
    if (res.status === 401 && typeof window !== "undefined" && !path.startsWith("/auth/")) {
      window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT));
    }
    throw new ApiError(res.status, err?.code ?? "HTTP_ERROR", err?.message ?? `Erro ${res.status}`, err?.details, err?.request_id);
  }
  return data as T;
}

export const api = {
  get: <T>(path: string, opts?: Opts) => request<T>("GET", path, undefined, opts),
  post: <T>(path: string, body?: unknown, opts?: Opts) => request<T>("POST", path, body ?? {}, opts),
  put: <T>(path: string, body?: unknown, opts?: Opts) => request<T>("PUT", path, body ?? {}, opts),
  patch: <T>(path: string, body?: unknown, opts?: Opts) => request<T>("PATCH", path, body ?? {}, opts),
  delete: <T>(path: string, opts?: Opts) => request<T>("DELETE", path, undefined, opts),
  upload: <T>(path: string, file: File, opts?: Opts) => {
    const fd = new FormData();
    fd.append("file", file);
    return request<T>("POST", path, fd, opts);
  },
};

/** Baixa um arquivo gerado pedindo antes um link assinado e curto (a API autoriza e audita). */
export async function downloadFile(fileId: string): Promise<void> {
  const { url } = await api.post<{ url: string }>(`/files/${fileId}/link`);
  const a = document.createElement("a");
  a.href = url;
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
}

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error) return e.message;
  return "Ocorreu um erro inesperado.";
}
