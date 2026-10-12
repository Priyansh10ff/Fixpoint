import { API_URL, ApiError } from './api'

/**
 * POST a JSON body and consume a Server-Sent Events response.
 * EventSource only supports GET, so this reads the stream with fetch.
 */
export async function streamEvents(path, body, { signal, onEvent }) {
  let res
  try {
    res = await fetch(`${API_URL}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify(body),
      signal,
    })
  } catch (err) {
    if (err.name === 'AbortError') throw err
    throw new ApiError(`Backend not reachable at ${API_URL}. Is it running?`, 0)
  }
  if (!res.ok) {
    const data = await res.json().catch(() => null)
    const detail = data?.detail
    const message = Array.isArray(detail) ? detail.map((d) => d.msg).join('; ') : detail || `HTTP ${res.status}`
    throw new ApiError(message, res.status)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let sep
    while ((sep = buffer.indexOf('\n\n')) !== -1) {
      const block = buffer.slice(0, sep)
      buffer = buffer.slice(sep + 2)
      let event = 'message'
      const data = []
      for (const line of block.split('\n')) {
        if (line.startsWith(':')) continue // heartbeat
        if (line.startsWith('event: ')) event = line.slice(7)
        else if (line.startsWith('data: ')) data.push(line.slice(6))
      }
      if (data.length) onEvent(event, JSON.parse(data.join('\n')))
    }
  }
}
