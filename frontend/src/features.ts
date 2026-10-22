// Public build-time switches only; authorization remains enforced by FastAPI.
export function creditsEnabled(): boolean {
  return import.meta.env.VITE_CREDITS_ENABLED === 'true'
}
