// Adapted from shadcn/ui (MIT). See public/THIRD_PARTY_NOTICES.txt.
import type { ComponentProps } from 'react'
import * as DialogPrimitive from '@radix-ui/react-dialog'
import { X } from 'lucide-react'
import { cn } from '@/lib/utils'

export const Sheet = DialogPrimitive.Root
export const SheetTrigger = DialogPrimitive.Trigger
export const SheetClose = DialogPrimitive.Close
export const SheetTitle = DialogPrimitive.Title
export const SheetDescription = DialogPrimitive.Description

export function SheetContent({ className, children, ...props }: ComponentProps<typeof DialogPrimitive.Content>) {
  return <DialogPrimitive.Portal>
    <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-slate-950/75 backdrop-blur-sm"/>
    <DialogPrimitive.Content className={cn('landing-menu fixed inset-y-0 right-0 z-50 w-[min(22rem,100%)] overflow-y-auto border-l border-white/10 bg-[#0c1225] p-7 text-slate-100 shadow-2xl', className)} {...props}>
      {children}
      <DialogPrimitive.Close className="absolute top-5 right-5 grid size-10 place-items-center rounded-lg text-slate-300 hover:bg-white/10 focus-visible:outline-2 focus-visible:outline-violet-400" aria-label="Close menu">
        <X size={20} aria-hidden="true"/>
      </DialogPrimitive.Close>
    </DialogPrimitive.Content>
  </DialogPrimitive.Portal>
}
