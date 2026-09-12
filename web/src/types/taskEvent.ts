/** 任务阶段 SSE 事件。字段与后端 app/models/task_event.py 的公开白名单一一对应；
 * 解析时只拷贝下列字段，未知字段不进入业务状态。 */

export type TaskPersistentEventType = 'phase' | 'completed' | 'failed' | 'cancelled' | 'settled'
export type TaskResetReason = 'attempt_changed' | 'cursor_expired' | 'event_gap'

export type TaskEventPayload = {
  status: string
  stage?: string
  error_code?: string
  business_settled: boolean
  session_id?: string
  message_id?: string
  course_id?: string
  lesson_id?: string
  content_version?: number
}

type TaskCursor = {
  executionId: string
  seq: number
  attempt: number
}

/** 持久事件（带 SSE id，断线可按游标续传）。 */
export type TaskPersistentEvent = TaskCursor & {
  type: TaskPersistentEventType
  payload: TaskEventPayload
  occurredAt: string
}

/** 授权快照；seq 为当前高水位（可为 0），允许同序号覆盖、不得倒退。 */
export type TaskSnapshotEvent = TaskCursor & {
  type: 'snapshot'
  payload: TaskEventPayload
  occurredAt: string
}

/** 控制帧（无 SSE id）：当前执行已失效，游标不推进，等待新快照重新锚定。 */
export type TaskResetEvent = {
  type: 'reset'
  reason: TaskResetReason
  executionId: string
}

/** 控制帧（无 SSE id）：来源授权已撤销，服务端随即关闭流。 */
export type TaskSourceRevokedEvent = {
  type: 'source_revoked'
}

export type TaskEvent =
  | TaskPersistentEvent
  | TaskSnapshotEvent
  | TaskResetEvent
  | TaskSourceRevokedEvent

export type TaskStreamState = 'connecting' | 'streaming' | 'polling' | 'closed'

/** 与 useIdentityKey 的返回值保持一致。 */
export type IdentityKey = number | 'guest'
