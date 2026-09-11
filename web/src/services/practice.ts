import { ApiError, request } from './http'
import { studyErrorMessage } from './study'
import type {
  Practice,
  PracticeAnswerBody,
  PracticeAttempt,
  PracticeCompletion,
  PracticeReceipt,
  PracticeSpec,
  PracticeTask,
  ReviewPracticeBody,
  PracticeEvidence,
  PracticeCost,
  PracticeHelp,
  PracticeReviewContext,
  PracticeReviewBody,
  PracticeAssessmentRef,
  PracticeSelfReviewBody,
  PracticeSelfReviewReceipt,
} from '../types/practice'

const part = encodeURIComponent
export const generatePractice = (data: PracticeSpec, key: string, signal?: AbortSignal) =>
  request<PracticeTask>('/practice/generate/async', {
    method: 'POST',
    data,
    idempotencyKey: key,
    signal,
  })
export const generateReviewPractice = (
  data: ReviewPracticeBody,
  key: string,
  signal?: AbortSignal,
) =>
  request<PracticeTask>('/practice/review-jobs', {
    method: 'POST',
    data,
    idempotencyKey: key,
    signal,
  })
export const getPractice = (id: string, signal?: AbortSignal) =>
  request<Practice>(`/practice/${part(id)}`, { signal })
export const getPracticeTask = (id: string, signal?: AbortSignal) =>
  request<PracticeTask>(`/practice/tasks/${part(id)}`, { signal })
export const cancelPracticeTask = (id: string, signal?: AbortSignal) =>
  request<PracticeTask>(`/practice/tasks/${part(id)}/cancel`, { method: 'POST', signal })
export const submitPracticeAnswer = (
  id: string,
  questionId: string,
  data: PracticeAnswerBody,
  key: string,
  signal?: AbortSignal,
) =>
  request<PracticeReceipt>(`/practice/${part(id)}/questions/${part(questionId)}/attempts`, {
    method: 'POST',
    data,
    idempotencyKey: key,
    signal,
  })
export const completePractice = (id: string, revision: number, signal?: AbortSignal) =>
  request<PracticeCompletion>(`/practice/${part(id)}/complete`, {
    method: 'POST',
    data: { expected_revision: revision },
    signal,
  })
export const getPracticeAttempt = (id: string, signal?: AbortSignal) =>
  request<PracticeAttempt>(`/practice/attempts/${part(id)}`, { signal })
export const markPracticeHelp = (id: string, questionId: string, signal?: AbortSignal) =>
  request<PracticeHelp>(`/practice/${part(id)}/questions/${part(questionId)}/help`, {
    method: 'POST',
    signal,
  })
export const retryPracticeGrading = (id: string, key: string, signal?: AbortSignal) =>
  request<PracticeTask>(`/practice/attempts/${part(id)}/retry-grading`, {
    method: 'POST',
    idempotencyKey: key,
    signal,
  })

export const getPracticeEvidence = (
  id: string,
  questionId: string,
  evidenceId: string,
  signal?: AbortSignal,
) =>
  request<PracticeEvidence>(
    `/practice/${part(id)}/questions/${part(questionId)}/evidence/${part(evidenceId)}`,
    { signal },
  )
export const previewPracticeCost = (data: PracticeSpec, signal?: AbortSignal) =>
  request<PracticeCost>('/practice/cost-preview', { method: 'POST', data, signal })

export const getPracticeReviewContext = (id: string, signal?: AbortSignal) =>
  request<PracticeReviewContext>(`/practice/attempts/${part(id)}/review-context`, { signal })
export const reviewPracticeAttempt = (
  id: string,
  data: PracticeReviewBody,
  key: string,
  signal?: AbortSignal,
) =>
  request<PracticeAssessmentRef>(`/practice/attempts/${part(id)}/review`, {
    method: 'POST',
    data,
    idempotencyKey: key,
    signal,
  })
export const selfReviewPracticeAttempt = (
  id: string,
  data: PracticeSelfReviewBody,
  key: string,
  signal?: AbortSignal,
) =>
  request<PracticeSelfReviewReceipt>(`/practice/attempts/${part(id)}/self-review`, {
    method: 'POST',
    data,
    idempotencyKey: key,
    signal,
  })

export const practiceKeys = {
  all: (identity: string | number) => [identity, 'practice'] as const,
  practice: (identity: string | number, id: string) => [identity, 'practice', id] as const,
  task: (identity: string | number, id: string) => [identity, 'practice-task', id] as const,
  attempt: (identity: string | number, id: string) => [identity, 'practice-attempt', id] as const,
  reviewContext: (identity: string | number, id: string) =>
    [identity, 'practice-review-context', id] as const,
}

export function practiceErrorMessage(error: unknown) {
  if (error instanceof ApiError) {
    if (error.code === 'short_answer_grading_unavailable')
      return '短解释评分暂不可用，请先选择填空或数值题。'
    if (error.code === 'help_ack_required') return '请先确认查看资料提示，再读取这道题的依据。'
    if (error.code === 'answer_already_submitted') return '这道题已有已保存的答案，正在刷新原作答。'
    if (error.code === 'evaluator_required') return '此操作需要本账号的评阅权限。'
    if (error.status === 422) return '答案格式不正确，请核对每个空、数值和单位后重新提交。'
  }
  return studyErrorMessage(error)
}
