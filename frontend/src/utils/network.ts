const WS_PROTOCOL = window.location.protocol === 'https:' ? 'wss' : 'ws';

export const WS_API_BASE = `${WS_PROTOCOL}://${window.location.host}/api/v1`;

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
