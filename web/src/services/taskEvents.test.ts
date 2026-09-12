import { afterEach, describe, expect, it, vi } from 'vitest'
import { setCsrfToken } from './http'
import { subscribeTaskEvents, TaskEventFrameParser } from './taskEvents'
import type { TaskEvent, TaskStreamState } from '../types/taskEvent'

const encoder = new TextEncoder()

afterEach(() => {
  vi.unstubAllGlobals()
  setCsrfToken(null)
})

const eventFrame = (
  seq: number,
  attempt: number,
  type: string,
  payload: Record<string, unknown>,
) =>
  `id: task-1.a${attempt}:${seq}\nevent: ${type}\ndata: ${JSON.stringify({
    schema_version: 1,
    task_id: 'task-1',
    execution_id: `task-1.a${attempt}`,
    seq,
    attempt,
    type,
    payload,
    occurred_at: '2026-09-12T08:00:00Z',
  })}\n\n`

const sseResponse = (...chunks: Uint8Array[]) =>
  new Response(
    new ReadableStream<Uint8Array>({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(chunk)
        controller.close()
      },
    }),
    { status: 200, headers: { 'Content-Type': 'text/event-stream' } },
  )

const hangingResponse = () =>
  new Response(new ReadableStream<Uint8Array>({ start() {} }), {
    status: 200,
    headers: { 'Content-Type': 'text/event-stream' },
  })

const jsonError = (status: number, errorCode: string) =>
  new Response(JSON.stringify({ code: status * 10, error_code: errorCode, message: 'x', data: null }), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })

const concat = (...parts: Uint8Array[]) => {
  const total = parts.reduce((sum, part) => sum + part.length, 0)
  const out = new Uint8Array(total)
  let offset = 0
  for (const part of parts) {
    out.set(part, offset)
    offset += part.length
  }
  return out
}

function startSubscriber(fetchMock: ReturnType<typeof vi.fn>) {
  vi.stubGlobal('fetch', fetchMock)
  const controller = new AbortController()
  const events: TaskEvent[] = []
  const states: TaskStreamState[] = []
  const pending = subscribeTaskEvents({
    path: '/qa/tasks/task-1/events',
    taskId: 'task-1',
    identityKey: 1,
    sessionRevision: 0,
    signal: controller.signal,
    onEvent: (event) => events.push(event),
    onState: (state) => states.push(state),
  })
  return { controller, events, states, pending }
}

const requestHeaders = (fetchMock: ReturnType<typeof vi.fn>, call: number) =>
  new Headers((fetchMock.mock.calls[call] as [string, RequestInit])[1]?.headers)

const eventPayload = (event: TaskEvent) => {
  if (event.type === 'reset' || event.type === 'source_revoked')
    throw new Error(`unexpected control frame: ${event.type}`)
  return event.payload
}

describe('task event frame parser', () => {
  it('splits CRLF and LF frames and joins multi-line data', () => {
    const parser = new TaskEventFrameParser()
    const frames = parser.push(
      'id: task-1.a1:1\r\nevent: phase\r\ndata: {"a":1}\ndata: {"b":2}\n\n: keepalive\n\n',
    )
    expect(frames).toHaveLength(1)
    expect(frames[0]).toMatchObject({ id: 'task-1.a1:1', event: 'phase', data: '{"a":1}\n{"b":2}' })
  })
})

describe('task event stream', () => {
  it('reassembles Chinese UTF-8 across chunks, multi-frame chunks and comment lines, then reconnects with the last cursor', async () => {
    // 后端契约：无游标首连先发快照，再补读事件。
    const snapshot = eventFrame(0, 1, 'snapshot', {
      status: 'running',
      stage: 'queued',
      business_settled: false,
    })
    const first = eventFrame(1, 1, 'phase', {
      status: 'running',
      stage: '正在生成回答',
      business_settled: false,
    })
    const second = eventFrame(2, 1, 'phase', {
      status: 'running',
      stage: '正在筛选依据',
      business_settled: false,
    })
    const snapshotBytes = encoder.encode(snapshot)
    const firstBytes = encoder.encode(first)
    const cut = first.indexOf('正') + 1 // 帧前缀均为 ASCII；切点落在“正”的三个字节内部
    const fetchMock = vi
      .fn()
      .mockImplementationOnce(async () =>
        // 帧一跨两个 chunk（多字节字符被截断）；帧二与保活注释、帧一尾部同在一个 chunk。
        sseResponse(
          concat(snapshotBytes, firstBytes.slice(0, cut)),
          concat(firstBytes.slice(cut), encoder.encode(`: keepalive\n\n${second}`)),
        ),
      )
      .mockImplementation(async () => hangingResponse())
    const { controller, events, pending } = startSubscriber(fetchMock)
    await vi.waitFor(() => expect(events.length).toBe(3), { timeout: 4000 })
    expect(events.map((event) => event.type)).toEqual(['snapshot', 'phase', 'phase'])
    expect(eventPayload(events[1]).stage).toBe('正在生成回答')
    expect(eventPayload(events[2]).stage).toBe('正在筛选依据')
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2), { timeout: 4000 })
    expect(requestHeaders(fetchMock, 1).get('Last-Event-ID')).toBe('task-1.a1:2')
    controller.abort()
    await pending
  })

  it('does not advance the cursor on reset and drops events from the stale execution', async () => {
    const snapshot = eventFrame(5, 1, 'snapshot', {
      status: 'running',
      stage: 'generating',
      business_settled: false,
    })
    const phase = eventFrame(6, 1, 'phase', {
      status: 'running',
      stage: 'retrieving',
      business_settled: false,
    })
    const stale = eventFrame(7, 1, 'phase', {
      status: 'running',
      stage: 'generating',
      business_settled: false,
    })
    const reset =
      'event: reset\ndata: {"schema_version":1,"task_id":"task-1","type":"reset","reason":"attempt_changed","execution_id":"task-1.a2"}\n\n'
    const reSnapshot = eventFrame(9, 2, 'snapshot', {
      status: 'failed',
      stage: 'failed',
      business_settled: false,
      error_code: 'LLM_UNAVAILABLE',
    })
    const fetchMock = vi
      .fn()
      .mockImplementationOnce(async () =>
        sseResponse(
          encoder.encode(snapshot + phase + reset + stale + reSnapshot),
        ),
      )
      .mockImplementation(async () => hangingResponse())
    const { controller, events, pending } = startSubscriber(fetchMock)
    await vi.waitFor(() => expect(events.length).toBe(4), { timeout: 4000 })
    expect(events.map((event) => event.type)).toEqual(['snapshot', 'phase', 'reset', 'snapshot'])
    // reset 清空游标：旧执行的 seq=7 事件被丢弃，新快照重新锚定游标。
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2), { timeout: 4000 })
    expect(requestHeaders(fetchMock, 1).get('Last-Event-ID')).toBe('task-1.a2:9')
    controller.abort()
    await pending
  })

  it('applies seq strictly increasingly, ignores stale snapshots and allows same-seq snapshot refresh', async () => {
    const base = { status: 'running', business_settled: false }
    const snapshot5 = eventFrame(5, 1, 'snapshot', { ...base, stage: 'generating' })
    const phase6 = eventFrame(6, 1, 'phase', { ...base, stage: 'retrieving' })
    const duplicate6 = eventFrame(6, 1, 'phase', { ...base, stage: 'generating' })
    const older4 = eventFrame(4, 1, 'phase', { ...base, stage: 'queued' })
    const staleSnapshot4 = eventFrame(4, 1, 'snapshot', { ...base, stage: 'queued' })
    const refresh6 = eventFrame(6, 1, 'snapshot', { ...base, stage: 'retrieving' })
    const fetchMock = vi
      .fn()
      .mockImplementationOnce(async () =>
        sseResponse(
          encoder.encode(snapshot5 + phase6 + duplicate6 + older4 + staleSnapshot4 + refresh6),
        ),
      )
      .mockImplementation(async () => hangingResponse())
    const { controller, events, pending } = startSubscriber(fetchMock)
    await vi.waitFor(() => expect(events.length).toBe(3), { timeout: 4000 })
    expect(events.map((event) => event.type)).toEqual(['snapshot', 'phase', 'snapshot'])
    expect(eventPayload(events[2]).stage).toBe('retrieving')
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2), { timeout: 4000 })
    expect(requestHeaders(fetchMock, 1).get('Last-Event-ID')).toBe('task-1.a1:6')
    controller.abort()
    await pending
  })

  it('disconnects permanently when a single frame exceeds 8KiB so callers fall back to polling', async () => {
    const snapshot = eventFrame(1, 1, 'snapshot', {
      status: 'running',
      stage: 'generating',
      business_settled: false,
    })
    const oversized =
      'id: task-1.a1:2\nevent: phase\ndata: {"schema_version":1,"task_id":"task-1","execution_id":"task-1.a1","seq":2,"attempt":1,"type":"phase","payload":{"status":"running","stage":"' +
      '长'.repeat(5000) +
      '"},"occurred_at":"2026-09-12T08:00:00Z"}\n\n'
    const fetchMock = vi
      .fn()
      .mockImplementationOnce(async () => sseResponse(encoder.encode(snapshot + oversized)))
    const { controller, events, states, pending } = startSubscriber(fetchMock)
    await vi.waitFor(() => expect(states[states.length - 1]).toBe('closed'), { timeout: 4000 })
    expect(events).toHaveLength(1)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    controller.abort()
    await pending
    expect(states[states.length - 1]).toBe('closed')
  })

  it('drops the cursor after an invalid_cursor rejection and reconnects without Last-Event-ID', async () => {
    const snapshot = eventFrame(5, 1, 'snapshot', {
      status: 'running',
      stage: 'generating',
      business_settled: false,
    })
    const fetchMock = vi
      .fn()
      .mockImplementationOnce(async () => sseResponse(encoder.encode(snapshot)))
      .mockImplementationOnce(async () => jsonError(422, 'invalid_cursor'))
      .mockImplementation(async () => hangingResponse())
    const { controller, pending } = startSubscriber(fetchMock)
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3), { timeout: 4000 })
    expect(requestHeaders(fetchMock, 1).get('Last-Event-ID')).toBe('task-1.a1:5')
    expect(requestHeaders(fetchMock, 2).has('Last-Event-ID')).toBe(false)
    controller.abort()
    await pending
  })
})
