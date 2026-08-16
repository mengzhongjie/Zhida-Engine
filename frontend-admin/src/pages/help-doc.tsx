import { useEffect, useMemo, useState } from 'react'
import { Link, useLocation, useSearchParams } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { BookOutlined, HomeOutlined } from '@ant-design/icons'
import helpMd from '../assets/help.md?raw'

/**
 * 帮助文档页 —— /help/doc
 * 独立渲染 src/assets/help.md 全文（目录 + 正文），支持 ?q= 关键词定位与 #锚点。
 */

export function slugify(s: string): string {
  return s.toLowerCase().replace(/[^\w\u4e00-\u9fa5]+/g, '-').replace(/^-+|-+$/g, '')
}

export function extractToc(md: string) {
  const toc: { level: number; text: string; id: string }[] = []
  for (const m of md.matchAll(/^(#{1,3})\s+(.+)$/gm)) {
    const level = m[1].length
    const text = m[2].trim()
    toc.push({ level, text, id: slugify(text) })
  }
  return toc
}

export const TOC = extractToc(helpMd)

// 目录树：一级章节 + 其下二级子节
export function buildTocTree(toc: { level: number; text: string; id: string }[]) {
  const tree: { h1: { text: string; id: string }; children: { text: string; id: string }[] }[] = []
  let cur: (typeof tree)[number] | null = null
  for (const t of toc) {
    if (t.level === 1) {
      cur = { h1: { text: t.text, id: t.id }, children: [] }
      tree.push(cur)
    } else if (t.level === 2 && cur) {
      cur.children.push({ text: t.text, id: t.id })
    }
  }
  return tree
}

export default function HelpDoc() {
  const location = useLocation()
  const [searchParams] = useSearchParams()
  const query = useMemo(() => (searchParams.get('q') || '').trim(), [searchParams])
  const tree = useMemo(() => buildTocTree(TOC), [])
  // 默认展开第一个章节；记录展开的章节 id
  const [open, setOpen] = useState<string>(tree[0]?.h1.id ?? '')

  const jump = (id: string) => {
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  // 支持 ?q= 关键词定位：滚动到第一个匹配标题
  useEffect(() => {
    if (query) {
      const q = query.toLowerCase()
      const hit = TOC.find(t => t.text.toLowerCase().includes(q))
      if (hit) {
        // 等正文渲染完成后再滚动
        setTimeout(() => jump(hit.id), 80)
      }
    } else if (location.hash) {
      setTimeout(() => jump(location.hash.slice(1)), 80)
    }
  }, [query, location.hash])

  const heading = (level: 1 | 2 | 3 | 4) =>
    function Heading({ children }: { children?: React.ReactNode }) {
      const text = String(children ?? '').replace(/[`*_]/g, '').trim()
      const Comp = `h${level}` as 'h1'
      return <Comp id={slugify(text)}>{children}</Comp>
    }

  return (
    <div className="help-page help-doc-page">
      <div className="help-doc-toolbar">
        <Link to="/help" className="help-doc-back"><HomeOutlined /> 返回帮助中心</Link>
        <div className="help-doc-toolbar-title"><BookOutlined /> 帮助文档 {query && <span className="help-doc-query">「{query}」已定位到相关章节</span>}</div>
      </div>

      <div className="help-body">
        <nav className="help-toc">
          <div className="help-toc-title"><BookOutlined /> 文档目录</div>
          {tree.map(section => (
            <div key={section.h1.id} className="help-toc-section">
              <div
                className="help-toc-item lv1"
                onClick={() => { setOpen(open === section.h1.id ? '' : section.h1.id); jump(section.h1.id) }}
              >
                <span className="help-toc-caret">{open === section.h1.id ? '▾' : '▸'}</span>
                <span className="help-toc-label">{section.h1.text}</span>
              </div>
              {open === section.h1.id && section.children.map(child => (
                <div key={child.id} className="help-toc-item lv2" onClick={() => jump(child.id)}>{child.text}</div>
              ))}
            </div>
          ))}
        </nav>
        <article className="help-content">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              h1: heading(1),
              h2: heading(2),
              h3: heading(3),
              h4: heading(4),
              a: ({ href, children }) => href?.startsWith('#') ? <a href={href} onClick={e => { e.preventDefault(); jump(href.slice(1)) }}>{children}</a> : <a href={href} target="_blank" rel="noreferrer">{children}</a>,
            }}
          >
            {helpMd}
          </ReactMarkdown>
        </article>
      </div>
    </div>
  )
}
