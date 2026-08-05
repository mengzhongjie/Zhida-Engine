import { Button, Input, Space, Typography } from 'antd'

export type PersonaPreset = { key: string; name: string; instruction: string }

export const defaultPersonaPresets: PersonaPreset[] = [
  { key: 'professional', name: '专业顾问', instruction: '你是一位专业顾问。表达严谨、准确、克制；先给明确结论，再说明依据与边界。' },
  { key: 'tutor', name: '耐心导师', instruction: '你是一位耐心导师。循序渐进地解释概念，必要时给出小例子和下一步建议，但不要居高临下。' },
  { key: 'friendly', name: '亲切伙伴', instruction: '你是一位亲切的知识伙伴。自然友好、易懂、有温度；避免空泛客套，重点帮助用户真正解决问题。' },
  { key: 'direct', name: '务实行动派', instruction: '你是一位务实的行动助手。先给可执行结论或步骤，语言直接、简短，避免重复题目和泛泛铺垫。' },
]

type Props = { value: string; customInstruction: string; onChange: (value: string) => void; onCustomInstructionChange: (value: string) => void; presets?: PersonaPreset[]; editablePreset?: boolean; onPresetInstructionChange?: (value: string) => void }

export default function PersonaPicker({ value, customInstruction, onChange, onCustomInstructionChange, presets = defaultPersonaPresets, editablePreset = false, onPresetInstructionChange }: Props) {
  const selected = presets.find(item => item.key === value)
  return <div className="persona-picker">
    <Space wrap size={[8, 8]}>{presets.map(item => <Button key={item.key} type={value === item.key ? 'primary' : 'default'} onClick={() => onChange(item.key)}>{item.name}</Button>)}<Button type={value === 'custom' ? 'primary' : 'dashed'} onClick={() => onChange('custom')}>自定义</Button></Space>
    {value === 'custom'
      ? <div className="persona-custom-editor"><Typography.Text type="secondary">自定义提示词会随每次回答生效，不能覆盖知识真实性和安全规则。</Typography.Text><Input.TextArea value={customInstruction} onChange={event => onCustomInstructionChange(event.target.value)} rows={5} maxLength={2000} placeholder="例如：你是一位面向新生的校园学长，语气真诚，先给结论，再给可执行建议。" /></div>
      : editablePreset ? <div className="persona-preset-editor"><Typography.Text type="secondary">修改后会同步更新使用“{selected?.name}”的其他 Agent。</Typography.Text><Input.TextArea value={selected?.instruction || ''} onChange={event => onPresetInstructionChange?.(event.target.value)} rows={4} maxLength={2000} /></div>
      : <Typography.Text className="persona-prompt-preview" type="secondary">{selected?.instruction || defaultPersonaPresets[0].instruction}</Typography.Text>}
  </div>
}
