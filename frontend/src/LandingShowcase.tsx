import { useState } from 'react'
import { ArrowUp, BookOpen, Check, ChevronDown, FileText, FolderOpen, Layers, MessageSquareText, Plus, ShieldCheck } from 'lucide-react'
import { Card } from './components/ui/card'

const examples = [
  {
    label: 'Onboarding', collection: 'People & operations', question: 'How do we welcome a new teammate?',
    intro: 'Start with the essentials, then help them find their feet.',
    steps: ['Set up their workspace and account access.', 'Introduce their team and onboarding buddy.', 'Walk through the first-week checklist together.'],
    file: 'Team handbook.pdf', page: 12, heading: 'A great first week',
    excerpt: 'Every new teammate is paired with an onboarding buddy. Before their first day, prepare workspace access and share the first-week checklist.',
    secondary: 'The team lead introduces the new starter to their colleagues and schedules a welcome conversation.',
  },
  {
    label: 'Operations', collection: 'Operations', question: 'What goes into a project handover?',
    intro: 'Give the next owner the context they need to keep moving.',
    steps: ['Record the current project status and open decisions.', 'Link the working documents and key contacts.', 'Agree on the next steps with the incoming owner.'],
    file: 'Operations guide.pdf', page: 7, heading: 'A thoughtful handover',
    excerpt: 'A project handover includes the current status, open decisions, links to working documents, and the people responsible for the next steps.',
    secondary: 'Review the handover with the incoming owner so that responsibilities and immediate priorities are clear.',
  },
] as const

/** Entirely local, fictional examples. Never mounts authenticated chat or PDF APIs. */
export default function LandingShowcase() {
  const [exampleIndex, setExampleIndex] = useState(0)
  const [sourceOpen, setSourceOpen] = useState(true)
  const example = examples[exampleIndex]

  return <figure className="landing-showcase" aria-label="Interactive example of the KnowledgeBase workspace">
    <div className="landing-preview-toolbar">
      <div className="flex items-center gap-1.5" aria-hidden="true"><i/><i/><i/></div>
      <span className="flex items-center gap-2"><ShieldCheck size={12} aria-hidden="true"/> Your knowledge workspace</span>
      <span className="landing-preview-label">Example</span>
    </div>
    <div className="landing-preview-layout">
      <aside className="landing-preview-sidebar" aria-label="Example workspace overview">
        <div className="flex items-center gap-2.5 font-semibold text-white"><Layers size={18} className="text-violet-300" aria-hidden="true"/> KnowledgeBase</div>
        <div className="mt-8 space-y-2 text-xs">
          <div className="landing-preview-nav-active"><MessageSquareText size={15} aria-hidden="true"/> Assistant</div>
          <div><FolderOpen size={15} aria-hidden="true"/> Documents</div>
          <div><BookOpen size={15} aria-hidden="true"/> Knowledge bases</div>
        </div>
        <p className="mt-9 text-[10px] font-medium uppercase tracking-widest text-slate-500">Your collections</p>
        <div className="mt-4 space-y-3 text-xs text-slate-400"><p><span className="landing-collection-dot bg-violet-400"/>People & operations</p><p><span className="landing-collection-dot bg-teal-400"/>Product knowledge</p><p><span className="landing-collection-dot bg-amber-300"/>Team resources</p></div>
        <div className="mt-auto flex items-center gap-2 border-t border-white/10 pt-5 text-[10px] text-slate-400"><ShieldCheck size={13} aria-hidden="true"/> Permission-aware retrieval</div>
      </aside>
      <div className="landing-preview-chat">
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4 text-xs sm:px-7">
          <span className="font-semibold text-slate-800">Knowledge Assistant</span><span className="flex items-center gap-1.5 text-slate-500"><BookOpen size={12} aria-hidden="true"/>{example.collection}<ChevronDown size={12} aria-hidden="true"/></span>
        </div>
        <div className="landing-preview-conversation">
          <div className="mb-7 flex justify-end"><p className="max-w-[95%] rounded-2xl rounded-tr-sm bg-[#ece9ff] px-4 py-3 text-[13px] leading-6 text-slate-800">{example.question}</p></div>
          <div className="mb-4 flex items-center gap-2 text-[11px] font-semibold text-slate-500"><span className="grid size-6 place-items-center rounded-md bg-violet-100 text-violet-600"><Layers size={13} aria-hidden="true"/></span> KNOWLEDGEBASE</div>
          <p className="text-[13px] leading-6 text-slate-700">{example.intro}</p>
          <ol className="my-4 space-y-2.5 text-[13px] leading-6 text-slate-700">
            {example.steps.map((step, index) => <li key={step} className="flex gap-2.5"><span className="font-medium text-violet-600">0{index + 1}</span><span>{step}</span></li>)}
          </ol>
          <button type="button" className="landing-preview-citation" aria-expanded={sourceOpen} aria-controls="landing-example-source" onClick={() => setSourceOpen(value => !value)}>
            <FileText size={13} aria-hidden="true"/><span>{example.file}</span><span className="text-slate-500">p. {example.page}</span><span className="citation">[1]</span>
            <span className="sr-only">{sourceOpen ? 'Hide example source' : 'View example source'}</span>
          </button>
          <p className="mt-4 flex items-center gap-1.5 text-[10px] text-slate-500"><Check size={12} className="text-teal-600" aria-hidden="true"/> Grounded in your selected knowledge base</p>
          <div className="landing-preview-composer" aria-hidden="true"><Plus size={15}/><span>Ask a follow-up question…</span><span className="ml-auto grid size-7 place-items-center rounded-lg bg-violet-600 text-white"><ArrowUp size={15}/></span></div>
        </div>
      </div>
      <div id="landing-example-source" hidden={!sourceOpen} className="landing-preview-source" role="region" aria-label="Example PDF source">
        <div className="mb-5 flex items-center gap-2 text-[11px] text-slate-500"><FileText size={14} aria-hidden="true"/><span className="font-medium text-slate-700">Source document</span><span className="ml-auto">{example.page} / 24</span></div>
        <Card className="landing-preview-paper">
          <p className="text-[9px] uppercase tracking-[.16em] text-slate-500">{example.file}</p>
          <div className="mb-5 mt-3 h-px bg-slate-200"/>
          <p className="mb-3 text-[9px] font-medium uppercase tracking-widest text-violet-600">People, process & practice</p>
          <h3 className="text-xl font-semibold tracking-tight text-slate-900">{example.heading}</h3>
          <p className="mt-5 text-[11px] leading-[1.9] text-slate-600"><mark className="bg-violet-100 px-0.5 text-slate-800">{example.excerpt}</mark></p>
          <p className="mt-5 text-[11px] leading-[1.9] text-slate-500">{example.secondary}</p>
          <div className="mt-8 border-t border-slate-200 pt-3 text-center text-[9px] text-slate-400">{example.page}</div>
        </Card>
        <p className="mt-4 flex items-center justify-center gap-1.5 text-[10px] text-violet-700"><span className="size-1.5 rounded-full bg-violet-500"/> The evidence, right beside the answer.</p>
      </div>
    </div>
    <figcaption className="landing-preview-caption">
      <span>Explore an example</span>
      <div className="flex gap-1" role="group" aria-label="Example questions">{examples.map((item, index) => <button type="button" key={item.label} aria-pressed={index === exampleIndex} onClick={() => {setExampleIndex(index); setSourceOpen(true)}}>{item.label}</button>)}</div>
      <span className="landing-preview-disclaimer">Fictional content · no live documents</span>
    </figcaption>
  </figure>
}
