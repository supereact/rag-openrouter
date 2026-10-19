// Adapted from Magic UI's Border Beam (MIT). See public/THIRD_PARTY_NOTICES.txt.
// https://magicui.design/docs/components/border-beam
import { m, useReducedMotion } from 'motion/react'

export function BorderBeam({ active = true }: { active?: boolean }) {
  const reducedMotion = useReducedMotion()
  if (reducedMotion || !active) return null
  return <div className="landing-beam" aria-hidden="true">
    <m.div className="landing-beam-light"
      style={{ offsetPath: 'rect(0 auto auto 0 round 20px)' }}
      initial={{ offsetDistance: '0%' }} animate={{ offsetDistance: '100%' }}
      transition={{ duration: 4, ease: 'linear' }}/>
  </div>
}
