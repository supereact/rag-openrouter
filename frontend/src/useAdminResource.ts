import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { ApiError } from './api'

type Loader<T> = () => Promise<T>
type Operation = 'read' | 'write' | null
interface ResourceState<T> {
  loader: Loader<T>
  data: T | null
  error: string
  operation: Operation
  updatedAt: Date | null
}

/** Component-local protected data. Memoize loader by session and selection. */
export function useAdminResource<T>(loader: Loader<T>, onUnauthorized: () => void,
  deniedMessage = 'Access denied. Admin access is required for this section.') {
  const [state, setState] = useState<ResourceState<T>>({
    loader, data: null, error: '', operation: 'read', updatedAt: null,
  })
  const scopeRef = useRef<{ loader: Loader<T>; pending: boolean } | null>(null)
  const unauthorizedRef = useRef(onUnauthorized)

  useLayoutEffect(() => { unauthorizedRef.current = onUnauthorized }, [onUnauthorized])
  useLayoutEffect(() => {
    // Invalidate before paint on a session/selection change, including A -> B -> A.
    const scope = { loader, pending: false }
    scopeRef.current = scope
    return () => { scopeRef.current = null }
  }, [loader])

  const run = useCallback(async (request: Loader<T>, operation: Operation): Promise<boolean> => {
    const scope = scopeRef.current
    if (!scope || scope.loader !== loader || scope.pending) return false
    scope.pending = true
    const current = () => scopeRef.current === scope
    setState(previous => ({
      loader,
      data: previous.loader === loader ? previous.data : null,
      updatedAt: previous.loader === loader ? previous.updatedAt : null,
      error: '', operation,
    }))
    try {
      const data = await request()
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
      if (current()) scope.pending = false
    }
  }, [loader, deniedMessage])

  const refresh = useCallback(() => run(loader, 'read'), [loader, run])
  // Serializing reads and writes also prevents a pre-save GET from replacing a PUT response.
  const save = useCallback((request: Loader<T>) => run(request, 'write'), [run])
  useEffect(() => { void refresh() }, [refresh])

  const visible = state.loader === loader
  const data = visible ? state.data : null
  const error = visible ? state.error : ''
  const loading = !visible || state.operation === 'read'
  const saving = visible && state.operation === 'write'
  return {
    data, error, loading, saving, pending: loading || saving,
    stale: data !== null && error !== '',
    updatedAt: visible ? state.updatedAt : null,
    refresh, save,
  }
}
