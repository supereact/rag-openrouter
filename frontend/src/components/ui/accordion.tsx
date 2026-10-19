// Adapted from shadcn/ui (MIT). See public/THIRD_PARTY_NOTICES.txt.
import type { ComponentProps } from 'react'
import * as AccordionPrimitive from '@radix-ui/react-accordion'
import { Plus } from 'lucide-react'
import { cn } from '@/lib/utils'

export const Accordion = AccordionPrimitive.Root

export function AccordionItem({ className, ...props }: ComponentProps<typeof AccordionPrimitive.Item>) {
  return <AccordionPrimitive.Item className={cn('border-b border-white/10', className)} {...props}/>
}

export function AccordionTrigger({ className, children, ...props }: ComponentProps<typeof AccordionPrimitive.Trigger>) {
  return <AccordionPrimitive.Header>
    <AccordionPrimitive.Trigger className={cn('group flex w-full items-center justify-between gap-5 py-6 text-left text-sm font-medium text-slate-100 focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-violet-400 sm:text-base', className)} {...props}>
      {children}<Plus aria-hidden="true" size={18} className="shrink-0 text-slate-400 transition-transform group-data-[state=open]:rotate-45 motion-reduce:transition-none"/>
    </AccordionPrimitive.Trigger>
  </AccordionPrimitive.Header>
}

export function AccordionContent({ className, children, ...props }: ComponentProps<typeof AccordionPrimitive.Content>) {
  return <AccordionPrimitive.Content className="overflow-hidden" {...props}>
    <div className={cn('pb-6 pr-7 text-sm leading-7 text-slate-400', className)}>{children}</div>
  </AccordionPrimitive.Content>
}
