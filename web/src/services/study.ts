import { ApiError, request } from './http'
import type { Task } from '../types/api'
import type {
  StudyConcept,
  StudyConceptCreate,
  StudyConceptList,
  StudyConceptUpdate,
  StudyGoal,
  StudyGoalCreate,
  StudyGoalList,
  StudyGoalUpdate,
  StudyQaPracticeContext,
  StudyQuizFromQa,
  StudyScopeUpdate,
  StudyScopeView,
  StudySpace,
  StudySpaceCreate,
  StudySpaceList,
  StudySpaceUpdate,
  StudyUnit,
  StudyUnitCreate,
  StudyUnitList,
  StudyUnitReorder,
  StudyUnitUpdate,
  StudyReview,
  StudyReviewList,
  StudyReviewUpdate,
  StudyReviewQuiz,
  StudyHistoryList,
  StudyWrongQuestionList,
  StudyConceptProgress,
  StudyListFilters,
} from '../types/study'

const segment = encodeURIComponent
const filterQuery = (filters: StudyListFilters = {}) =>
  new URLSearchParams(
    Object.entries(filters)
      .filter(([, value]) => value !== undefined && value !== '')
      .map(([key, value]) => [key, String(value)]),
  ).toString()
export const studyApi = {
  reviews: (filters: StudyListFilters = {}, signal?: AbortSignal) =>
    request<StudyReviewList>(`/study/reviews?${filterQuery(filters)}`, { signal }),
  updateReview: (id: string, data: StudyReviewUpdate, signal?: AbortSignal) =>
    request<StudyReview>(`/study/reviews/${segment(id)}`, { method: 'PATCH', data, signal }),
  reviewQuiz: (data: StudyReviewQuiz, key: string, signal?: AbortSignal) =>
    request<Task>('/study/review-quiz-jobs', { method: 'POST', data, idempotencyKey: key, signal }),
  history: (filters: StudyListFilters = {}, signal?: AbortSignal) =>
    request<StudyHistoryList>(`/study/history?${filterQuery(filters)}`, { signal }),
  wrongQuestions: (filters: StudyListFilters = {}, signal?: AbortSignal) =>
    request<StudyWrongQuestionList>(`/study/wrong-questions?${filterQuery(filters)}`, { signal }),
  conceptProgress: (id: string, signal?: AbortSignal) =>
    request<StudyConceptProgress>(`/study/concepts/${segment(id)}/progress`, { signal }),
  spaces: (page = 1, status?: StudySpace['status'], signal?: AbortSignal) => {
    const params = new URLSearchParams({ page: String(page), page_size: '20' })
    if (status) params.set('status', status)
    return request<StudySpaceList>(`/study/spaces?${params}`, { signal })
  },
  space: (id: string, signal?: AbortSignal) =>
    request<StudySpace>(`/study/spaces/${segment(id)}`, { signal }),
  createSpace: (data: StudySpaceCreate, key: string, signal?: AbortSignal) =>
    request<StudySpace>('/study/spaces', { method: 'POST', data, idempotencyKey: key, signal }),
  updateSpace: (id: string, data: StudySpaceUpdate, signal?: AbortSignal) =>
    request<StudySpace>(`/study/spaces/${segment(id)}`, { method: 'PATCH', data, signal }),
  updateScope: (id: string, data: StudyScopeUpdate, signal?: AbortSignal) =>
    request<StudySpace>(`/study/spaces/${segment(id)}/scope`, { method: 'PATCH', data, signal }),
  scope: (id: string, revision: number, signal?: AbortSignal) =>
    request<StudyScopeView>(`/study/spaces/${segment(id)}/scopes/${revision}`, { signal }),
  goals: (spaceId: string, signal?: AbortSignal) =>
    request<StudyGoalList>(`/study/spaces/${segment(spaceId)}/goals`, { signal }),
  createGoal: (spaceId: string, data: StudyGoalCreate, signal?: AbortSignal) =>
    request<StudyGoal>(`/study/spaces/${segment(spaceId)}/goals`, { method: 'POST', data, signal }),
  updateGoal: (id: string, data: StudyGoalUpdate, signal?: AbortSignal) =>
    request<StudyGoal>(`/study/goals/${segment(id)}`, { method: 'PATCH', data, signal }),
  units: (goalId: string, signal?: AbortSignal) =>
    request<StudyUnitList>(`/study/goals/${segment(goalId)}/units`, { signal }),
  createUnit: (goalId: string, data: StudyUnitCreate, signal?: AbortSignal) =>
    request<StudyUnit>(`/study/goals/${segment(goalId)}/units`, { method: 'POST', data, signal }),
  updateUnit: (id: string, data: StudyUnitUpdate, signal?: AbortSignal) =>
    request<StudyUnit>(`/study/units/${segment(id)}`, { method: 'PATCH', data, signal }),
  reorderUnits: (goalId: string, data: StudyUnitReorder, signal?: AbortSignal) =>
    request<StudyUnitList>(`/study/goals/${segment(goalId)}/units/order`, {
      method: 'PATCH',
      data,
      signal,
    }),
  concepts: (spaceId: string, signal?: AbortSignal) =>
    request<StudyConceptList>(`/study/spaces/${segment(spaceId)}/concepts`, { signal }),
  createConcept: (spaceId: string, data: StudyConceptCreate, signal?: AbortSignal) =>
    request<StudyConcept>(`/study/spaces/${segment(spaceId)}/concepts`, {
      method: 'POST',
      data,
      signal,
    }),
  updateConcept: (id: string, data: StudyConceptUpdate, signal?: AbortSignal) =>
    request<StudyConcept>(`/study/concepts/${segment(id)}`, { method: 'PATCH', data, signal }),
  practiceContext: (answerId: string, signal?: AbortSignal) =>
    request<StudyQaPracticeContext>(`/study/qa-answers/${segment(answerId)}/practice-context`, {
      signal,
    }),
  quizFromQa: (data: StudyQuizFromQa, key: string, signal?: AbortSignal) =>
    request<Task>('/study/quiz-jobs/from-qa', {
      method: 'POST',
      data,
      idempotencyKey: key,
      signal,
    }),
}

export const studyKeys = {
  all: (identity: string | number) => [identity, 'study'] as const,
  reviews: (identity: string | number, filters: StudyListFilters = {}) =>
    [identity, 'study', 'reviews', filters] as const,
  history: (identity: string | number, filters: StudyListFilters = {}) =>
    [identity, 'study', 'history', filters] as const,
  wrongQuestions: (identity: string | number, filters: StudyListFilters = {}) =>
    [identity, 'study', 'wrong-questions', filters] as const,
  progress: (identity: string | number, conceptId: string) =>
    [identity, 'study', 'progress', conceptId] as const,
  spaces: (identity: string | number, page = 1, status?: StudySpace['status']) =>
    [identity, 'study', 'spaces', status || 'all', page] as const,
  space: (identity: string | number, spaceId: string) =>
    [identity, 'study', 'space', spaceId] as const,
  scope: (identity: string | number, spaceId: string, revision: number) =>
    [identity, 'study', 'space', spaceId, 'scope', revision] as const,
  goals: (identity: string | number, spaceId: string) =>
    [identity, 'study', 'space', spaceId, 'goals'] as const,
  concepts: (identity: string | number, spaceId: string) =>
    [identity, 'study', 'space', spaceId, 'concepts'] as const,
  units: (identity: string | number, spaceId: string, goalId: string) =>
    [identity, 'study', 'space', spaceId, 'goal', goalId, 'units'] as const,
  practiceContext: (identity: string | number, answerId: string) =>
    [identity, 'study', 'qa', answerId, 'practice-context'] as const,
}

export const studyUnavailable = (error: unknown) =>
  error instanceof ApiError && [403, 404, 410].includes(error.status)
export const studyConflict = (error: unknown) => error instanceof ApiError && error.status === 409
export const studyUncertain = (error: unknown) =>
  error instanceof ApiError &&
  (error.status === 0 || error.status >= 500 || error.code === 'INVALID_RESPONSE')

export function studyErrorMessage(error: unknown) {
  if (studyUnavailable(error)) return '资料已不可用或访问权限已变更，相关学习内容已隐藏。'
  if (studyConflict(error)) return '内容已更新，请重新核对后再保存。'
  if (studyUncertain(error)) return '提交结果尚未确认，请检查网络后重试。'
  if (error instanceof ApiError && error.status === 401) return '登录已失效，请重新登录。'
  return '操作未完成，请检查所填内容后重试。'
}

/** Only fingerprints and operation keys are persisted, under the existing auth cleanup prefix. */
export function createStudySubmissionKeys(identity: string | number, entry: string) {
  const memory = new Map<string, string>()
  const fingerprints = new Map<string, string>()
  const storageName = (operation: 'space' | 'quiz') =>
    `qa-submission:${identity}:study:${entry}:${operation}`
  const keyFor = async (operation: 'space' | 'quiz', semanticRequest: string) => {
    const semantic = `${operation}:${semanticRequest}`
    const remembered = memory.get(semantic)
    if (remembered) return remembered
    let fingerprint: string | undefined
    let persisted: Record<string, string> = {}
    const storageKey = storageName(operation)
    try {
      const bytes = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(semantic))
      fingerprint = Array.from(new Uint8Array(bytes), (byte) =>
        byte.toString(16).padStart(2, '0'),
      ).join('')
      fingerprints.set(semantic, fingerprint)
      const candidate: unknown = JSON.parse(sessionStorage.getItem(storageKey) || '{}')
      if (candidate && typeof candidate === 'object' && !Array.isArray(candidate)) {
        persisted = Object.fromEntries(
          Object.entries(candidate).filter(
            ([hash, key]) =>
              /^[a-f0-9]{64}$/.test(hash) &&
              typeof key === 'string' &&
              /^[a-zA-Z0-9-]{1,128}$/.test(key),
          ),
        )
      }
    } catch {
      // Memory still protects retries when Web Crypto or storage is unavailable.
    }
    const key = (fingerprint && persisted[fingerprint]) || crypto.randomUUID()
    memory.set(semantic, key)
    if (fingerprint) {
      try {
        sessionStorage.setItem(storageKey, JSON.stringify({ ...persisted, [fingerprint]: key }))
      } catch {
        // Browsers can disable storage; do not discard the in-memory identity.
      }
    }
    return key
  }
  return Object.assign(keyFor, {
    settle(operation: 'space' | 'quiz', semanticRequest: string) {
      const semantic = `${operation}:${semanticRequest}`
      memory.delete(semantic)
      const fingerprint = fingerprints.get(semantic)
      fingerprints.delete(semantic)
      if (!fingerprint) return
      try {
        const storageKey = storageName(operation)
        const candidate: unknown = JSON.parse(sessionStorage.getItem(storageKey) || '{}')
        if (candidate && typeof candidate === 'object' && !Array.isArray(candidate)) {
          const remaining = Object.fromEntries(
            Object.entries(candidate).filter(([hash]) => hash !== fingerprint),
          )
          if (Object.keys(remaining).length)
            sessionStorage.setItem(storageKey, JSON.stringify(remaining))
          else sessionStorage.removeItem(storageKey)
        }
      } catch {
        // Confirmation still clears the in-memory retry identity.
      }
    },
  })
}
