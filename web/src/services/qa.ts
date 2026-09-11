import { request } from './http'
import type {
  QaEvidence,
  QaFeedback,
  QaFeedbackView,
  QaMessageCreate,
  QaMessageList,
  QaScopeUpdate,
  QaSession,
  QaSessionCreate,
  QaSessionList,
  QaTask,
} from '../types/qa'

const segment = encodeURIComponent
export const qaApi = {
  sessions: (page = 1, signal?: AbortSignal) =>
    request<QaSessionList>(`/qa/sessions?page=${page}&page_size=20`, { signal }),
  createSession: (data: QaSessionCreate, signal?: AbortSignal) =>
    request<QaSession>('/qa/sessions', { method: 'POST', data, signal }),
  session: (id: string, signal?: AbortSignal) =>
    request<QaSession>(`/qa/sessions/${segment(id)}`, { signal }),
  updateScope: (id: string, data: QaScopeUpdate, signal?: AbortSignal) =>
    request<QaSession>(`/qa/sessions/${segment(id)}/scope`, { method: 'PATCH', data, signal }),
  messages: (id: string, before?: number, signal?: AbortSignal) => {
    const params = new URLSearchParams({ page_size: '20' })
    if (before !== undefined) params.set('before_sequence', String(before))
    return request<QaMessageList>(`/qa/sessions/${segment(id)}/messages?${params}`, { signal })
  },
  ask: (id: string, data: QaMessageCreate, key: string, signal?: AbortSignal) =>
    request<QaTask>(`/qa/sessions/${segment(id)}/messages`, {
      method: 'POST',
      data,
      idempotencyKey: key,
      signal,
    }),
  task: (id: string, signal?: AbortSignal) =>
    request<QaTask>(`/qa/tasks/${segment(id)}`, { signal }),
  cancel: (id: string, signal?: AbortSignal) =>
    request<QaTask>(`/qa/tasks/${segment(id)}/cancel`, { method: 'POST', signal }),
  evidence: (answerId: string, evidenceId: string, signal?: AbortSignal) =>
    request<QaEvidence>(`/qa/answers/${segment(answerId)}/evidence/${segment(evidenceId)}`, {
      signal,
    }),
  feedback: (answerId: string, data: QaFeedback, signal?: AbortSignal) =>
    request<QaFeedbackView>(`/qa/answers/${segment(answerId)}/feedback`, {
      method: 'POST',
      data,
      signal,
    }),
}

export const qaKeys = {
  sessions: (identity: string | number) => [identity, 'qa', 'sessions'] as const,
  session: (identity: string | number, sessionId: string) =>
    [identity, 'qa', sessionId, 'session'] as const,
  messages: (identity: string | number, sessionId: string) =>
    [identity, 'qa', sessionId, 'messages'] as const,
  task: (identity: string | number, sessionId: string, taskId?: string) =>
    [identity, 'qa', sessionId, 'task', taskId] as const,
  evidence: (identity: string | number, sessionId: string) =>
    [identity, 'qa', sessionId, 'evidence'] as const,
}
