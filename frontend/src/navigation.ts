import { useEffect, useState, type MouseEvent } from 'react'

export const routes = ['/assistant', '/documents', '/dashboard', '/users', '/knowledge-bases', '/audit-log', '/credits'] as const
export function returnDestination(value: string | null): string {
  if (!value || !value.startsWith('/') || value.startsWith('//')) return '/assistant'
  const url = new URL(value, window.location.origin)
  return url.origin === window.location.origin && routes.some(route => route === url.pathname)
    ? url.pathname + url.search : '/assistant'
}
export function navigate(to: string, replace = false) {
  if (!replace && window.location.pathname + window.location.search === to) return
  window.history[replace ? 'replaceState' : 'pushState']({}, '', to)
  window.dispatchEvent(new Event('app-navigation'))
}
export function followLink(event: MouseEvent<HTMLAnchorElement>) {
  if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
  event.preventDefault()
  navigate(event.currentTarget.pathname + event.currentTarget.search)
}
export function useLocation() {
  const [location, setLocation] = useState(() => window.location.pathname + window.location.search)
  useEffect(() => {
    const update = () => setLocation(window.location.pathname + window.location.search)
    window.addEventListener('popstate', update)
    window.addEventListener('app-navigation', update)
    return () => { window.removeEventListener('popstate', update); window.removeEventListener('app-navigation', update) }
  }, [])
  return location
}
