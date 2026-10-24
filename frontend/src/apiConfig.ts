export function apiEndpoint(path: string): string {
  const base = (import.meta.env.VITE_API_BASE_URL || '/api').trim().replace(/\/+$/, '')
  // Preserve the existing local development/rehearsal proxy when unset.
  if (base === '/api') return `${base}${path}`
  try {
    const url = new URL(base)
    const local = ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname)
    if ((url.protocol !== 'https:' && !(url.protocol === 'http:' && local))
      || url.username || url.password || url.search || url.hash) throw new Error()
    return `${url.origin}${url.pathname.replace(/\/+$/, '')}${path}`
  } catch {
    throw new Error('VITE_API_BASE_URL must be an HTTPS backend URL, or HTTP on localhost.')
  }
}
