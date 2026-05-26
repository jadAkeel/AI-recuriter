const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api/v1';

function resolveApiBaseUrl(): URL {
  return new URL(API_BASE_URL, window.location.origin);
}

function resolveWebSocketApiBase(): string {
  const url = resolveApiBaseUrl();
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  return url.toString().replace(/\/$/, '');
}

export const WS_API_BASE = resolveWebSocketApiBase();

export function buildApiWebSocketUrl(path: string): string {
  const normalizedPath = path.startsWith('/') ? path : `/${path}`;
  return `${WS_API_BASE}${normalizedPath}`;
}

export function buildAuthenticatedWebSocketUrl(path: string): string {
  const token = localStorage.getItem('access_token');
  const url = new URL(buildApiWebSocketUrl(path));
  if (token) {
    url.searchParams.set('token', token);
  }
  return url.toString();
}
