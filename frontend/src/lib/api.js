export const API_URL = (import.meta.env.VITE_API_URL || 'http://localhost:8000').replace(/\/$/, '')

export class ApiError extends Error {
  constructor(message, status) {
    super(message)
    this.status = status
  }
}

async function request(path, { method = 'GET', body, signal } = {}) {
  let res
  try {
    res = await fetch(`${API_URL}${path}`, {
      method,
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
      signal,
    })
  } catch (err) {
    if (err.name === 'AbortError') throw err
    throw new ApiError(`Backend not reachable at ${API_URL}. Is it running?`, 0)
  }
  const data = await res.json().catch(() => null)
  if (!res.ok) {
    const detail = data?.detail
    const message = Array.isArray(detail)
      ? detail.map((d) => d.msg).join('; ')
      : detail || `Request failed with HTTP ${res.status}`
    throw new ApiError(message, res.status)
  }
  return data
}

export const api = {
  health: (signal) => request('/api/health', { signal }),
  providers: (signal) => request('/api/providers', { signal }),
  run: (payload, signal) => request('/api/run', { method: 'POST', body: payload, signal }),
  test: (payload, signal) => request('/api/test', { method: 'POST', body: payload, signal }),
  explain: (payload, signal) => request('/api/explain', { method: 'POST', body: payload, signal }),
}
