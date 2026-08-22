let csrfToken = "";

export async function api<T>(path: string, options: RequestInit = {}, csrf = false): Promise<T> {
  if (csrf && !csrfToken) {
    const response = await fetch("/api/auth/csrf", { method: "POST", credentials: "same-origin" });
    if (!response.ok) throw new Error("보안 토큰을 준비하지 못했습니다.");
    csrfToken = (await response.json()).csrf_token;
  }
  const headers = new Headers(options.headers);
  if (options.body && !(options.body instanceof FormData)) headers.set("Content-Type", "application/json");
  if (csrf) headers.set("X-CSRF-Token", csrfToken);
  const response = await fetch(path, { ...options, headers, credentials: "same-origin" });
  if (response.status === 401 && path !== "/api/auth/me") {
    window.location.href = "/";
    throw new Error("로그인이 만료되었습니다.");
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail || "요청을 처리하지 못했습니다.");
  }
  if (response.status === 204) return undefined as T;
  return response.json();
}

export function idempotencyKey(prefix: string): string {
  return `${prefix}-${crypto.randomUUID()}`;
}

export async function openRealtime(onMessage: (message: any) => void): Promise<WebSocket> {
  const { ticket } = await api<{ ticket: string }>("/api/auth/websocket-ticket", { method: "POST" }, true);
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${scheme}://${location.host}/ws?ticket=${encodeURIComponent(ticket)}`);
  socket.addEventListener("message", event => {
    try { onMessage(JSON.parse(event.data)); }
    catch { /* Ignore malformed server frames and keep the live connection usable. */ }
  });
  return socket;
}
