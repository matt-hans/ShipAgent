export const BROWSER_CSRF_HEADER = 'X-CSRF-Token';

const BROWSER_SESSION_PATH = '/api/v1/auth/session';
const SAFE_HTTP_METHODS = new Set(['GET', 'HEAD', 'OPTIONS']);

function resolutionBase(): string {
  try {
    const href = globalThis.location?.href;
    if (href) return new URL(href).href;
  } catch {
    // Fall through to a non-routable comparison origin.
  }
  return 'http://shipagent.invalid/';
}

function normalizedUrl(url: string): URL | null {
  try {
    return new URL(url, resolutionBase());
  } catch {
    return null;
  }
}

export function isBrowserSessionFlow(url: string): boolean {
  return (
    normalizedUrl(url)?.pathname.replace(/\/+$/, '') === BROWSER_SESSION_PATH
  );
}

export function isShipAgentApiFlow(url: string, apiBaseUrl: string): boolean {
  const target = normalizedUrl(url);
  const apiBase = normalizedUrl(apiBaseUrl);
  if (
    !target ||
    !apiBase ||
    target.protocol !== apiBase.protocol ||
    target.hostname !== apiBase.hostname ||
    target.port !== apiBase.port
  ) {
    return false;
  }

  const apiPath = apiBase.pathname.replace(/\/+$/, '');
  return (
    target.pathname === apiPath || target.pathname.startsWith(`${apiPath}/`)
  );
}

export function isUnsafeHttpMethod(method: string): boolean {
  return !SAFE_HTTP_METHODS.has(method.toUpperCase());
}
