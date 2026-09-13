import { request } from './http'
import type { ApiSchemas } from '../types/api'

export type CourseRevisionView = ApiSchemas['CourseRevisionView']

const segment = encodeURIComponent

/** 影响预览不调用模型；一次最多三节课。 */
export function createRevisionPreview(
  courseId: string,
  body: ApiSchemas['CourseRevisionPreview'],
  key: string,
  signal?: AbortSignal,
) {
  return request<CourseRevisionView>(`/courses/${segment(courseId)}/revision-previews`, {
    method: 'POST', data: body, idempotencyKey: key, signal,
  })
}

export function startRevisionJobs(
  courseId: string,
  body: ApiSchemas['CourseRevisionGenerate'],
  key: string,
  signal?: AbortSignal,
) {
  return request<CourseRevisionView>(`/courses/${segment(courseId)}/revision-jobs`, {
    method: 'POST', data: body, idempotencyKey: key, signal,
  })
}

export function getRevision(courseId: string, revisionId: string, signal?: AbortSignal) {
  return request<CourseRevisionView>(
    `/courses/${segment(courseId)}/revisions/${segment(revisionId)}`, { signal })
}

export function applyRevision(
  courseId: string,
  revisionId: string,
  body: ApiSchemas['CourseRevisionApply'],
  key: string,
  signal?: AbortSignal,
) {
  return request<CourseRevisionView>(
    `/courses/${segment(courseId)}/revisions/${segment(revisionId)}/apply`,
    { method: 'POST', data: body, idempotencyKey: key, signal },
  )
}

export function lessonVersions(courseId: string, lessonId: string, signal?: AbortSignal) {
  return request<Array<{ content_version: number; archived_at: string; read_at: string | null }>>(
    `/courses/${segment(courseId)}/lessons/${segment(lessonId)}/versions`, { signal })
}

export function lessonVersion(
  courseId: string, lessonId: string, contentVersion: number, signal?: AbortSignal,
) {
  return request<{ lesson_id: string; content_version: number; content: { payload?: { blocks?: Array<{ type: string; text: string }> } }; read_only: boolean }>(
    `/courses/${segment(courseId)}/lessons/${segment(lessonId)}/versions/${contentVersion}`,
    { signal },
  )
}
