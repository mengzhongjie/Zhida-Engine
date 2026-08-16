import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Button, Card, Drawer, Input, Select, Space, Table, Tag, Typography, message } from 'antd'
import { ArrowLeftOutlined, ReloadOutlined } from '@ant-design/icons'
import { api } from '@/services/api'

type Item = {
  id: number
  agent_id: number
  question: string
  answer: string
  sources: string | null
  channel?: string | null
  user_id?: string | null
  chat_id?: string | null
  input_tokens: number
  output_tokens: number
  is_degraded: boolean
  web_search_count: number
  response_time_ms: number
  from_cache: boolean
  created_at: string
}
type Agent = { id: number; name: string }

const CHANNEL_META: Record<string, { label: string; color: string }> = {
  web: { label: '管理台', color: 'blue' },
  qq: { label: 'QQ 机器人', color: 'green' },
  feishu: { label: '飞书机器人', color: 'purple' },
  unknown: { label: '其他', color: 'default' },
}

// 简洁相对时间：刚刚 / N 分钟前 / N 小时前 / MM-DD HH:mm
function fmtTime(iso: string) {
  const t = new Date(iso.replace(' ', 'T')).getTime()
  if (Number.isNaN(t)) return iso
  const diff = Date.now() - t
  if (diff < 60 * 1000) return '刚刚'
  if (diff < 3600 * 1000) return `${Math.floor(diff / 60000)} 分钟前`
  if (diff < 24 * 3600 * 1000) return `${Math.floor(diff / 3600000)} 小时前`
  const d = new Date(t)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export default function ChannelDetail() {
  const { channel = 'unknown' } = useParams()
  const navigate = useNavigate()
  const meta = CHANNEL_META[channel] || { label: channel, color: 'default' }

  const [items, setItems] = useState<Item[]>([])
  const [agents, setAgents] = useState<Agent[]>([])
  const [agentName, setAgentName] = useState<Record<number, string>>({})
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [agentId, setAgentId] = useState<number>()
  const [keyword, setKeyword] = useState('')
  const [detail, setDetail] = useState<Item | null>(null)
  const [loading, setLoading] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const params: Record<string, unknown> = { page, page_size: pageSize, channel }
      if (agentId) params.agent_id = agentId
      if (keyword.trim()) params.keyword = keyword.trim()
      const r = await api.get<{ total: number; items: Item[] }>('/qa/history', { params })
      setItems(r.items)
      setTotal(r.total)
    } catch { message.error('加载问答记录失败') }
    finally { setLoading(false) }
  }

  useEffect(() => { void load() }, [page, pageSize, channel, agentId])
  useEffect(() => { const t = setTimeout(() => { setPage(1); void load() }, 400); return () => clearTimeout(t) }, [keyword])
  useEffect(() => { setPage(1) }, [channel])

  useEffect(() => {
    api.get<{ items: Agent[] }>('/agents').then(r => {
      setAgents(r.items)
      const map: Record<number, string> = {}
      r.items.forEach(a => { map[a.id] = a.name })
      setAgentName(map)
    }).catch(() => undefined)
  }, [])

  const parsedSources = (item: Item) => {
    try { return JSON.parse(item.sources || '[]') as unknown[] } catch { return [] }
  }

  return (
    <div className="observe-page">
      <div className="page-header">
        <div>
          <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => navigate('/observability')} style={{ marginLeft: -8 }}>返回观测首页</Button>
          <Typography.Title level={3} style={{ margin: 0 }}>渠道问答 · <Tag color={meta.color}>{meta.label}</Tag></Typography.Title>
          <Typography.Text type="secondary">共 {total} 条问答记录，含 Token 与耗时指标。</Typography.Text>
        </div>
        <Button icon={<ReloadOutlined />} onClick={() => void load()} loading={loading}>刷新</Button>
      </div>

      <Card style={{ marginTop: 16 }}>
        <Space wrap style={{ marginBottom: 16 }}>
          <Select
            allowClear showSearch placeholder="全部 Agent" style={{ width: 180 }}
            value={agentId} onChange={setAgentId}
            options={agents.map(a => ({ value: a.id, label: a.name }))}
            optionFilterProp="label"
          />
          <Input.Search
            allowClear placeholder="搜索问题 / 回答关键词" style={{ width: 260 }}
            value={keyword} onChange={e => setKeyword(e.target.value)}
            onSearch={() => { setPage(1); void load() }}
          />
        </Space>

        <Table<Item>
          rowKey="id"
          loading={loading}
          dataSource={items}
          pagination={{
            current: page, pageSize, total,
            showSizeChanger: true, showTotal: t => `共 ${t} 条`,
            onChange: (p, ps) => { setPage(p); setPageSize(ps) },
          }}
          columns={[
            { title: '时间', dataIndex: 'created_at', width: 130, render: (v: string) => <Typography.Text type="secondary" style={{ fontSize: 12.5 }}>{fmtTime(v)}</Typography.Text> },
            { title: 'Agent', dataIndex: 'agent_id', width: 120, render: (id: number) => agentName[id] || `#${id}` },
            { title: '问题', dataIndex: 'question', ellipsis: true, render: (v: string) => <span style={{ fontWeight: 500 }}>{v}</span> },
            { title: '回答', dataIndex: 'answer', ellipsis: true, render: (v: string) => <Typography.Text type="secondary" style={{ fontSize: 13 }}>{v}</Typography.Text> },
            { title: 'Token', width: 120, render: (_, r) => <Typography.Text type="secondary" style={{ fontSize: 12.5 }}>↑{r.input_tokens} / ↓{r.output_tokens}</Typography.Text> },
            { title: '耗时', width: 90, render: (_, r) => <Typography.Text type="secondary" style={{ fontSize: 12.5 }}>{r.response_time_ms ? `${(r.response_time_ms / 1000).toFixed(1)}s` : '-'}</Typography.Text> },
            { title: '状态', width: 130, render: (_, r) => <Space size={4} wrap>{r.from_cache && <Tag>缓存</Tag>}{r.web_search_count > 0 && <Tag color="orange">搜索×{r.web_search_count}</Tag>}{r.is_degraded && <Tag color="red">降级</Tag>}</Space> },
            { title: '操作', width: 70, render: (_, r) => <Button type="link" size="small" onClick={() => setDetail(r)}>详情</Button> },
          ]}
        />
      </Card>

      <Drawer title="问答详情" width={640} open={detail !== null} onClose={() => setDetail(null)}>
        {detail && <>
          <Typography.Paragraph><Typography.Text strong>时间：</Typography.Text>{detail.created_at}</Typography.Paragraph>
          <Typography.Paragraph><Typography.Text strong>渠道：</Typography.Text><Tag color={meta.color}>{meta.label}</Tag><Typography.Text type="secondary"> chat_id: {detail.chat_id || '-'} · user: {detail.user_id || '-'}</Typography.Text></Typography.Paragraph>
          <Typography.Paragraph><Typography.Text strong>Agent：</Typography.Text>{agentName[detail.agent_id] || `#${detail.agent_id}`}</Typography.Paragraph>
          <Typography.Paragraph><Typography.Text strong>指标：</Typography.Text><Typography.Text type="secondary">输入 {detail.input_tokens} · 输出 {detail.output_tokens} · 耗时 {(detail.response_time_ms / 1000).toFixed(1)}s{detail.from_cache ? ' · 缓存' : ''}{detail.is_degraded ? ' · 降级' : ''}{detail.web_search_count ? ` · 搜索×${detail.web_search_count}` : ''}</Typography.Text></Typography.Paragraph>
          <Typography.Title level={5}>问题</Typography.Title>
          <Typography.Paragraph style={{ whiteSpace: 'pre-wrap' }}>{detail.question}</Typography.Paragraph>
          <Typography.Title level={5}>回答</Typography.Title>
          <Typography.Paragraph style={{ whiteSpace: 'pre-wrap' }}>{detail.answer}</Typography.Paragraph>
          <Typography.Title level={5}>引用来源（{parsedSources(detail).length}）</Typography.Title>
          {parsedSources(detail).length === 0
            ? <Typography.Text type="secondary">无来源记录</Typography.Text>
            : <pre style={{ background: '#f6f8fc', padding: 12, borderRadius: 8, fontSize: 12.5, overflow: 'auto', maxHeight: 320 }}>{JSON.stringify(parsedSources(detail), null, 2)}</pre>}
        </>}
      </Drawer>
    </div>
  )
}
