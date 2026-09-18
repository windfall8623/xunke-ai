import { ApiError, expireSessionIfCurrent, getSessionRevision } from './http'
import { TaskEventFrameParser } from './taskEvents'
import { emptyContentPreview, type ContentFrame, type ContentPreviewState } from '../types/contentEvent'

const kinds = new Set(['snapshot', 'delta', 'block', 'reset', 'finalized', 'unavailable', 'revoked'])

export function parseContentFrame(raw: unknown, taskId: string): ContentFrame | null {
  if (!raw || typeof raw !== 'object') return null
  const value = raw as ContentFrame
  if (value.schema_version !== 'xunke-content.v1' || value.task_id !== taskId
    || typeof value.execution_id !== 'string' || !value.execution_id.startsWith(taskId + '.a')
    || !/^\d+$/.test(value.execution_id.slice(taskId.length + 2))
    || !Number.isSafeInteger(value.generation_revision) || value.generation_revision < 1
    || !Number.isSafeInteger(value.seq) || value.seq < 0 || !kinds.has(value.type)
    || !value.payload || typeof value.payload !== 'object') return null
  const p = value.payload
  if (p.text !== undefined && (typeof p.text !== 'string' || p.text.length > 6000)) return null
  if (p.validated_blocks !== undefined && (!Array.isArray(p.validated_blocks) || p.validated_blocks.length > 30
    || p.validated_blocks.some(b => !b || typeof b.block_id !== 'string' || b.block_id.length > 80
      || typeof b.text !== 'string' || b.text.length > 6000 || !Array.isArray(b.source_refs)
      || b.source_refs.length > 20 || b.source_refs.some(ref => typeof ref !== 'string' || ref.length > 256)))) return null
  return value
}

export function applyContentFrame(state: ContentPreviewState, frame: ContentFrame): ContentPreviewState {
  const oldAttempt = Number(state.executionId?.split('.a').at(-1) || 0)
  const incomingAttempt = Number(frame.execution_id.split('.a').at(-1))
  if (state.taskId === frame.task_id && (incomingAttempt < oldAttempt
    || incomingAttempt === oldAttempt && frame.generation_revision < state.generationRevision)) return state
  const same = state.executionId === frame.execution_id && state.generationRevision === frame.generation_revision
  if (same && frame.seq < state.seq) return state
  const base = same && !['reset', 'snapshot'].includes(frame.type) ? state : {
    ...emptyContentPreview, taskId: frame.task_id, executionId: frame.execution_id,
    generationRevision: frame.generation_revision,
  }
  const next = { ...base, seq: frame.seq }
  if (frame.type === 'revoked' || frame.type === 'unavailable')
    return { ...next, text: '', blocks: [], status: frame.type }
  if (frame.type === 'finalized') return { ...next, status: 'finalized' }
  if (same && frame.seq === state.seq && !['reset', 'snapshot'].includes(frame.type)) return state
  if (frame.type === 'delta') return { ...next, status: 'streaming', text: (base.text + (frame.payload.text || '')).slice(0, 262144) }
  if (frame.type === 'block') {
    const blocks = [...base.blocks]
    for (const block of frame.payload.validated_blocks || []) {
      const index = blocks.findIndex(item => item.block_id === block.block_id)
      if (index < 0) blocks.push(block)
      else blocks[index] = block
    }
    return { ...next, status: 'streaming', blocks }
  }
  return { ...next, status: 'waiting' }
}

export type ContentSubscription = {
  kind: 'course' | 'qa'
  taskId: string
  signal: AbortSignal
  onFrame: (frame: ContentFrame) => void
  onInterrupted?: () => void
  onUnavailable?: () => void
}

export async function subscribeContentEvents({ kind, taskId, signal, onFrame, onInterrupted, onUnavailable }: ContentSubscription): Promise<void> {
  const session = getSessionRevision()
  const path = `/api/v1/${kind === 'course' ? 'courses' : 'qa'}/tasks/${encodeURIComponent(taskId)}/content-events`
  let cursor: string | undefined
  let failures = 0
  while (!signal.aborted && session === getSessionRevision() && failures < 3) {
    try {
      const headers = new Headers({ Accept: 'text/event-stream' })
      if (cursor) headers.set('Last-Event-ID', cursor)
      const response = await fetch(path, { credentials: 'include', headers, signal })
      if (!response.ok || !response.body || !response.headers.get('content-type')?.includes('text/event-stream')) {
        if (response.status === 401) expireSessionIfCurrent(session)
        if ([401, 403, 404, 409, 422, 503].includes(response.status)) {
          onUnavailable?.()
          return
        }
        throw new ApiError('正文预览连接中断', response.status, 'CONTENT_STREAM_UNAVAILABLE')
      }
      const reader = response.body.getReader()
      const parser = new TaskEventFrameParser()
      const decoder = new TextDecoder()
      try {
        while (!signal.aborted && session === getSessionRevision()) {
          const { done, value } = await reader.read()
          if (done) break
          for (const item of parser.push(decoder.decode(value, { stream: true }))) {
            if (item.oversized) throw new Error('content frame oversized')
            const frame = parseContentFrame(JSON.parse(item.data), taskId)
            if (!frame || item.event !== frame.type || item.id !== `${frame.execution_id}.g${frame.generation_revision}:${frame.seq}`)
              throw new Error('invalid content frame')
            if (signal.aborted || session !== getSessionRevision()) return
            cursor = item.id || undefined
            onFrame(frame)
            if (frame.type === 'delta' || frame.type === 'block') failures = 0
            if (['finalized', 'unavailable', 'revoked'].includes(frame.type)) return
          }
        }
      } finally {
        await reader.cancel().catch(() => {})
        reader.releaseLock()
      }
    } catch {
      if (signal.aborted || session !== getSessionRevision()) return
    }
    failures++
    onInterrupted?.()
    if (failures < 3) await new Promise<void>(resolve => {
      const stop = () => { clearTimeout(timer); signal.removeEventListener('abort', stop); resolve() }
      const timer = setTimeout(stop, 1000)
      signal.addEventListener('abort', stop, { once: true })
    })
  }
  if (!signal.aborted) onUnavailable?.()
}
