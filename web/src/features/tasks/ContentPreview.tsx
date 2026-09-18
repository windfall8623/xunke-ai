import type { ContentPreviewState } from '../../types/contentEvent'

export function ContentPreview({ state, lesson = false }: { state: ContentPreviewState; lesson?: boolean }) {
  if (!state.text && !state.blocks.length) return null
  return <section className="content-preview" aria-live="off" aria-label={lesson ? '课文生成预览' : '回答生成预览'}>
    <p className="muted" role="status">{state.status === 'reconnecting' ? '连接中断，正在恢复当前内容…'
      : state.status === 'finalized' ? '已生成，正在读取完整内容…'
        : lesson ? '内容正在生成，教学检查尚未完成' : '回答正在生成，内容仍在检查中'}</p>
    {state.text && <p style={{ whiteSpace: 'pre-wrap' }}>{state.text}</p>}
    {state.blocks.map(block => <div key={block.block_id} style={{ whiteSpace: 'pre-wrap', marginBlock: '1rem' }}>
      {block.text}
      {block.source_refs.length > 0 && <small className="muted" style={{ display: 'block' }}>已核对引用范围 · 完整来源将在生成后显示</small>}
    </div>)}
  </section>
}
