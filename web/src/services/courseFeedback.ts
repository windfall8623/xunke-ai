import { request } from './http'
import type { ApiSchemas } from '../types/api'

export type CourseFeedbackCreate = ApiSchemas['CourseFeedbackCreate']
export type CourseFeedbackView = ApiSchemas['CourseFeedbackView']
export type CourseFeedbackList = ApiSchemas['CourseFeedbackList']
export type CourseFeedbackUpdate = ApiSchemas['CourseFeedbackUpdate']
export type CourseCorrectionView = ApiSchemas['CourseCorrectionView']
export type CourseFeedbackTarget = CourseFeedbackCreate['target']

const segment = encodeURIComponent

/** 保存问题；同 key 重放返回原记录，异 body 409。 */
export const createCourseFeedback = (
  courseId: string,
  body: CourseFeedbackCreate,
  key: string,
  signal?: AbortSignal,
) =>
  request<CourseFeedbackView>(`/courses/${segment(courseId)}/feedback`, {
    method: 'POST',
    data: body,
    idempotencyKey: key,
    signal,
  })

export const listCourseFeedback = (
  courseId: string,
  query: { lesson_id?: string; check_attempt_id?: string; course_assessment_id?: string } = {},
  signal?: AbortSignal,
) => {
  const params = new URLSearchParams()
  if (query.lesson_id) params.set('lesson_id', query.lesson_id)
  if (query.check_attempt_id) params.set('check_attempt_id', query.check_attempt_id)
  if (query.course_assessment_id) params.set('course_assessment_id', query.course_assessment_id)
  const suffix = params.size ? `?${params.toString()}` : ''
  return request<CourseFeedbackList>(`/courses/${segment(courseId)}/feedback${suffix}`, { signal })
}

export const updateCourseFeedback = (
  courseId: string,
  feedbackId: string,
  body: CourseFeedbackUpdate,
  signal?: AbortSignal,
) =>
  request<CourseFeedbackView>(
    `/courses/${segment(courseId)}/feedback/${segment(feedbackId)}`,
    { method: 'PATCH', data: body, signal },
  )

/** 个人纠正：append-only；provisional，不修改旧记录。 */
export const createCourseCorrection = (
  courseId: string,
  feedbackId: string,
  body: ApiSchemas['CourseCorrectionCreate'],
  key: string,
  signal?: AbortSignal,
) =>
  request<CourseCorrectionView>(
    `/courses/${segment(courseId)}/feedback/${segment(feedbackId)}/corrections`,
    { method: 'POST', data: body, idempotencyKey: key, signal },
  )

export const confirmedCorrections = (view: CourseFeedbackView) =>
  (view.corrections ?? []).filter((item) => item.confirmation === 'confirmed')

export const latestCorrection = (view: CourseFeedbackView) =>
  view.corrections?.length ? view.corrections[view.corrections.length - 1] : null

/** 一个人工确认能改变什么：注释、替代判分、请求新检查或准备内容修订。 */
export const correctionEffectLabel = (view: CourseFeedbackView): string => {
  const confirmed = confirmedCorrections(view)
  if (!confirmed.length) return '尚无已确认纠正，只有你自己的说明。'
  if (view.target.kind === 'course_assessment') return '已确认复核替代了原判分。'
  if (view.target.kind === 'quiz') return '已确认题目有误，原成绩保留，稍后安排新的检查。'
  return '已确认内容需要修订，正文更新前会先给你预览。'
}
