const DEFAULT_API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000/api";

let cachedInvoke = null;
let cachedApiBase = null;

export function isDesktopRuntime() {
  return typeof window !== "undefined" && Boolean(window.__TAURI_INTERNALS__);
}

async function resolveInvoke() {
  if (cachedInvoke) return cachedInvoke;
  if (!isDesktopRuntime()) return null;

  try {
    const mod = await import("@tauri-apps/api/core");
    cachedInvoke = mod.invoke;
    return cachedInvoke;
  } catch {
    return null;
  }
}

export async function getApiBase() {
  if (cachedApiBase) return cachedApiBase;

  const invoke = await resolveInvoke();
  if (!invoke) {
    cachedApiBase = DEFAULT_API_BASE;
    return cachedApiBase;
  }

  try {
    const value = await invoke("get_api_base");
    if (typeof value === "string" && value.trim()) {
      cachedApiBase = value.trim();
      return cachedApiBase;
    }
  } catch {
    // fallback below
  }

  cachedApiBase = DEFAULT_API_BASE;
  return cachedApiBase;
}

export async function openInChrome(url) {
  const invoke = await resolveInvoke();
  if (invoke) {
    await invoke("open_in_chrome", { url });
    return;
  }

  if (typeof window !== "undefined") {
    window.open(url, "_blank", "noopener,noreferrer");
  }
}
