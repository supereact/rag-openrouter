import type { ReactNode } from 'react'

export default function PageFrame({ title, subtitle, actions, children, footer }: {
  title: string; subtitle: string; actions?: ReactNode; children: ReactNode; footer?: ReactNode
}) {
  return <section className="page-frame">
    <header className="workspace-header"><div><h1 className="text-xl sm:text-2xl font-semibold tracking-tight text-slate-900">{title}</h1>
      <p className="text-sm text-slate-500 mt-1">{subtitle}</p></div>{actions}</header>
    <div className="page-content">{children}</div>{footer}
  </section>
}
