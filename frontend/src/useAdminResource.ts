import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { ApiError } from './api'

type Loader<T> = (signal?: AbortSignal) => Promise<T>
type Operation = 'read' | 'write' | 'background'
interface ActiveRequest { operation: Operation; controller: AbortController }
interface ResourceState<T> {
  loader: Loader<T>
  data: T | null
  error: string
  operation: Operation | null
  updatedAt: Date | null
}

/** Component-local protected data. Memoize loader by session and selection. */
export function useAdminResource<T>(loader: Loader<T>, onUnauthorized: () => void,
  deniedMessage = 'Access denied. Admin access is required for this section.') {
  const [state, setState] = useState<ResourceState<T>>({
    loader, data: null, error: '', operation: 'read', updatedAt: null,
  })
  const scopeRef = useRef<{ loader: Loader<T>; active: ActiveRequest | null } | null>(null)
  const unauthorizedRef = useRef(onUnauthorized)

  useLayoutEffect(() => { unauthorizedRef.current = onUnauthorized }, [onUnauthorized])
  useLayoutEffect(() => {
    // Invalidate before paint on a session/selection change, including A -> B -> A.
    const scope: NonNullable<typeof scopeRef.current> = { loader, active: null }
    scopeRef.current = scope
    return () => {
      scopeRef.current = null
      if (scope.active?.operation !== 'write') scope.active?.controller.abort()
    }
  }, [loader])

  const run = useCallback(async (request: Loader<T>, operation: Operation): Promise<boolean> => {
    const scope = scopeRef.current
    if (!scope || scope.loader !== loader) return false
    if (scope.active) {
      if (operation === 'background' || scope.active.operation !== 'background') return false
      // User actions supersede a poll. Never cancel an in-flight mutation.
      scope.active.controller.abort()
    }
    const active = { operation, controller: new AbortController() }
    scope.active = active
    const current = () => scopeRef.current === scope && scope.active === active
    setState(previous => ({
      loader,
      data: previous.loader === loader ? previous.data : null,
      updatedAt: previous.loader === loader ? previous.updatedAt : null,
      // Keep a refresh warning visible through retries rather than flashing it.
      error: operation === 'background' && previous.loader === loader ? previous.error : '', operation,
    }))
    try {
      const data = await request(active.controller.signal)
      if (!current()) return false
      setState({ loader, data, error: '', operation: null, updatedAt: new Date() })
      return true
    } catch (err) {
      if (!current()) return false
      const denied = err instanceof ApiError && (err.status === 401 || err.status === 403)
      const error = err instanceof ApiError && err.status === 403
        ? deniedMessage
        : err instanceof Error ? err.message : 'Request failed'
      setState(previous => ({
        ...previous, error, operation: null,
        ...(denied ? { data: null, updatedAt: null } : {}),
      }))
      if (err instanceof ApiError && err.status === 401) unauthorizedRef.current()
      return false
    } finally {
      if (current()) scope.active = null
    }
  }, [loader, deniedMessage])

  const refresh = useCallback(() => run(loader, 'read'), [loader, run])
  const refreshInBackground = useCallback(() => run(loader, 'background'), [loader, run])
  // Foreground reads/writes serialize; superseded polls cannot replace a save.
  const save = useCallback((request: Loader<T>) => run(request, 'write'), [run])
  useEffect(() => { void refresh() }, [refresh])

  const visible = state.loader === loader
  const data = visible ? state.data : null
  const error = visible ? state.error : ''
  const loading = !visible || state.operation === 'read'
  const saving = visible && state.operation === 'write'
  return {
    // Background reads do not put controls into a disabled/loading state.
    data, error, loading, saving, pending: loading || saving,
    backgroundRefreshing: visible && state.operation === 'background',
    stale: data !== null && error !== '',
    updatedAt: visible ? state.updatedAt : null,
    refresh, refreshInBackground, save,
  }
}
