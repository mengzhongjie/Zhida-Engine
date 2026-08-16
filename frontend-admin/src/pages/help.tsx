import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Input, Tag } from 'antd'
import { BookOutlined, DatabaseOutlined, MessageOutlined, QuestionCircleOutlined, RocketOutlined, SafetyCertificateOutlined, SearchOutlined } from '@ant-design/icons'
import { TOC } from './help-doc'

/**
 * 帮助中心首页 —— 功能入口卡片 + 搜索，文档正文在 /help/doc 独立页面。
 */

const QUICK_TAGS = ['部署', '飞书', 'QQ', '群列表', 'python', '端口', '凭据', '收不到']

const QUICK_ENTRIES = [
  { title: '快速开始', description: '从部署到首个 Agent', icon: <RocketOutlined />, heading: '二、快速部署' },
  { title: '配置知识库', description: '导入资料并完成向量化', icon: <DatabaseOutlined />, heading: '三、第一次使用' },
  { title: '机器人接入', description: 'QQ 与飞书群问答', icon: <MessageOutlined />, heading: '四、接入 QQ' },
  { title: '常见问题', description: '按现象快速排查', icon: <QuestionCircleOutlined />, heading: '七、常见问题 FAQ' },
]

export default function HelpPage() {
  const navigate = useNavigate()
  const [query, setQuery] = useState('')

  const goDoc = (q?: string, anchor?: string) => {
    const params = new URLSearchParams()
    if (q) params.set('q', q)
    const queryStr = params.toString()
    navigate(anchor ? `/help/doc#${anchor}` : `/help/doc${queryStr ? `?${queryStr}` : ''}`)
  }

  const onSearch = (value: string) => goDoc(value.trim() || undefined)
  const goHeading = (heading: string) => {
    const item = TOC.find(entry => entry.text.startsWith(heading))
    if (item) goDoc(undefined, item.id)
  }

  return (
    <div className="help-page">
      <div className="help-hero">
        <div className="help-hero-kicker"><BookOutlined /> 智答引擎使用文档</div>
        <div className="help-hero-title">帮助中心</div>
        <div className="help-hero-sub">从零部署、首次配置、接入 QQ / 飞书机器人，以及常见问题检索。</div>
        <div className="help-hero-meta" aria-label="文档能力概览">
          <span><RocketOutlined /> 3 步快速上手</span>
          <span><MessageOutlined /> QQ / 飞书机器人</span>
          <span><SafetyCertificateOutlined /> 本地数据存储</span>
        </div>
        <Input
          className="help-search"
          prefix={<SearchOutlined style={{ color: '#94a3b8' }} />}
          placeholder="搜索帮助内容，如：飞书、群列表、python、端口"
          allowClear
          value={query}
          onChange={e => setQuery(e.target.value)}
          onPressEnter={() => onSearch(query)}
          suffix={
            <button type="button" className="help-search-go" aria-label="搜索" onClick={() => onSearch(query)}>
              <SearchOutlined />
            </button>
          }
        />
        <div className="help-quick-tags">
          <span className="help-quick-label">热门：</span>
          {QUICK_TAGS.map(t => (
            <Tag key={t} className="help-quick-tag" onClick={() => goDoc(t)}>{t}</Tag>
          ))}
        </div>
      </div>

      <div className="help-entry-grid" aria-label="常用帮助入口">
        {QUICK_ENTRIES.map(entry => (
          <button key={entry.title} className="help-entry-card" onClick={() => goHeading(entry.heading)}>
            <span className="help-entry-icon">{entry.icon}</span>
            <span className="help-entry-copy"><strong>{entry.title}</strong><small>{entry.description}</small></span>
            <span className="help-entry-arrow">→</span>
          </button>
        ))}
      </div>

      <div className="help-doc-index">
        <div className="help-doc-index-head"><div className="help-toc-title"><BookOutlined /> 全部章节</div><button onClick={() => goDoc()}>查看完整文档 →</button></div>
        <div className="help-doc-index-list">
          {TOC.filter(t => t.level === 1).map(t => (
            <span key={t.id} className="help-doc-index-item" onClick={() => goDoc(undefined, t.id)}>{t.text}</span>
          ))}
        </div>
      </div>
    </div>
  )
}
