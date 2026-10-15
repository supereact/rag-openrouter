import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { SearchHit } from './types'

type MarkdownNode = {
  type: string
  value?: string
  url?: string
  children?: MarkdownNode[]
}

type CitationPluginOptions = {
  entryId: number
  sourceNumbers: number[]
}

/** Turn valid [n] markers in ordinary Markdown text into internal links.
 * Markdown code blocks and existing links are intentionally left unchanged.
 */
function remarkSourceCitations({ entryId, sourceNumbers }: CitationPluginOptions) {
  const valid = new Set(sourceNumbers)

  return (tree: MarkdownNode) => {
    function walk(node: MarkdownNode) {
      if (!node.children || node.type === 'link' || node.type === 'linkReference') return
      const children: MarkdownNode[] = []

      for (const child of node.children) {
        if (child.type !== 'text' || !child.value) {
          walk(child)
          children.push(child)
          continue
        }

        const matches = [...child.value.matchAll(/\[(\d+)\]/g)].filter(match => valid.has(Number(match[1])))
        if (!matches.length) {
          children.push(child)
          continue
        }

        let offset = 0
        for (const match of matches) {
          const start = match.index
          if (start > offset) children.push({ type: 'text', value: child.value.slice(offset, start) })
          const number = Number(match[1])
          children.push({
            type: 'link',
            url: `#rag-source-${entryId}-${number}`,
            children: [{ type: 'text', value: `[${number}]` }],
          })
          offset = start + match[0].length
        }
        if (offset < child.value.length) children.push({ type: 'text', value: child.value.slice(offset) })
      }
      node.children = children
    }

    walk(tree)
  }
}

/** Safe Markdown rendering: no raw HTML interpretation, no remote images.
 * The standard react-markdown URL sanitizer blocks unsafe link protocols.
 */
export default function MarkdownAnswer({ text, sources, entryId, onCitationClick }: {
  text: string
  sources: SearchHit[]
  entryId: number
  onCitationClick?: (source: SearchHit) => void
}) {
  const sourceNumbers = sources.map(source => source.source_number)

  return <div className="rag-markdown text-sm leading-7 text-slate-800">
    <ReactMarkdown
      remarkPlugins={[remarkGfm, [remarkSourceCitations, { entryId, sourceNumbers }]]}
      components={{
        h1: ({ children }) => <h1 className="text-xl font-bold mt-5 mb-3 first:mt-0">{children}</h1>,
        h2: ({ children }) => <h2 className="text-lg font-bold mt-5 mb-2 first:mt-0">{children}</h2>,
        h3: ({ children }) => <h3 className="text-base font-semibold mt-4 mb-2 first:mt-0">{children}</h3>,
        h4: ({ children }) => <h4 className="font-semibold mt-3 mb-1">{children}</h4>,
        p: ({ children }) => <p className="mb-3 last:mb-0">{children}</p>,
        ul: ({ children }) => <ul className="list-disc pl-6 mb-3 space-y-1">{children}</ul>,
        ol: ({ children }) => <ol className="list-decimal pl-6 mb-3 space-y-1">{children}</ol>,
        li: ({ children }) => <li className="pl-1">{children}</li>,
        blockquote: ({ children }) => <blockquote className="border-l-4 border-indigo-200 pl-4 my-3 italic text-slate-600">{children}</blockquote>,
        pre: ({ children }) => <pre className="bg-slate-900 text-slate-100 text-xs rounded-lg px-4 py-3 my-3 overflow-x-auto whitespace-pre">{children}</pre>,
        code: ({ children, className }) => <code className={className}>{children}</code>,
        table: ({ children }) => <div className="overflow-x-auto my-3"><table className="w-full text-left text-xs border-collapse">{children}</table></div>,
        th: ({ children }) => <th className="border border-slate-200 bg-slate-100 px-3 py-2 font-semibold">{children}</th>,
        td: ({ children }) => <td className="border border-slate-200 px-3 py-2 align-top">{children}</td>,
        hr: () => <hr className="border-slate-200 my-4"/>,
        img: ({ alt }) => <span className="text-slate-500">[Image omitted{alt ? `: ${alt}` : ''}]</span>,
        a: ({ href, children }) => {
          const matched = /^#rag-source-(\d+)-(\d+)$/.exec(href ?? '')
          if (matched && Number(matched[1]) === entryId && sourceNumbers.includes(Number(matched[2]))) {
            const n = Number(matched[2])
            return <button type="button" className="citation" aria-label={`Jump to source ${n}`} onClick={() => {
              const element = document.getElementById(`source-${entryId}-${n}`)
              element?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
              element?.focus()
              const source = sources.find(source => source.source_number === n)
              if (source && onCitationClick) onCitationClick(source)
            }}>{children}</button>
          }
          return href ? <a href={href} target="_blank" rel="noopener noreferrer nofollow" className="text-indigo-600 underline underline-offset-2 break-all">{children}</a> : <span>{children}</span>
        },
      }}
    >{text}</ReactMarkdown>
  </div>
}
