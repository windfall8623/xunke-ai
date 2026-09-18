import { request } from './http'
import type { ApiSchemas } from '../types/api'

export type LearningPreferencesView = ApiSchemas['LearningPreferencesView']
export type LearningPreferencesUpdate = ApiSchemas['LearningPreferencesUpdate']
export type CourseReviewUpdate = ApiSchemas['CourseReviewUpdate']
export type CourseReviewAdjustAction = CourseReviewUpdate['action']

export const difficultyLabels: Record<LearningPreferencesView['difficulty'], string> = {
  easy: '先补基础',
  medium: '正常推进',
  hard: '增加挑战',
  mixed: '混合安排',
}

export function getPreferences(signal?: AbortSignal) {
  return request<LearningPreferencesView>('/study/preferences', { signal })
}

export function updatePreferences(body: LearningPreferencesUpdate, signal?: AbortSignal) {
  return request<LearningPreferencesView>('/study/preferences', {
    method: 'PATCH',
    data: body,
    signal,
  })
}

/** 暂停只隐藏建议，不产生完成记录；reschedule 需要显式未来时间。 */
export function adjustCourseReview(
  courseId: string,
  reviewId: string,
  body: CourseReviewUpdate,
  key: string,
  signal?: AbortSignal,
) {
  return request<ApiSchemas['CourseReviewView']>(
    `/courses/${encodeURIComponent(courseId)}/reviews/${encodeURIComponent(reviewId)}`,
    { method: 'PATCH', data: body, idempotencyKey: key, signal },
  )
}
