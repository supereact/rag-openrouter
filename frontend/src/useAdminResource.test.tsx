import { StrictMode } from 'react'
import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from './api'
import { useAdminResource } from './useAdminResource'

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

afterEach(cleanup)

describe('component-local admin requests', () => {
  it('deduplicates quiet polls without disabling foreground controls', async () => {
    const poll = deferred<string>()
    const loader = vi.fn<(_: AbortSignal | undefined) => Promise<string>>()
      .mockResolvedValueOnce('initial').mockReturnValueOnce(poll.promise)
    const { result } = renderHook(() => useAdminResource(loader, vi.fn()))
    await waitFor(() => expect(result.current.data).toBe('initial'))
    act(() => { void result.current.refreshInBackground() })
    expect(result.current.backgroundRefreshing).toBe(true)
    expect(result.current.pending).toBe(false)
    expect(result.current.loading).toBe(false)
    expect(result.current.data).toBe('initial')
    await act(async () => { expect(await result.current.refreshInBackground()).toBe(false) })
    expect(loader).toHaveBeenCalledTimes(2)
    await act(async () => { poll.resolve('latest') })
    expect(result.current.data).toBe('latest')
    expect(result.current.backgroundRefreshing).toBe(false)
  })

  it('prioritizes a save over a poll and ignores its late response', async () => {
    const poll = deferred<string>()
    const write = deferred<string>()
    const loader = vi.fn<(_: AbortSignal | undefined) => Promise<string>>()
      .mockResolvedValueOnce('initial').mockReturnValueOnce(poll.promise)
    const { result } = renderHook(() => useAdminResource(loader, vi.fn()))
    await waitFor(() => expect(result.current.data).toBe('initial'))
    act(() => { void result.current.refreshInBackground() })
    const signal = loader.mock.calls[1][0]!
    const mutation = vi.fn(() => write.promise)
    act(() => { void result.current.save(mutation) })
    expect(signal.aborted).toBe(true)
    expect(mutation).toHaveBeenCalledOnce()
    expect(result.current.saving).toBe(true)
    await act(async () => { expect(await result.current.refreshInBackground()).toBe(false) })
    await act(async () => { write.resolve('saved') })
    await act(async () => { poll.resolve('obsolete') })
    expect(result.current.data).toBe('saved')
    expect(result.current.error).toBe('')
    expect(loader).toHaveBeenCalledTimes(2)
  })

  it('allows manual refresh to cancel a poll without exposing its cancellation error', async () => {
    const poll = deferred<string>()
    const loader = vi.fn<(_: AbortSignal | undefined) => Promise<string>>()
      .mockResolvedValueOnce('initial').mockReturnValueOnce(poll.promise).mockResolvedValue('manual')
    const unauthorized = vi.fn()
    const { result } = renderHook(() => useAdminResource(loader, unauthorized))
    await waitFor(() => expect(result.current.data).toBe('initial'))
    act(() => { void result.current.refreshInBackground() })
    const signal = loader.mock.calls[1][0]!
    await act(async () => { await result.current.refresh() })
    expect(signal.aborted).toBe(true)
    await act(async () => { poll.reject(new ApiError(401, 'Obsolete request')) })
    expect(result.current.data).toBe('manual')
    expect(result.current.error).toBe('')
    expect(unauthorized).not.toHaveBeenCalled()
  })

  it('retains a background failure warning through retries until recovery', async () => {
    const retry = deferred<string>()
    const loader = vi.fn<() => Promise<string>>().mockResolvedValueOnce('initial')
      .mockRejectedValueOnce(new Error('Offline')).mockReturnValueOnce(retry.promise)
    const { result } = renderHook(() => useAdminResource(loader, vi.fn()))
    await waitFor(() => expect(result.current.data).toBe('initial'))
    await act(async () => { await result.current.refreshInBackground() })
    expect(result.current.stale).toBe(true)
    act(() => { void result.current.refreshInBackground() })
    expect(result.current.error).toBe('Offline')
    expect(result.current.stale).toBe(true)
    await act(async () => { retry.resolve('recovered') })
    expect(result.current.error).toBe('')
    expect(result.current.stale).toBe(false)
  })

  it.each([401, 403])('clears protected content on a background HTTP %i', async status => {
    const loader = vi.fn<() => Promise<string>>().mockResolvedValueOnce('protected')
      .mockRejectedValueOnce(new ApiError(status, 'Denied'))
    const unauthorized = vi.fn()
    const { result } = renderHook(() => useAdminResource(loader, unauthorized))
    await waitFor(() => expect(result.current.data).toBe('protected'))
    await act(async () => { await result.current.refreshInBackground() })
    expect(result.current.data).toBeNull()
    expect(unauthorized).toHaveBeenCalledTimes(status === 401 ? 1 : 0)
  })

  it('aborts an old background read after selection/session changes and on unmount', async () => {
    const poll = deferred<string>()
    const first = vi.fn<(_: AbortSignal | undefined) => Promise<string>>()
      .mockResolvedValueOnce('initial').mockReturnValueOnce(poll.promise)
    const second = vi.fn<(_: AbortSignal | undefined) => Promise<string>>(() => new Promise(() => {}))
    const { result, rerender, unmount } = renderHook(({ loader }) => useAdminResource(loader, vi.fn()), {
      initialProps: {loader: first},
    })
    await waitFor(() => expect(result.current.data).toBe('initial'))
    act(() => { void result.current.refreshInBackground() })
    const oldSignal = first.mock.calls[1][0]!
    rerender({loader: second})
    expect(oldSignal.aborted).toBe(true)
    expect(result.current.data).toBeNull()
    await act(async () => { poll.resolve('obsolete') })
    expect(result.current.data).toBeNull()
    unmount()
    expect(second.mock.calls[0][0]!.aborted).toBe(true)
  })

  it('loads once and prevents duplicate refreshes while a read is pending', async () => {
    const request = deferred<string>()
    const loader = vi.fn(() => request.promise)
    const { result } = renderHook(() => useAdminResource(loader, vi.fn()))
    expect(result.current.loading).toBe(true)
    expect(result.current.data).toBeNull()
    await act(async () => { await Promise.all([result.current.refresh(), result.current.refresh()]) })
    expect(loader).toHaveBeenCalledTimes(1)
    await act(async () => { request.resolve('loaded') })
    expect(result.current.data).toBe('loaded')
    expect(result.current.pending).toBe(false)
    expect(result.current.updatedAt).toBeInstanceOf(Date)
  })

  it('retains successful data and its timestamp after refresh failure, then retries', async () => {
    const loader = vi.fn<() => Promise<string>>().mockResolvedValue('initial')
    const { result } = renderHook(() => useAdminResource(loader, vi.fn()))
    await waitFor(() => expect(result.current.data).toBe('initial'))
    const timestamp = result.current.updatedAt
    const request = deferred<string>()
    loader.mockReturnValueOnce(request.promise)
    act(() => { void result.current.refresh() })
    expect(result.current.loading).toBe(true)
    expect(result.current.data).toBe('initial')
    await act(async () => { request.reject(new Error('Offline')) })
    expect(result.current.error).toBe('Offline')
    expect(result.current.stale).toBe(true)
    expect(result.current.updatedAt).toBe(timestamp)
    loader.mockResolvedValueOnce('recovered')
    await act(async () => { await result.current.refresh() })
    expect(result.current.data).toBe('recovered')
    expect(result.current.error).toBe('')
    expect(result.current.stale).toBe(false)
  })

  it('clears previous selection data and ignores out-of-order responses', async () => {
    const older = deferred<string>()
    const newer = deferred<string>()
    const first = vi.fn().mockResolvedValueOnce('initial').mockReturnValueOnce(older.promise)
    const second = vi.fn(() => newer.promise)
    const { result, rerender } = renderHook(({ loader }) => useAdminResource(loader, vi.fn()), {
      initialProps: { loader: first },
    })
    await waitFor(() => expect(result.current.data).toBe('initial'))
    act(() => { void result.current.refresh() })
    rerender({ loader: second })
    expect(result.current.data).toBeNull()
    expect(result.current.updatedAt).toBeNull()
    await act(async () => { newer.resolve('new selection') })
    await act(async () => { older.resolve('obsolete') })
    expect(result.current.data).toBe('new selection')
    expect(result.current.error).toBe('')
  })

  it('ignores an obsolete 401 after changing sessions', async () => {
    const older = deferred<string>()
    const first = () => older.promise
    const second = () => Promise.resolve('new tenant')
    const unauthorized = vi.fn()
    const { result, rerender } = renderHook(({ loader }) => useAdminResource(loader, unauthorized), {
      initialProps: { loader: first },
    })
    rerender({ loader: second })
    await waitFor(() => expect(result.current.data).toBe('new tenant'))
    await act(async () => { older.reject(new ApiError(401, 'Expired old session')) })
    expect(unauthorized).not.toHaveBeenCalled()
    expect(result.current.data).toBe('new tenant')
  })

  it.each([401, 403])('clears protected data on HTTP %i', async status => {
    const loader = vi.fn<() => Promise<string>>().mockResolvedValue('protected')
    const unauthorized = vi.fn()
    const { result } = renderHook(() => useAdminResource(loader, unauthorized))
    await waitFor(() => expect(result.current.data).toBe('protected'))
    loader.mockRejectedValueOnce(new ApiError(status, 'Denied'))
    await act(async () => { await result.current.refresh() })
    expect(result.current.data).toBeNull()
    expect(result.current.updatedAt).toBeNull()
    expect(result.current.stale).toBe(false)
    expect(unauthorized).toHaveBeenCalledTimes(status === 401 ? 1 : 0)
    expect(result.current.error).toMatch(status === 403 ? /Access denied/ : /Denied/)
  })

  it.each(['resolve', 'reject'] as const)('ignores a request that completes after unmount: %s', async outcome => {
    const request = deferred<string>()
    const unauthorized = vi.fn()
    const loader = () => request.promise
    const { unmount } = renderHook(() => useAdminResource(loader, unauthorized))
    unmount()
    await act(async () => {
      if (outcome === 'resolve') request.resolve('obsolete')
      else request.reject(new ApiError(401, 'Expired'))
    })
    expect(unauthorized).not.toHaveBeenCalled()
  })

  it('uses the latest unauthorized callback without refetching', async () => {
    const loader = vi.fn<() => Promise<string>>().mockResolvedValue('loaded')
    const first = vi.fn()
    const second = vi.fn()
    const { result, rerender } = renderHook(({ callback }) => useAdminResource(loader, callback), {
      initialProps: { callback: first },
    })
    await waitFor(() => expect(result.current.data).toBe('loaded'))
    rerender({ callback: second })
    expect(loader).toHaveBeenCalledTimes(1)
    loader.mockRejectedValueOnce(new ApiError(401, 'Expired'))
    await act(async () => { await result.current.refresh() })
    expect(first).not.toHaveBeenCalled()
    expect(second).toHaveBeenCalledOnce()
  })

  it('serializes reads and writes and applies a save response without a GET', async () => {
    const initial = deferred<string>()
    const write = deferred<string>()
    const loader = vi.fn(() => initial.promise)
    const mutation = vi.fn(() => write.promise)
    const { result } = renderHook(() => useAdminResource(loader, vi.fn()))
    await act(async () => { expect(await result.current.save(mutation)).toBe(false) })
    expect(mutation).not.toHaveBeenCalled()
    await act(async () => { initial.resolve('initial') })
    act(() => { void result.current.save(mutation) })
    expect(result.current.saving).toBe(true)
    expect(result.current.loading).toBe(false)
    await act(async () => {
      expect(await result.current.refresh()).toBe(false)
      expect(await result.current.save(mutation)).toBe(false)
    })
    expect(loader).toHaveBeenCalledTimes(1)
    expect(mutation).toHaveBeenCalledTimes(1)
    await act(async () => { write.resolve('saved') })
    expect(result.current.data).toBe('saved')
    expect(result.current.pending).toBe(false)
  })

  it('rejects a save result from a previous session', async () => {
    const write = deferred<string>()
    const first = () => Promise.resolve('first tenant')
    const second = () => Promise.resolve('second tenant')
    const { result, rerender } = renderHook(({ loader }) => useAdminResource(loader, vi.fn()), {
      initialProps: { loader: first },
    })
    await waitFor(() => expect(result.current.data).toBe('first tenant'))
    let saved!: Promise<boolean>
    act(() => { saved = result.current.save(() => write.promise) })
    rerender({ loader: second })
    await waitFor(() => expect(result.current.data).toBe('second tenant'))
    await act(async () => {
      write.resolve('obsolete save')
      expect(await saved).toBe(false)
    })
    expect(result.current.data).toBe('second tenant')
  })

  it('ignores the first StrictMode request even when its loader is identical', async () => {
    const older = deferred<string>()
    const loader = vi.fn().mockReturnValueOnce(older.promise).mockResolvedValue('current')
    const { result } = renderHook(() => useAdminResource(loader, vi.fn()), { wrapper: StrictMode })
    await waitFor(() => expect(result.current.data).toBe('current'))
    await act(async () => { older.resolve('obsolete') })
    expect(result.current.data).toBe('current')
  })
})
