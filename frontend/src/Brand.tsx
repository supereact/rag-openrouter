import { Layers } from 'lucide-react'

export default function Brand({ compact = false }: { compact?: boolean }) {
  return <div className="flex items-center gap-3">
    <div className="brand-mark"><Layers size={19} strokeWidth={2.3} aria-hidden="true"/></div>
    {!compact && <div><div className="font-bold tracking-tight text-white leading-tight">KnowledgeBase</div>
      <div className="text-[11px] tracking-[.14em] uppercase text-slate-400 mt-0.5">Enterprise RAG</div></div>}
  </div>
}
