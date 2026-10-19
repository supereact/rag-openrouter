import { useEffect } from 'react'

/** Small polling loop for mounted views; pauses when hidden/offline. */
export function useVisiblePolling(refresh: () => Promise<boolean>, interval = 3000) {
  useEffect(() => {
    const tick = () => {
      if (document.visibilityState === 'visible' && navigator.onLine) void refresh()
    }
    const timer = window.setInterval(tick, interval)
    document.addEventListener('visibilitychange', tick)
    window.addEventListener('online', tick)
    return () => {
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', tick)
      window.removeEventListener('online', tick)
    }
  }, [refresh, interval])
}
