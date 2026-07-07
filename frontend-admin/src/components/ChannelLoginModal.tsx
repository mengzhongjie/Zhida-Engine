/**
 * 智答引擎（ZhiDa Engine）—— 渠道扫码登录组件
 *
 * 支持 QQ / 微信扫码登录，登录成功后可选择群聊/好友，
 * 选择群聊后可查看群成员并指定监听用户。
 */
import { useState, useEffect, useRef } from 'react'
import {
  Modal, Tabs, Button, Space, List, Avatar, Tag, Input,
  Spin, message, Checkbox, Typography, Divider, Empty, Radio
} from 'antd'
import {
  QrcodeOutlined, UserOutlined, TeamOutlined,
  ReloadOutlined, CheckOutlined,
} from '@ant-design/icons'
import { api } from '../../services/api'

const { Title, Text } = Typography

interface GroupItem {
  id: string
  name: string
  member_count: number
  avatar: string
}

interface FriendItem {
  id: string
  nickname: string
  remark: string
  avatar: string
}

interface GroupMember {
  user_id: string
  nickname: string
  card: string
  role: string
  avatar: string
  join_time: number
}

interface QRCodeResult {
  login_id: string
  qrcode_url: string
  qrcode_content: string
  expires_at: number
  message?: string
}

interface LoginStatus {
  status: 'waiting' | 'scanned' | 'confirmed' | 'success' | 'expired' | 'unsupported'
  user_info?: {
    id: string
    nickname: string
    avatar: string
  }
  message: string
}

interface ChannelLoginModalProps {
  open: boolean
  onCancel: () => void
  onConfirm: (data: {
    channel_type: string
    chat_id: string
    chat_name: string
    chat_type: 'group' | 'private'
    target_users?: string[]
  }) => void
  confirmLoading?: boolean
}

export default function ChannelLoginModal({
  open,
  onCancel,
  onConfirm,
  confirmLoading = false,
}: ChannelLoginModalProps) {
  const [activeChannel, setActiveChannel] = useState<string>('qq')
  const [activeTab, setActiveTab] = useState<string>('qrcode')
  const [qrcodeData, setQrcodeData] = useState<QRCodeResult | null>(null)
  const [loginStatus, setLoginStatus] = useState<LoginStatus | null>(null)
  const [loading, setLoading] = useState(false)
  const [contacts, setContacts] = useState<{ groups: GroupItem[], friends: FriendItem[] }>({
    groups: [],
    friends: [],
  })
  const [selectedChat, setSelectedChat] = useState<{
    type: 'group' | 'private'
    id: string
    name: string
  } | null>(null)
  const [groupMembers, setGroupMembers] = useState<GroupMember[]>([])
  const [selectedMembers, setSelectedMembers] = useState<string[]>([])
  const [searchText, setSearchText] = useState('')
  const [memberLoading, setMemberLoading] = useState(false)

  const pollTimerRef = useRef<number | null>(null)

  /**
   * 生成登录二维码
   */
  const generateQrcode = async () => {
    try {
      setLoading(true)
      setLoginStatus(null)
      const result = await api.post<QRCodeResult>(`/channels/${activeChannel}/login/qrcode`)
      setQrcodeData(result)
      setLoginStatus({ status: 'waiting', message: '等待扫码' })
      // 开始轮询登录状态
      startPolling(result.login_id)
    } catch (err: any) {
      message.error(err.response?.data?.detail || '生成二维码失败')
    } finally {
      setLoading(false)
    }
  }

  /**
   * 轮询登录状态
   */
  const startPolling = (loginId: string) => {
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current)
    }

    const poll = async () => {
      try {
        const status = await api.get<LoginStatus>(
          `/channels/${activeChannel}/login/status/${loginId}`
        )
        setLoginStatus(status)

        if (status.status === 'success' || status.status === 'expired') {
          if (pollTimerRef.current) {
            clearInterval(pollTimerRef.current)
            pollTimerRef.current = null
          }
          if (status.status === 'success') {
            message.success('登录成功')
            // 登录成功后加载联系人列表
            loadContacts()
          }
        }
      } catch (err) {
        console.error('查询登录状态失败:', err)
      }
    }

    pollTimerRef.current = window.setInterval(poll, 2000)
  }

  /**
   * 加载联系人列表
   */
  const loadContacts = async () => {
    try {
      setLoading(true)
      const result = await api.get<{ groups: GroupItem[], friends: FriendItem[] }>(
        `/channels/${activeChannel}/contacts`
      )
      setContacts(result)
      setActiveTab('contacts')
    } catch (err: any) {
      message.error(err.response?.data?.detail || '获取联系人列表失败')
    } finally {
      setLoading(false)
    }
  }

  /**
   * 加载群成员列表
   */
  const loadGroupMembers = async (groupId: string) => {
    try {
      setMemberLoading(true)
      const result = await api.get<{ total: number, members: GroupMember[] }>(
        `/channels/${activeChannel}/groups/${groupId}/members`
      )
      setGroupMembers(result.members)
      setSelectedMembers([])
    } catch (err: any) {
      message.error(err.response?.data?.detail || '获取群成员列表失败')
    } finally {
      setMemberLoading(false)
    }
  }

  /**
   * 选择群聊
   */
  const handleSelectGroup = (group: GroupItem) => {
    setSelectedChat({
      type: 'group',
      id: group.id,
      name: group.name,
    })
    loadGroupMembers(group.id)
    setActiveTab('members')
  }

  /**
   * 选择好友
   */
  const handleSelectFriend = (friend: FriendItem) => {
    setSelectedChat({
      type: 'private',
      id: friend.id,
      name: friend.remark || friend.nickname,
    })
  }

  /**
   * 群成员勾选变化
   */
  const handleMemberCheck = (userId: string, checked: boolean) => {
    setSelectedMembers(prev =>
      checked
        ? [...prev, userId]
        : prev.filter(id => id !== userId)
    )
  }

  /**
   * 全选/取消全选
   */
  const handleSelectAllMembers = (checked: boolean) => {
    if (checked) {
      setSelectedMembers(groupMembers.map(m => m.user_id))
    } else {
      setSelectedMembers([])
    }
  }

  /**
   * 确认添加渠道
   */
  const handleConfirm = () => {
    if (!selectedChat) {
      message.warning('请先选择群聊或好友')
      return
    }

    onConfirm({
      channel_type: activeChannel,
      chat_id: selectedChat.id,
      chat_name: selectedChat.name,
      chat_type: selectedChat.type,
      target_users: selectedChat.type === 'group' && selectedMembers.length > 0
        ? selectedMembers
        : undefined,
    })
  }

  /**
   * 重置状态
   */
  const resetState = () => {
    setQrcodeData(null)
    setLoginStatus(null)
    setContacts({ groups: [], friends: [] })
    setSelectedChat(null)
    setGroupMembers([])
    setSelectedMembers([])
    setSearchText('')
    setActiveTab('qrcode')
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current)
      pollTimerRef.current = null
    }
  }

  useEffect(() => {
    if (open) {
      resetState()
    }
    return () => {
      if (pollTimerRef.current) {
        clearInterval(pollTimerRef.current)
      }
    }
  }, [open, activeChannel])

  /**
   * 渲染二维码内容
   */
  const renderQrcodeContent = () => {
    if (loading && !qrcodeData) {
      return (
        <div style={{ textAlign: 'center', padding: '40px 0' }}>
          <Spin size="large" />
          <div style={{ marginTop: 16 }}>正在生成二维码...</div>
        </div>
      )
    }

    if (!qrcodeData) {
      return (
        <div style={{ textAlign: 'center', padding: '40px 0' }}>
          <QrcodeOutlined style={{ fontSize: 64, color: '#999' }} />
          <div style={{ marginTop: 16, color: '#666' }}>
            点击下方按钮生成登录二维码
          </div>
          <Button
            type="primary"
            icon={<QrcodeOutlined />}
            onClick={generateQrcode}
            style={{ marginTop: 20 }}
          >
            生成二维码
          </Button>
        </div>
      )
    }

    const statusText: Record<string, string> = {
      waiting: '等待扫码',
      scanned: '已扫码，请在手机上确认',
      confirmed: '登录确认中...',
      success: '登录成功',
      expired: '二维码已过期',
    }

    const statusColor: Record<string, string> = {
      waiting: 'blue',
      scanned: 'gold',
      confirmed: 'cyan',
      success: 'green',
      expired: 'red',
    }

    return (
      <div style={{ textAlign: 'center' }}>
        <div
          style={{
            width: 200,
            height: 200,
            margin: '0 auto',
            border: '1px solid #eee',
            borderRadius: 8,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            background: '#fafafa',
          }}
        >
          {qrcodeData.qrcode_url ? (
            <img
              src={qrcodeData.qrcode_url}
              alt="登录二维码"
              style={{ width: '100%', height: '100%' }}
            />
          ) : (
            <div style={{ padding: 20 }}>
              <QrcodeOutlined style={{ fontSize: 48, color: '#999' }} />
              <div style={{ fontSize: 12, color: '#999', marginTop: 8 }}>
                {qrcodeData.message || '请使用手机扫码'}
              </div>
            </div>
          )}
        </div>

        <div style={{ marginTop: 16 }}>
          <Tag color={statusColor[loginStatus?.status || 'waiting']}>
            {statusText[loginStatus?.status || 'waiting']}
          </Tag>
        </div>

        <Text type="secondary" style={{ fontSize: 12 }}>
          {loginStatus?.message || '请使用手机 QQ/微信 扫一扫登录'}
        </Text>

        {(loginStatus?.status === 'expired' || loginStatus?.status === 'unsupported') && (
          <div style={{ marginTop: 16 }}>
            <Button
              icon={<ReloadOutlined />}
              onClick={generateQrcode}
            >
              重新生成
            </Button>
          </div>
        )}
      </div>
    )
  }

  /**
   * 过滤后的群列表
   */
  const filteredGroups = contacts.groups.filter(g =>
    g.name.toLowerCase().includes(searchText.toLowerCase())
  )

  /**
   * 过滤后的好友列表
   */
  const filteredFriends = contacts.friends.filter(f =>
    f.nickname.toLowerCase().includes(searchText.toLowerCase()) ||
    f.remark.toLowerCase().includes(searchText.toLowerCase())
  )

  /**
   * 过滤后的群成员列表
   */
  const filteredMembers = groupMembers.filter(m =>
    m.nickname.toLowerCase().includes(searchText.toLowerCase()) ||
    m.card.toLowerCase().includes(searchText.toLowerCase())
  )

  /**
   * 渲染联系人列表
   */
  const renderContactsContent = () => {
    if (loading) {
      return (
        <div style={{ textAlign: 'center', padding: '40px 0' }}>
          <Spin size="large" />
          <div style={{ marginTop: 16 }}>加载联系人列表...</div>
        </div>
      )
    }

    return (
      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        items={[
          {
            key: 'groups',
            label: (
              <span>
                <TeamOutlined /> 群聊 ({contacts.groups.length})
              </span>
            ),
            children: (
              <div>
                <Input.Search
                  placeholder="搜索群聊"
                  value={searchText}
                  onChange={e => setSearchText(e.target.value)}
                  style={{ marginBottom: 12 }}
                  allowClear
                />
                {filteredGroups.length === 0 ? (
                  <Empty description="暂无群聊" />
                ) : (
                  <List
                    dataSource={filteredGroups}
                    renderItem={(group) => (
                      <List.Item
                        key={group.id}
                        style={{ cursor: 'pointer', padding: '8px 12px' }}
                        onClick={() => handleSelectGroup(group)}
                      >
                        <List.Item.Meta
                          avatar={
                            <Avatar
                              src={group.avatar}
                              icon={!group.avatar && <TeamOutlined />}
                            />
                          }
                          title={group.name}
                          description={`${group.member_count} 人`}
                        />
                        {selectedChat?.id === group.id && (
                          <CheckOutlined style={{ color: '#1677ff' }} />
                        )}
                      </List.Item>
                    )}
                    style={{ maxHeight: 300, overflowY: 'auto' }}
                  />
                )}
              </div>
            ),
          },
          {
            key: 'friends',
            label: (
              <span>
                <UserOutlined /> 好友 ({contacts.friends.length})
              </span>
            ),
            children: (
              <div>
                <Input.Search
                  placeholder="搜索好友"
                  value={searchText}
                  onChange={e => setSearchText(e.target.value)}
                  style={{ marginBottom: 12 }}
                  allowClear
                />
                {filteredFriends.length === 0 ? (
                  <Empty description="暂无好友" />
                ) : (
                  <List
                    dataSource={filteredFriends}
                    renderItem={(friend) => (
                      <List.Item
                        key={friend.id}
                        style={{ cursor: 'pointer', padding: '8px 12px' }}
                        onClick={() => handleSelectFriend(friend)}
                      >
                        <List.Item.Meta
                          avatar={
                            <Avatar
                              src={friend.avatar}
                              icon={!friend.avatar && <UserOutlined />}
                            />
                          }
                          title={friend.remark || friend.nickname}
                          description={friend.remark ? friend.nickname : ''}
                        />
                        {selectedChat?.id === friend.id && (
                          <CheckOutlined style={{ color: '#1677ff' }} />
                        )}
                      </List.Item>
                    )}
                    style={{ maxHeight: 300, overflowY: 'auto' }}
                  />
                )}
              </div>
            ),
          },
        ]}
      />
    )
  }

  /**
   * 渲染群成员选择
   */
  const renderMembersContent = () => {
    if (memberLoading) {
      return (
        <div style={{ textAlign: 'center', padding: '40px 0' }}>
          <Spin size="large" />
          <div style={{ marginTop: 16 }}>加载群成员...</div>
        </div>
      )
    }

    return (
      <div>
        <Divider orientation="left" style={{ margin: '8px 0' }}>
          已选择: {selectedChat?.name}
        </Divider>

        <div style={{ marginBottom: 12 }}>
          <Checkbox
            checked={selectedMembers.length === groupMembers.length && groupMembers.length > 0}
            indeterminate={selectedMembers.length > 0 && selectedMembers.length < groupMembers.length}
            onChange={e => handleSelectAllMembers(e.target.checked)}
          >
            全选（{groupMembers.length} 人）
          </Checkbox>
          <Text type="secondary" style={{ marginLeft: 12, fontSize: 12 }}>
            不选则监听所有用户
          </Text>
        </div>

        <Input.Search
          placeholder="搜索成员"
          value={searchText}
          onChange={e => setSearchText(e.target.value)}
          style={{ marginBottom: 12 }}
          allowClear
        />

        {filteredMembers.length === 0 ? (
          <Empty description="暂无成员" />
        ) : (
          <List
            dataSource={filteredMembers}
            renderItem={(member) => (
              <List.Item
                key={member.user_id}
                style={{ padding: '6px 12px' }}
              >
                <Checkbox
                  checked={selectedMembers.includes(member.user_id)}
                  onChange={e => handleMemberCheck(member.user_id, e.target.checked)}
                  style={{ marginRight: 12 }}
                />
                <List.Item.Meta
                  avatar={
                    <Avatar
                      size="small"
                      src={member.avatar}
                      icon={!member.avatar && <UserOutlined />}
                    />
                  }
                  title={
                    <Space>
                      <span>{member.card || member.nickname}</span>
                      {member.role === 'owner' && (
                        <Tag color="red" style={{ fontSize: 10 }}>群主</Tag>
                      )}
                      {member.role === 'admin' && (
                        <Tag color="blue" style={{ fontSize: 10 }}>管理员</Tag>
                      )}
                    </Space>
                  }
                  description={member.card ? member.nickname : ''}
                  style={{ marginBottom: 0 }}
                />
              </List.Item>
            )}
            style={{ maxHeight: 260, overflowY: 'auto' }}
          />
        )}

        <Button
          style={{ marginTop: 12 }}
          onClick={() => setActiveTab('contacts')}
        >
          ← 返回列表
        </Button>
      </div>
    )
  }

  return (
    <Modal
      title={
        <Space>
          <span>添加渠道</span>
          <Radio.Group
            value={activeChannel}
            onChange={e => setActiveChannel(e.target.value)}
            size="small"
          >
            <Radio.Button value="qq">QQ</Radio.Button>
            <Radio.Button value="wechat">微信</Radio.Button>
          </Radio.Group>
        </Space>
      }
      open={open}
      onCancel={() => {
        resetState()
        onCancel()
      }}
      onOk={handleConfirm}
      confirmLoading={confirmLoading}
      okText="添加"
      cancelText="取消"
      width={520}
      okButtonProps={{
        disabled: !selectedChat,
      }}
    >
      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        items={[
          {
            key: 'qrcode',
            label: '扫码登录',
            children: renderQrcodeContent(),
          },
          {
            key: 'contacts',
            label: '选择联系人',
            disabled: loginStatus?.status !== 'success',
            children: renderContactsContent(),
          },
          {
            key: 'members',
            label: '监听用户',
            disabled: !selectedChat || selectedChat.type !== 'group',
            children: renderMembersContent(),
          },
        ]}
      />

      {selectedChat && (
        <div
          style={{
            marginTop: 16,
            padding: 12,
            background: '#f6ffed',
            border: '1px solid #b7eb8f',
            borderRadius: 6,
          }}
        >
          <Space>
            <CheckOutlined style={{ color: '#52c41a' }} />
            <Text>
              已选择: <b>{selectedChat.name}</b>
              {selectedMembers.length > 0 && `（仅监听 ${selectedMembers.length} 人）`}
            </Text>
          </Space>
        </div>
      )}
    </Modal>
  )
}
