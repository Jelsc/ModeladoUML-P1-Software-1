export const API = '/api';
export const AUTH_EXPIRED_EVENT = 'uml:auth-expired';
export const DIAGRAMS_REFRESH_EVENT = 'uml:diagrams-refresh';
export function notifyAuthExpired() {
  localStorage.removeItem('token');
  window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT));
}
function formatValidationError(detail) {
  if (Array.isArray(detail)) {
    const messages = detail.map(item => {
      if (!item || typeof item !== 'object') return String(item);
      const location = Array.isArray(item.loc) ? item.loc.filter(Boolean).join('.') : '';
      return location ? `${location}: ${item.msg || 'Valor no válido'}` : (item.msg || 'Valor no válido');
    }).filter(Boolean);
    if (messages.length) return messages.join('; ');
  }
  if (typeof detail === 'string' && detail.trim()) return detail;
  if (detail && typeof detail === 'object') {
    try { return JSON.stringify(detail); } catch { return 'El servidor devolvió un error de validación ilegible.'; }
  }
  return 'La solicitud falló. Revise los valores enviados e intente nuevamente.';
}
export async function request(path, options = {}) {
  const detailPath = path.match(/^\/(attributes|methods)\/(.+)$/);
  if (detailPath) path = `/details/${detailPath[1]}/${detailPath[2]}`;
  const token = localStorage.getItem('token');
  const headers = { ...(options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }), ...(token ? { Authorization: `Bearer ${token}` } : {}) };
  const response = await fetch(API + path, { ...options, headers: { ...headers, ...(options.headers || {}) } });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = body.detail ?? body;
    const expired = token && (response.status === 401 || (typeof detail === 'string' && /token|sesión|session|jwt/i.test(detail) && /expir|invalid|venc/i.test(detail)));
    if (expired) {
      notifyAuthExpired();
      const error = Error('La sesión expiró. Inicie sesión nuevamente.');
      error.status = response.status;
      error.authExpired = true;
      throw error;
    }
    const error = Error(formatValidationError(detail)); error.status = response.status; throw error;
  }
  const contentType = response.headers.get('content-type') || '';
  return contentType.includes('zip') || contentType.includes('xml') || contentType.includes('octet-stream') ? response.blob() : response.json();
}
export const json = (method, body) => ({ method, body: JSON.stringify(body) });
