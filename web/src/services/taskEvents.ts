import { ApiError, expireSessionIfCurrent, getSessionRevision } from './http'
import type {
  IdentityKey,
  TaskEvent,
  TaskEventPayload,
  TaskPersistentEvent,
  TaskPersistentEventType,
  TaskResetReason,
  TaskSnapshotEvent,
  TaskStreamState,
} from '../types/taskEvent'

const MAX_FRAME_DATA_BYTES = 8 * 1024
const MAX_BUFFER_CHARS = 1 << 20
const RECONNECT_DELAY_MS = 1_000
const TERMINAL_STATUSES = new Set(['completed', 'failed', 'cancelled'])
const PERSISTENT_TYPES = new Set<TaskPersistentEventType>([
  'phase',
  'completed',
  'failed',
  'cancelled',
  'settled',
])
const RESET_REASONS = new Set<TaskResetReason>(['attempt_changed', 'cursor_expired', 'event_gap'])
const encoder = new TextEncoder()

type SseFrame = {
  id: string | null
  event: string | null
  data: string
  oversized: boolean
}

/**
 * SSE 文本帧解析器。支持 LF/CRLF/CR 换行、注释行、多行 data 拼接与一个 chunk
 * 内的多帧；单帧 data 超过 8KiB 时标记 oversized，由调用方断开降级。
 */
export class TaskEventFrameParser {
  private pending = ''
  private id: string | null = null
  private event: string | null = null
  private data: string[] = []
  private dataBytes = 0
  private oversized = false

  push(chunk: string): SseFrame[] {
    this.pending += chunk
    if (this.pending.length > MAX_BUFFER_CHARS) {
      // 无边界异常流的兜底保护：丢弃缓冲并按超大帧断开。
      this.pending = ''
      this.reset()
      return [{ id: null, event: null, data: '', oversized: true }]
    }
    const frames: SseFrame[] = []
    let start = 0
    for (;;) {
      const boundary = this.findLineEnd(start)
      if (!boundary) break
      this.consumeLine(this.pending.slice(start, boundary.end), frames)
      start = boundary.next
    }
    this.pending = this.pending.slice(start)
    return frames
  }

  /** 只清空当前帧草稿；pending 由 push 统一管理，清空会丢掉尚未扫描的缓冲。 */
  reset() {
    this.id = null
    this.event = null
    this.data = []
    this.dataBytes = 0
    this.oversized = false
  }

  /** 返回换行边界；行尾孤立 \r 可能是被 chunk 截断的 CRLF，留待下一片再判定。 */
  private findLineEnd(start: number): { end: number; next: number } | null {
    const lf = this.pending.indexOf('\n', start)
    const cr = this.pending.indexOf('\r', start)
    if (lf === -1 && cr === -1) return null
    if (cr === -1 || (lf !== -1 && lf < cr)) return { end: lf, next: lf + 1 }
    if (lf === cr + 1) return { end: cr, next: cr + 2 }
    if (cr === this.pending.length - 1) return null
    return { end: cr, next: cr + 1 }
  }

  private consumeLine(line: string, frames: SseFrame[]) {
    if (line === '') {
      const empty = this.id === null && this.event === null && this.data.length === 0
      if (empty && !this.oversized) return
      frames.push({
        id: this.id,
        event: this.event,
        data: this.data.join('\n'),
        oversized: this.oversized,
      })
      this.reset()
      return
    }
    if (line.startsWith(':')) return
    const colon = line.indexOf(':')
    const field = colon === -1 ? line : line.slice(0, colon)
    let value = colon === -1 ? '' : line.slice(colon + 1)
    if (value.startsWith(' ')) value = value.slice(1)
    if (field === 'id') this.id = value
    else if (field === 'event') this.event = value
    else if (field === 'data') {
      if (this.oversized) return
      const lineBytes = encoder.encode(value).length + 1
      if (this.dataBytes + lineBytes > MAX_FRAME_DATA_BYTES) {
        this.oversized = true
        this.data = []
        return
      }
      this.data.push(value)
      this.dataBytes += lineBytes
    }
  }
}

export type TaskCursor = { executionId: string; seq: number; attempt: number }

export type TaskEventOptions = {
  /** 如 '/qa/tasks/{id}/events' 的同源相对路径。 */
  path: string
  taskId: string
  identityKey: IdentityKey
  sessionRevision: number
  signal: AbortSignal
  onEvent: (event: TaskEvent) => void
  onState: (state: TaskStreamState) => void
}

type Outcome = { kind: 'stop' | 'aborted' | 'retry'; delayMs?: number }

const safeJson = (text: string): Record<string, unknown> | null => {
  try {
    const parsed: unknown = JSON.parse(text)
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : null
  } catch {
    return null
  }
}

const text = (value: unknown) => (typeof value === 'string' && value ? value : undefined)

function parseCursorId(taskId: string, id: string): TaskCursor | null {
  const separator = id.lastIndexOf(':')
  if (separator <= 0) return null
  const executionId = id.slice(0, separator)
  const prefix = `${taskId}.a`
  if (!executionId.startsWith(prefix)) return null
  const attempt = executionId.slice(prefix.length)
  if (!/^\d+$/.test(attempt)) return null
  const seq = Number(id.slice(separator + 1))
  if (!Number.isInteger(seq) || seq < 0) return null
  return { executionId, seq, attempt: Number(attempt) }
}

function sanitizePayload(raw: unknown): TaskEventPayload | null {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null
  const source = raw as Record<string, unknown>
  const status = text(source.status)
  if (!status) return null
  const payload: TaskEventPayload = { status, business_settled: source.business_settled === true }
  const stage = text(source.stage)
  if (stage) payload.stage = stage
  const errorCode = text(source.error_code)
  if (errorCode) payload.error_code = errorCode
  for (const field of ['session_id', 'message_id', 'course_id', 'lesson_id'] as const) {
    const value = text(source[field])
    if (value) payload[field] = value
  }
  const version = source.content_version
  if (typeof version === 'number' && Number.isInteger(version) && version >= 1)
    payload.content_version = version
  return payload
}

function toPayloadEvent(
  type: TaskPersistentEventType | 'snapshot',
  taskId: string,
  frame: SseFrame,
  raw: Record<string, unknown> | null,
): TaskPersistentEvent | TaskSnapshotEvent | null {
  const cursor = parseCursorId(taskId, frame.id || '')
  const payload = sanitizePayload(raw?.payload)
  if (!cursor || !payload || raw?.task_id !== taskId || raw.type !== type) return null
  if (type === 'snapshot')
    return { type: 'snapshot', ...cursor, payload, occurredAt: text(raw.occurred_at) || '' }
  return { type, ...cursor, payload, occurredAt: text(raw.occurred_at) || '' }
}

function toTaskEvent(taskId: string, frame: SseFrame): TaskEvent | null {
  if (frame.oversized || !frame.event) return null
  const raw = safeJson(frame.data)
  if (frame.event === 'reset') {
    const reason = raw?.reason
    if (
      raw?.task_id !== taskId ||
      typeof reason !== 'string' ||
      !RESET_REASONS.has(reason as TaskResetReason)
    )
      return null
    return { type: 'reset', reason: reason as TaskResetReason, executionId: text(raw.execution_id) || '' }
  }
  if (frame.event === 'source_revoked') {
    return raw?.task_id === taskId ? { type: 'source_revoked' } : null
  }
  if (frame.event === 'snapshot') return toPayloadEvent('snapshot', taskId, frame, raw)
  if (!frame.id || !PERSISTENT_TYPES.has(frame.event as TaskPersistentEventType)) return null
  return toPayloadEvent(frame.event as TaskPersistentEventType, taskId, frame, raw)
}

/**
 * 订阅任务阶段流。内部自带断线重连（携带 Last-Event-ID 游标）、按执行身份去重、
 * seq 严格递增与快照锚定；不可恢复的错误（401/403/404/503、来源撤销、超大帧）直接
 * 结束交给调用方兜底轮询，可重试失败的重连次数与降级时机由 useTaskEvents 决定。
 */
export async function subscribeTaskEvents(options: TaskEventOptions): Promise<void> {
  const { path, taskId, signal, onEvent, onState, sessionRevision: startedSession } = options
  if (!/^\/(?!\/)/.test(path) || path.includes('\\'))
    throw new ApiError('API 请求必须使用同源相对路径', 0, 'INVALID_URL')

  let cursor: TaskCursor | null = null
  let settled = false

  const dispatch = (event: TaskEvent) => {
    // 会话已切换时不再外发迟到事件；identity 变化由调用方 abort。
    if (startedSession !== getSessionRevision()) return
    if (event.type === 'reset') {
      // reset 不推进游标：清空后等待新快照重新锚定。
      cursor = null
    } else if (event.type === 'snapshot') {
      if (cursor && event.executionId === cursor.executionId && event.seq < cursor.seq) return
      cursor = { executionId: event.executionId, seq: event.seq, attempt: event.attempt }
      if (TERMINAL_STATUSES.has(event.payload.status) && event.payload.business_settled)
        settled = true
    } else if (event.type !== 'source_revoked') {
      if (!cursor) return
      if (event.executionId === cursor.executionId) {
        if (event.seq <= cursor.seq) return
        cursor = { ...cursor, seq: event.seq }
      } else {
        if (event.attempt <= cursor.attempt) return
        cursor = { executionId: event.executionId, seq: event.seq, attempt: event.attempt }
      }
      if (TERMINAL_STATUSES.has(event.payload.status) && event.payload.business_settled)
        settled = true
    }
    onEvent(event)
  }

  const sleep = (ms: number) =>
    new Promise<void>((resolve) => {
      let timer: ReturnType<typeof setTimeout>
      const finish = () => {
        clearTimeout(timer)
        signal.removeEventListener('abort', onAbort)
        resolve()
      }
      const onAbort = () => finish()
      timer = setTimeout(finish, ms)
      signal.addEventListener('abort', onAbort, { once: true })
      if (signal.aborted) finish()
    })

  const connectOnce = async (): Promise<Outcome> => {
    const attemptSession = getSessionRevision()
    // 每次连接使用全新解析器：断点残留的半帧不属于新连接。
    const parser = new TaskEventFrameParser()
    const decoder = new TextDecoder()
    const controller = new AbortController()
    const abort = () => controller.abort(signal.reason)
    signal.addEventListener('abort', abort, { once: true })
    try {
      const headers: Record<string, string> = { Accept: 'text/event-stream' }
      if (cursor) headers['Last-Event-ID'] = `${cursor.executionId}:${cursor.seq}`
      let response: Response
      try {
        response = await fetch(`/api/v1${path}`, {
          headers,
          credentials: 'include',
          signal: controller.signal,
        })
      } catch {
        return signal.aborted ? { kind: 'aborted' } : { kind: 'retry' }
      }
      if (!response.ok) {
        switch (response.status) {
          case 401:
            expireSessionIfCurrent(attemptSession)
            return { kind: 'stop' }
          case 403:
          case 404:
          case 503:
            // 无权、不存在或功能未开启：重连无意义，交给调用方兜底。
            return { kind: 'stop' }
          case 429: {
            const retryAfter = Number(response.headers.get('Retry-After'))
            return {
              kind: 'retry',
              delayMs: Number.isFinite(retryAfter)
                ? Math.min(Math.max(retryAfter, 1), 30) * 1000
                : RECONNECT_DELAY_MS,
            }
          }
          case 422:
            // 游标失效或超前：丢弃游标重取快照。
            cursor = null
            return { kind: 'retry', delayMs: 0 }
          default:
            return { kind: 'retry' }
        }
      }
      if (!/text\/event-stream/i.test(response.headers.get('Content-Type') || ''))
        return { kind: 'retry' }
      const reader = response.body?.getReader()
      if (!reader) return { kind: 'retry' }
      onState('streaming')
      const cancelOnAbort = () => void reader.cancel().catch(() => {})
      signal.addEventListener('abort', cancelOnAbort, { once: true })
      try {
        for (;;) {
          const { done, value } = await reader.read()
          if (done) break
          for (const frame of parser.push(decoder.decode(value, { stream: true }))) {
            if (frame.oversized) return { kind: 'stop' }
            const event = toTaskEvent(taskId, frame)
            if (!event) continue
            dispatch(event)
            if (event.type === 'source_revoked') return { kind: 'stop' }
          }
        }
        // 服务端正常收流：任务已收尾则结束，连接轮换则由外层携带游标重连。
        return settled ? { kind: 'stop' } : { kind: 'retry' }
      } catch (error) {
        return signal.aborted ? { kind: 'aborted' } : { kind: 'retry' }
      } finally {
        signal.removeEventListener('abort', cancelOnAbort)
      }
    } finally {
      signal.removeEventListener('abort', abort)
    }
  }

  onState('connecting')
  while (!signal.aborted && startedSession === getSessionRevision()) {
    const outcome = await connectOnce()
    if (outcome.kind !== 'retry' || signal.aborted || startedSession !== getSessionRevision())
      break
    onState('connecting')
    await sleep(outcome.delayMs ?? RECONNECT_DELAY_MS)
  }
  onState('closed')
}
