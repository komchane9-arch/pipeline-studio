// Shared by the desktop library and the dedicated mobile page; no desktop UI side effects.
export const CLIP_API = `${location.origin}/clip-api`;
export async function api(url, options = {}) {
  let token = '';
  try { token = localStorage.getItem('pipelineStudioToken') || ''; } catch {}
  const response = await fetch(url, { ...options, headers: {
    'Content-Type': 'application/json', ...(token ? { 'x-device-token': token } : {}),
    ...(options.headers || {}),
  }});
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || 'ดำเนินการไม่สำเร็จ');
  return payload;
}
