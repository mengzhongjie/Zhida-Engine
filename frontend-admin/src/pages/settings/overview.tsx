import { Card, Col, Row, Tag, Typography } from 'antd'
import { Link } from 'react-router-dom'
import { ApiOutlined, DatabaseOutlined, EyeOutlined, GlobalOutlined, CloudOutlined, SafetyCertificateOutlined, RadarChartOutlined, RobotOutlined } from '@ant-design/icons'
import styles from './index.module.css'

const { Title, Text } = Typography

const entries = [
  { to: '/settings/models', icon: <ApiOutlined />, title: '模型服务', desc: '主模型、降级模型与独立模型配置', tag: 'LLM' },
  { to: '/settings/embedding', icon: <DatabaseOutlined />, title: '向量化模型', desc: '多套向量配置与受控索引切换', tag: 'Embedding' },
  { to: '/settings/vision', icon: <EyeOutlined />, title: '视觉模型', desc: '主模型与降级模型，用于网页和云文档图片', tag: '可选' },
  { to: '/settings/search', icon: <GlobalOutlined />, title: '网络检索', desc: '仅在本地知识不足时补充信息', tag: '可选' },
  { to: '/settings/observability', icon: <RadarChartOutlined />, title: 'Agent 链路观测', desc: '记录 Agent 问答与调用链路', tag: '可选' },
  { to: '/settings/sources', icon: <CloudOutlined />, title: '云文档配置', desc: '连接外部云文档与知识内容来源', tag: '扩展' },
  { to: '/settings/bots', icon: <RobotOutlined />, title: '机器人', desc: 'QQ 与后续消息平台的统一配置入口', tag: '扩展' },
  { to: '/settings/system', icon: <SafetyCertificateOutlined />, title: '系统信息', desc: '本地运行状态、备份与数据一致性核验', tag: '本地' },
]

export default function SettingsOverview() {
  return <div className={styles.container}>
    <div className="page-header"><div><Title level={3}>设置</Title><Text type="secondary">按需进入配置项，避免在一个页面堆叠所有参数。</Text></div></div>
    <Row gutter={[16, 16]}>{entries.map(item => <Col xs={24} md={12} xl={8} key={item.to}><Link to={item.to}>
      <Card hoverable><div style={{ display: 'flex', gap: 14, alignItems: 'flex-start' }}><div style={{ fontSize: 24, color: '#1677ff' }}>{item.icon}</div><div><div style={{ display: 'flex', gap: 8, alignItems: 'center' }}><Text strong>{item.title}</Text><Tag>{item.tag}</Tag></div><Text type="secondary">{item.desc}</Text></div></div></Card>
    </Link></Col>)}</Row>
  </div>
}
