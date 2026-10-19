// Adapted from shadcn/ui (MIT). See public/THIRD_PARTY_NOTICES.txt.
import type { ComponentProps } from 'react'
import { cn } from '@/lib/utils'

export function Badge({ className, ...props }: ComponentProps<'span'>) {
  return <span data-slot="badge" className={cn('inline-flex items-center gap-2 rounded-full border border-violet-400/20 bg-violet-400/[.07] px-3 py-1 text-xs font-medium text-violet-200', className)} {...props}/>
}
