import { useEffect, useRef, useState } from 'react'
import { ArrowDown, ArrowRight, BookOpen, Check, CheckCheck, ChevronRight, FileCheck2, FileText, Fingerprint, FolderOpen, Layers, LockKeyhole, Menu, MessageSquareText, Plus, Search, ShieldCheck, Sparkles, Upload } from 'lucide-react'
import { LazyMotion, domAnimation, m, MotionConfig, useInView, useReducedMotion } from 'motion/react'
import Brand from './Brand'
import LandingShowcase from './LandingShowcase'
import { followLink } from './navigation'
import { Button } from './components/ui/button'
import { Badge } from './components/ui/badge'
import { Card } from './components/ui/card'
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from './components/ui/accordion'
import { Sheet, SheetClose, SheetContent, SheetDescription, SheetTitle, SheetTrigger } from './components/ui/sheet'
import { BorderBeam } from './components/magicui/border-beam'
import './landing.css'

const sections = [
  { href: '#product', label: 'Product' }, { href: '#features', label: 'Features' },
  { href: '#how-it-works', label: 'How it works' }, { href: '#security', label: 'Security' },
]

const faqs = [
  ['What does KnowledgeBase actually do?', 'KnowledgeBase helps your team ask questions about the documents they can access. It retrieves relevant passages, uses a language model to draft an answer, and includes sources so people can check the evidence. Answers can still be wrong; review the cited material for important decisions.'],
  ['Which documents can I upload?', 'You can upload PDF, Markdown and TXT files, including multiple files together. Documents are processed in the background. PDFs need extractable text; scanned image-only PDFs may need OCR before uploading.'],
  ['Can I check where an answer came from?', 'Yes. Retrieved sources accompany answers. Page-aware PDF citations let authorized users open the original PDF at the cited physical page. Page numbers follow file order and may differ from printed page labels.'],
  ['Who can see my documents?', 'Access is controlled by your tenant, account role, document ownership and sharing permissions. Putting a document in a knowledge base does not grant access to it. Administrators manage users and permissions within their tenant.'],
  ['Where is document data processed?', 'Embeddings are generated locally. Relevant document excerpts and question context are sent to the configured generation provider, such as OpenRouter, to produce answers. Storage, model selection and provider settings depend on your deployment.'],
  ['How do I get started?', 'Choose Get started to create an account and a private workspace. To join an existing team, enter the invitation code supplied by its administrator. Choose Sign in if you already have an account. An API-key sign-in option is also available.'],
]

function WorkspaceLink({ signedIn, large = false }: { signedIn: boolean; large?: boolean }) {
  return <Button asChild size={large ? 'lg' : 'default'} className="landing-primary">
    <a href={signedIn ? '/assistant' : '/login?mode=register'} onClick={followLink}>{signedIn ? 'Open workspace' : 'Get started'}<ArrowRight aria-hidden="true"/></a>
  </Button>
}

function PrecisionLanding({ signedIn }: { signedIn: boolean }) {
  const [menuOpen, setMenuOpen] = useState(false)
  const [visible, setVisible] = useState(() => document.visibilityState !== 'hidden')
  const reducedMotion = useReducedMotion()
  const productRef = useRef<HTMLDivElement>(null)
  const productInView = useInView(productRef, { margin: '100px' })
  useEffect(() => {
    // Native fragment navigation can run before this lazy page has mounted.
    // Resolve known section links once the actual targets are available.
    const hash = window.location.hash
    if ([...sections.map(item => item.href), '#faq', '#landing-main'].includes(hash)) {
      document.getElementById(hash.slice(1))?.scrollIntoView({ behavior: 'instant', block: 'start' })
    }
  }, [])
  useEffect(() => {
    const update = () => setVisible(document.visibilityState !== 'hidden')
    document.addEventListener('visibilitychange', update)
    return () => document.removeEventListener('visibilitychange', update)
  }, [])
  const entrance = reducedMotion ? {} : {
    initial: { opacity: 0, y: 16 }, animate: { opacity: 1, y: 0 },
    transition: { duration: 0.65, ease: 'easeOut' as const },
  }

  return <div className="landing-page" data-reduced-motion={reducedMotion ? 'true' : 'false'}>
    <a className="landing-skip-link" href="#landing-main">Skip to content</a>
    <header className="landing-header">
      <div className="landing-container flex h-20 items-center justify-between gap-5">
        <a href="#landing-main" aria-label="KnowledgeBase home"><Brand/></a>
        <nav className="landing-desktop-nav" aria-label="Website navigation">{sections.map(item => <a key={item.href} href={item.href}>{item.label}</a>)}</nav>
        <div className="flex items-center gap-2 sm:gap-4">
          {!signedIn && <a href="/login" onClick={followLink} className="landing-sign-in">Sign in</a>}
          <span className="landing-desktop-cta"><WorkspaceLink signedIn={signedIn}/></span>
          <Sheet open={menuOpen} onOpenChange={setMenuOpen}>
            <SheetTrigger asChild><Button variant="ghost" size="icon" className="landing-mobile-trigger" aria-label="Open menu"><Menu aria-hidden="true"/></Button></SheetTrigger>
            <SheetContent>
              <SheetTitle className="text-lg font-semibold">Explore KnowledgeBase</SheetTitle>
              <SheetDescription className="mt-2 max-w-60 text-sm leading-6 text-slate-400">Your team’s knowledge, connected to clear answers.</SheetDescription>
              <nav className="mt-9 flex flex-col gap-2" aria-label="Mobile website navigation">{sections.map(item => <SheetClose asChild key={item.href}><a href={item.href} className="rounded-lg px-3 py-4 text-sm text-slate-300 hover:bg-white/5">{item.label}</a></SheetClose>)}</nav>
              <div className="mt-8 border-t border-white/10 pt-7" onClick={() => setMenuOpen(false)}><WorkspaceLink signedIn={signedIn}/></div>
            </SheetContent>
          </Sheet>
        </div>
      </div>
    </header>

    <main id="landing-main" tabIndex={-1}>
      <section className="landing-hero" aria-labelledby="landing-headline">
        <div className="landing-hero-grid" aria-hidden="true"/>
        <div className="landing-container relative">
          <m.div {...entrance} className="mx-auto max-w-4xl text-center">
            <Badge><Sparkles size={12} aria-hidden="true"/> Your knowledge. A clearer perspective.<ChevronRight size={12} aria-hidden="true"/></Badge>
            <h1 id="landing-headline">Your company’s knowledge.<br/><span>Answers you can verify.</span></h1>
            <p className="landing-hero-description">Bring your documents together. Ask a better question.<br className="hidden sm:block"/> Get a grounded answer, with the sources to back it up.</p>
            <div className="mt-8 flex flex-wrap justify-center gap-3"><WorkspaceLink signedIn={signedIn} large/><Button asChild variant="outline" size="lg"><a href="#product">Explore the product<ArrowDown aria-hidden="true"/></a></Button></div>
            <p className="mt-4 text-xs text-slate-500">{signedIn ? 'Your workspace is ready when you are.' : 'Invitation-based workspaces. Built around your team.'}</p>
          </m.div>
          <div ref={productRef} id="product" className="landing-product-anchor">
            <div className="landing-product-halo" aria-hidden="true"/>
            <div className="landing-showcase-frame"><LandingShowcase/><BorderBeam active={visible && productInView}/></div>
            <div className="landing-product-footnotes"><span><FileCheck2 aria-hidden="true"/> Answers with citations</span><span><BookOpen aria-hidden="true"/> Connected knowledge bases</span><span><LockKeyhole aria-hidden="true"/> Permission-aware access</span></div>
          </div>
        </div>
      </section>

      <section id="features" className="landing-section landing-container" aria-labelledby="features-title">
        <div className="landing-section-heading"><p className="landing-eyebrow">From information to understanding</p><h2 id="features-title">Less searching.<br/>More knowing.</h2><p>Your best knowledge already exists. Give your team a clearer way to find it, understand it, and put it to work.</p></div>
        <div className="landing-feature-grid">
          <Card className="landing-feature-card"><div className="landing-feature-icon"><Search aria-hidden="true"/></div><h3>Find the meaning.<br/>Keep the context.</h3><p>Semantic and keyword search work together to find relevant passages. Reranking helps bring the strongest matches into focus.</p><div className="landing-search-visual" aria-hidden="true"><span>Semantic</span><Plus size={13}/><span>Keyword</span><ArrowRight size={14}/><strong>Relevant context</strong></div><span className="landing-feature-label">RETRIEVAL-AUGMENTED GENERATION</span></Card>
          <Card className="landing-feature-card"><div className="landing-feature-icon"><FileCheck2 aria-hidden="true"/></div><h3>An answer is useful.<br/>Evidence is better.</h3><p>Follow page-level PDF citations back to the original document. See the passage behind an answer and make your own informed call.</p><div className="landing-citation-visual" aria-hidden="true"><FileText size={21}/><div><strong>Team handbook.pdf</strong><span>Original document · page 12</span></div><span className="citation">[1]</span></div><span className="landing-feature-label">TRACEABLE PDF CITATIONS</span></Card>
          <Card className="landing-feature-card"><div className="landing-feature-icon"><BookOpen aria-hidden="true"/></div><h3>A place for every<br/>piece of knowledge.</h3><p>Organize documents into focused collections. Choose a knowledge base to keep each conversation close to the subject at hand.</p><div className="landing-collections-visual" aria-hidden="true"><span><FolderOpen size={14}/>Team handbook</span><span><FolderOpen size={14}/>Operations</span><span><FolderOpen size={14}/>Product</span></div><span className="landing-feature-label">PURPOSEFUL KNOWLEDGE BASES</span></Card>
          <Card className="landing-feature-card"><div className="landing-feature-icon"><Fingerprint aria-hidden="true"/></div><h3>The right knowledge.<br/>For the right people.</h3><p>Tenant isolation, account roles and document sharing control access. Knowledge-base membership keeps those permissions intact.</p><div className="landing-access-visual" aria-hidden="true"><span><ShieldCheck size={16}/>Document permissions</span><span><Check size={12}/> Applied before retrieval</span></div><span className="landing-feature-label">ACCESS THAT FOLLOWS YOUR RULES</span></Card>
        </div>
      </section>

      <section id="how-it-works" className="landing-section landing-workflow" aria-labelledby="workflow-title">
        <div className="landing-container"><div className="landing-section-heading text-center mx-auto"><p className="landing-eyebrow">A simpler path to clarity</p><h2 id="workflow-title">From document to dialogue.</h2><p>Keep the workflow familiar. Let the assistant connect the dots.</p></div>
          <ol className="landing-steps">{[
            { icon: Upload, title: 'Bring your knowledge', text: 'Upload PDFs, Markdown or text files. Background processing gets your documents ready while you keep working.' },
            { icon: MessageSquareText, title: 'Ask in your own words', text: 'Choose a knowledge base, ask a question, and continue the conversation with follow-ups.' },
            { icon: CheckCheck, title: 'Follow the evidence', text: 'Read the answer, inspect its sources, and open a cited PDF page when you need the full picture.' },
          ].map((step, index) => <li key={step.title}><div className="landing-step-number">0{index + 1}<step.icon size={21} aria-hidden="true"/></div><h3>{step.title}</h3><p>{step.text}</p></li>)}</ol>
        </div>
      </section>

      <section id="security" className="landing-section landing-container" aria-labelledby="security-title">
        <div className="landing-security-layout">
          <div className="landing-section-heading"><p className="landing-eyebrow">Confidence starts with control</p><h2 id="security-title">Your knowledge.<br/>Your boundaries.</h2><p>A shared assistant should respect the way your team works. Access checks stay part of the journey, from retrieval to the original source.</p><a href="#faq" className="mt-6 inline-flex items-center gap-2 text-sm font-medium text-violet-300 hover:text-violet-200">More about your data<ArrowRight size={15} aria-hidden="true"/></a></div>
          <Card className="landing-security-card"><div className="landing-security-card-heading"><ShieldCheck size={22} className="text-violet-300" aria-hidden="true"/><span>Designed around access</span><Badge className="border-teal-400/20 bg-teal-400/5 text-teal-300">Built in</Badge></div>
            {[
              ['Tenant boundaries', 'Keep retrieval scoped to the authenticated tenant.'],
              ['Document-level permissions', 'Check ownership and sharing before selecting sources.'],
              ['Authorized PDF viewing', 'Protect original documents behind authenticated access.'],
              ['Session controls', 'Review active password sessions and revoke access.'],
            ].map(([title, description]) => <div key={title} className="landing-security-row"><span><Check size={14} aria-hidden="true"/></span><div><h3>{title}</h3><p>{description}</p></div></div>)}
            <p className="landing-provider-note"><LockKeyhole size={13} aria-hidden="true"/><span>Embeddings run locally. Answer generation sends relevant context to your configured LLM provider.</span></p>
          </Card>
        </div>
      </section>

      <section id="faq" className="landing-section landing-container landing-faq-layout" aria-labelledby="faq-title">
        <div className="landing-section-heading"><p className="landing-eyebrow">A few things worth knowing</p><h2 id="faq-title">Good questions.<br/>Clear answers.</h2><p>A little context before your first conversation.</p></div>
        <Accordion type="single" collapsible className="min-w-0">{faqs.map(([question, answer], index) => <AccordionItem key={question} value={`faq-${index}`}><AccordionTrigger>{question}</AccordionTrigger><AccordionContent>{answer}</AccordionContent></AccordionItem>)}</Accordion>
      </section>

      <section className="landing-container landing-final-cta" aria-labelledby="cta-title"><div className="landing-cta-glow" aria-hidden="true"/><Layers size={31} className="relative mx-auto text-violet-300" aria-hidden="true"/><h2 id="cta-title">Your next great answer<br/>is already in your documents.</h2><p>Bring your team closer to what they know.</p><WorkspaceLink signedIn={signedIn} large/><span className="mt-4 block text-xs text-slate-500">{signedIn ? 'Continue in your authorized workspace.' : 'Create your private workspace. No invitation required.'}</span></section>
    </main>

    <footer className="landing-footer landing-container"><div><a href="#landing-main" aria-label="KnowledgeBase home"><Brand/></a><p>Built for knowledge. Grounded in sources.</p></div><nav aria-label="Footer navigation"><a href="#product">Product</a><a href="#security">Security</a><a href="#faq">FAQ</a><a href={signedIn ? '/assistant' : '/login'} onClick={followLink}>{signedIn ? 'Workspace' : 'Sign in'}</a></nav><span>© {new Date().getFullYear()} KnowledgeBase</span></footer>
  </div>
}

export default function LandingPage({ signedIn = false }: { signedIn?: boolean }) {
  return <LazyMotion features={domAnimation} strict><MotionConfig reducedMotion="user"><PrecisionLanding signedIn={signedIn}/></MotionConfig></LazyMotion>
}
