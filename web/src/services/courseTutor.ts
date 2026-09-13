import { request } from './http'
import { trackContentSubmission } from './experienceEvents'
import type {
  CourseEvidenceView,
  CourseSelfCheckCreate,
  CourseSelfCheckView,
  CourseTutorCreate,
  CourseTutorTurnView,
} from '../types/course'

const segment = encodeURIComponent
const base = (courseId: string, lessonId: string) =>
  `/courses/${segment(courseId)}/lessons/${segment(lessonId)}`

const trackTutorSubmission = async (send: () => Promise<CourseTutorTurnView>) => {
  const result = await trackContentSubmission(async () => {
    const turn = await send()
    return { task_id: turn.task.task_id, turn }
  })
  return result.turn
}

export const askTutor = (
  courseId: string,
  lessonId: string,
  body: CourseTutorCreate,
  key: string,
  signal?: AbortSignal,
) =>
  trackTutorSubmission(() => request<CourseTutorTurnView>(`${base(courseId, lessonId)}/tutor-turns`, {
    method: 'POST',
    data: body,
    idempotencyKey: key,
    signal,
  }))

export const listTutorTurns = (
  courseId: string,
  lessonId: string,
  version: number,
  signal?: AbortSignal,
) =>
  request<CourseTutorTurnView[]>(
    `${base(courseId, lessonId)}/tutor-turns?content_version=${version}`,
    { signal },
  )

export const retryTutorTurn = (
  courseId: string,
  lessonId: string,
  turnId: string,
  key: string,
  signal?: AbortSignal,
) =>
  trackTutorSubmission(() => request<CourseTutorTurnView>(`${base(courseId, lessonId)}/tutor-turns/${segment(turnId)}/retry`, {
    method: 'POST',
    idempotencyKey: key,
    signal,
  }))

export const readTutorEvidence = (
  courseId: string,
  lessonId: string,
  turnId: string,
  sourceRef: string,
  signal?: AbortSignal,
) =>
  request<CourseEvidenceView>(
    `${base(courseId, lessonId)}/tutor-turns/${segment(turnId)}/evidence/${segment(sourceRef)}`,
    { signal },
  )

export const saveCheckAttempt = (
  courseId: string,
  lessonId: string,
  body: CourseSelfCheckCreate,
  key: string,
  signal?: AbortSignal,
) =>
  request<CourseSelfCheckView>(`${base(courseId, lessonId)}/self-check-attempts`, {
    method: 'POST',
    data: body,
    idempotencyKey: key,
    signal,
  })

export const listCheckAttempts = (
  courseId: string,
  lessonId: string,
  version: number,
  signal?: AbortSignal,
) =>
  request<CourseSelfCheckView[]>(
    `${base(courseId, lessonId)}/self-check-attempts?content_version=${version}`,
    { signal },
  )

export const courseTutorKeys = {
  turns: (identity: string | number, courseId: string, lessonId: string, version: number) =>
    [identity, 'courses', 'tutor', courseId, lessonId, version] as const,
  checks: (identity: string | number, courseId: string, lessonId: string, version: number) =>
    [identity, 'courses', 'self-checks', courseId, lessonId, version] as const,
  evidence: (
    identity: string | number,
    courseId: string,
    lessonId: string,
    turnId: string,
    sourceRef: string,
  ) => [identity, 'courses', 'tutor-evidence', courseId, lessonId, turnId, sourceRef] as const,
}
