// Thin fetch wrapper for the same-origin /api proxy.
// Always sends cookies; transparently retries once via /api/auth/refresh on 401.

export async function apiFetch(
  path: string,
  init: RequestInit = {},
  _retried = false
): Promise<Response> {
  const res = await fetch(`/api${path}`, {
    ...init,
    credentials: "include",
    headers: { ...(init.headers ?? {}) },
  });

  // One transparent refresh attempt on an expired access token.
  if (res.status === 401 && !_retried && path !== "/auth/refresh") {
    const refreshed = await fetch("/api/auth/refresh", {
      method: "POST",
      credentials: "include",
    });
    if (refreshed.ok) {
      return apiFetch(path, init, true);
    }
  }
  return res;
}
