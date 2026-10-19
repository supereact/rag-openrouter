// Adapted from shadcn/ui (MIT). See public/THIRD_PARTY_NOTICES.txt.
import type { ComponentProps } from 'react'
import { cn } from '@/lib/utils'

export function Card({ className, ...props }: ComponentProps<'div'>) {
  return <div data-slot="card" className={cn('rounded-2xl border border-white/10 bg-white/[.025]', className)} {...props}/>
}
