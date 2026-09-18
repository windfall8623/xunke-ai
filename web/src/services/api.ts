import { request } from './http'
import type {
  AnswerReceipt,
  ApiSchemas,
  AuthSession,
  CompletionReceipt,
  DocumentItem,
  Evidence,
  Feedback,
  GenerateRequest,
  HistoryItem,
  Page,
  Profile,
  Quiz,
  Report,
  Task,
} from '../types/api'

export type LlmSettingsInput = ApiSchemas['LLMConfigRequest']
export type LlmProvider = LlmSettingsInput['provider']
export type LlmSettings = ApiSchemas['LLMConfigView']

// Only public metadata belongs in the query cache, even if a server adds fields.
function llmMetadata(data: LlmSettings): LlmSettings {
  return {
    configured: data.configured,
    provider: data.provider,
    model: data.model,
    base_url: data.base_url,
    api_key_hint: data.api_key_hint,
    can_use_system: data.can_use_system,
    source: data.source,
  }
}

const segment = encodeURIComponent
export const api = {
  authCapabilities: (signal?: AbortSignal) =>
    request<ApiSchemas['AuthCapabilitiesView']>('/auth/capabilities', { signal }),
  session: (signal?: AbortSignal) => request<AuthSession>('/auth/session', { signal }),
  login: (data: ApiSchemas['LoginBody']) =>
    request<AuthSession>('/auth/login', { method: 'POST', data }),
  sendEmailCode: (data: ApiSchemas['EmailCodeBody']) =>
    request<ApiSchemas['EmailCodeView']>('/auth/email-code', { method: 'POST', data }),
  register: (data: ApiSchemas['RegisterBody']) =>
    request<AuthSession>('/auth/register', { method: 'POST', data }),
  bindLegacy: (
    data: Pick<ApiSchemas['BindBody'], 'account' | 'password' | 'code' | 'verification_code'>,
  ) => request<AuthSession>('/auth/bind', { method: 'POST', data }),
  recover: (data: ApiSchemas['RecoverBody']) =>
    request<{ recovery_code?: string }>('/auth/recover', { method: 'POST', data }),
  resetPasswordWithEmailCode: (data: ApiSchemas['PasswordResetBody']) =>
    request<AuthSession>('/auth/password/reset', { method: 'POST', data }),
  taskOverview: (signal?: AbortSignal) =>
    request<ApiSchemas['TaskOverviewView']>('/tasks/active', { signal }),
  logout: () => request<null>('/auth/logout', { method: 'POST' }),
  changePassword: (data: ApiSchemas['PasswordBody']) =>
    request<null>('/auth/change-password', { method: 'POST', data }),
  llmSettings: (signal?: AbortSignal) =>
    request<LlmSettings>('/me/llm', { signal }).then(llmMetadata),
  saveLlmSettings: (data: LlmSettingsInput, signal?: AbortSignal) =>
    request<LlmSettings>('/me/llm', { method: 'PUT', data, signal, timeoutMs: 60_000 }).then(
      llmMetadata,
    ),
  deleteLlmSettings: (signal?: AbortSignal) =>
    request<LlmSettings>('/me/llm', { method: 'DELETE', signal }).then(llmMetadata),
  profile: (signal?: AbortSignal) => request<Profile>('/user/profile', { signal }),
  updateProfile: (nickname: string) =>
    request<null>('/user/profile', { method: 'PUT', data: { nickname } }),
  avatar: (file: File) => {
    const data = new FormData()
    data.append('file', file)
    return request<ApiSchemas['AvatarUploadResponse']>('/user/avatar', { method: 'POST', data })
  },
  history: (page = 1, signal?: AbortSignal) =>
    request<Page<HistoryItem>>(`/user/quizzes?page=${page}&page_size=10`, { signal }),
  generate: (data: GenerateRequest, key: string) =>
    request<Task>('/quiz/generate/async', {
      method: 'POST',
      data,
      idempotencyKey: key,
    }),
  task: (id: string, signal?: AbortSignal) =>
    request<Task>(`/quiz/task/${segment(id)}`, { signal }),
  quiz: (id: string, signal?: AbortSignal) =>
    request<Quiz>(`/user/quizzes/${segment(id)}`, { signal }),
  answer: (quizId: string, questionId: string, data: ApiSchemas['AnswerBody']) =>
    request<AnswerReceipt>(`/quiz/${segment(quizId)}/answers/${segment(questionId)}`, {
      method: 'PUT',
      data,
    }),
  complete: (id: string, revision: number, key: string) =>
    request<CompletionReceipt>(`/quiz/${segment(id)}/complete`, {
      method: 'POST',
      data: { expected_revision: revision },
      idempotencyKey: key,
    }),
  report: (id: string, signal?: AbortSignal) =>
    request<Report>(`/report/${segment(id)}`, { signal }),
  retryReport: (id: string) =>
    request<ApiSchemas['ReportRetryView']>(`/report/${segment(id)}/retry`, { method: 'POST' }),
  documents: (signal?: AbortSignal) =>
    request<Page<DocumentItem>>('/knowledge/documents', { signal }),
  document: (id: string, signal?: AbortSignal) =>
    request<DocumentItem>(`/knowledge/documents/${segment(id)}`, { signal }),
  upload: (file: File, docId?: string) => {
    const data = new FormData()
    data.append('file', file)
    return request<DocumentItem>(
      `/knowledge/documents${docId ? `/${segment(docId)}/versions` : ''}`,
      { method: 'POST', data, timeoutMs: 120_000 },
    )
  },
  reindex: (
    id: string,
    indexProfile: ApiSchemas['ReindexBody']['index_profile_id'] = 'legacy-char-v1',
  ) =>
    request<DocumentItem>(`/knowledge/documents/${segment(id)}/reindex`, {
      method: 'POST',
      data: { index_profile_id: indexProfile },
    }),
  deleteDocument: (id: string) =>
    request<ApiSchemas['DocumentDeletionView']>(`/knowledge/documents/${segment(id)}`, {
      method: 'DELETE',
    }),
  evidence: (quizId: string, evidenceId: string, signal?: AbortSignal) =>
    request<Evidence>(`/quiz/${segment(quizId)}/evidence/${segment(evidenceId)}`, { signal }),
  feedback: (quizId: string, data: Feedback) =>
    request<{ feedback_id: string }>(`/quiz/${segment(quizId)}/feedback`, { method: 'POST', data }),
}
