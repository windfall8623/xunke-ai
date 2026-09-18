import { ApiError, request } from './http'
import { providerErrorMessage } from './providerErrors'
import { trackContentSubmission } from './experienceEvents'
import type {
  CourseApplicationAnswer,
  CourseApplicationAttemptView,
  CourseAssessmentComplete,
  CourseAssessmentCreate,
  CourseAssessmentView,
  CourseCapabilities,
  CourseCreate,
  CourseEvidenceView,
  CourseLessonView,
  CourseList,
  CourseOutcomeSummary,
  CourseOutlineUpdate,
  CourseProgressView,
  CourseQuizCreate,
  CourseQuizLinkView,
  CourseReviewStart,
  CourseReviewView,
  CourseTodayView,
  CourseTaskView,
  CourseView,
} from '../types/course'

/** 契约上限：`CourseApplicationAnswer.answer` 为 1–4000 字符。 */
export const COURSE_APPLICATION_ANSWER_MAX = 4000

const segment = encodeURIComponent
const courseBase = (id: string) => `/courses/${segment(id)}`
const lessonBase = (id: string, lessonId: string) =>
  `${courseBase(id)}/lessons/${segment(lessonId)}`
const assessmentBase = (id: string, assessmentId: string) =>
  `${courseBase(id)}/assessments/${segment(assessmentId)}`

export const coursesApi = {
  capabilities: (signal?: AbortSignal) =>
    request<CourseCapabilities>('/courses/capabilities', { signal }),
  list: (page = 1, pageSize = 6, signal?: AbortSignal) =>
    request<CourseList>(`/courses?page=${page}&page_size=${pageSize}`, { signal }),
  create: (data: CourseCreate, key: string, signal?: AbortSignal) =>
    request<CourseTaskView>('/courses', { method: 'POST', data, idempotencyKey: key, signal }),
  course: (id: string, signal?: AbortSignal) => request<CourseView>(courseBase(id), { signal }),
  updateOutline: (id: string, data: CourseOutlineUpdate, signal?: AbortSignal) =>
    request<CourseView>(`${courseBase(id)}/outline`, { method: 'PATCH', data, signal }),
  retryOutline: (id: string, key: string, signal?: AbortSignal) =>
    request<CourseTaskView>(`${courseBase(id)}/outline-jobs`, {
      method: 'POST',
      idempotencyKey: key,
      signal,
    }),
  generateLesson: (
    id: string,
    lessonId: string,
    revision: number,
    key: string,
    signal?: AbortSignal,
    requestQualityReview = false,
  ) =>
    trackContentSubmission(() => request<CourseTaskView>(`${lessonBase(id, lessonId)}/generation-jobs`, {
      method: 'POST',
      // 课时沿用课程已冻结的教学方式；fast 下只能显式请求本课核对。
      data: { expected_course_revision: revision, request_quality_review: requestQualityReview },
      idempotencyKey: key,
      signal,
    })),
  lesson: (id: string, lessonId: string, signal?: AbortSignal) =>
    request<CourseLessonView>(lessonBase(id, lessonId), { signal }),
  markRead: (id: string, lessonId: string, revision: number, read: boolean, signal?: AbortSignal) =>
    request<CourseLessonView>(`${lessonBase(id, lessonId)}/progress`, {
      method: 'PATCH',
      data: { expected_revision: revision, read },
      signal,
    }),
  createQuiz: (
    id: string,
    lessonId: string,
    data: CourseQuizCreate,
    key: string,
    signal?: AbortSignal,
  ) =>
    request<CourseQuizLinkView>(`${lessonBase(id, lessonId)}/quiz-jobs`, {
      method: 'POST',
      data,
      idempotencyKey: key,
      signal,
    }),
  progress: (id: string, signal?: AbortSignal) =>
    request<CourseProgressView>(`${courseBase(id)}/progress`, { signal }),
  reviews: (id: string, signal?: AbortSignal) =>
    request<CourseReviewView[]>(`${courseBase(id)}/reviews`, { signal }),
  startReview: (
    id: string,
    lessonId: string,
    data: CourseReviewStart,
    key: string,
    signal?: AbortSignal,
  ) =>
    request<CourseQuizLinkView>(`${lessonBase(id, lessonId)}/review-jobs`, {
      method: 'POST',
      data,
      idempotencyKey: key,
      signal,
    }),
  today: (timezone = 'Asia/Shanghai', minutesBudget = 20, signal?: AbortSignal) =>
    request<CourseTodayView>(
      `/courses/today?timezone=${segment(timezone)}&minutes_budget=${minutesBudget}`,
      { signal },
    ),
  task: (taskId: string, signal?: AbortSignal) =>
    request<CourseTaskView>(`/courses/tasks/${segment(taskId)}`, { signal }),
  cancelTask: (taskId: string, signal?: AbortSignal) =>
    request<CourseTaskView>(`/courses/tasks/${segment(taskId)}/cancel`, { method: 'POST', signal }),
  evidence: (id: string, sourceRef: string, lessonId?: string, signal?: AbortSignal) =>
    request<CourseEvidenceView>(
      `${lessonId ? lessonBase(id, lessonId) : courseBase(id)}/evidence/${segment(sourceRef)}`,
      { signal },
    ),
  // A07：只读目标结果投影；GET 不创建题目、不结算、不追加学习行为。
  outcomes: (id: string, signal?: AbortSignal) =>
    request<CourseOutcomeSummary>(`${courseBase(id)}/outcomes`, { signal }),
  assessments: (id: string, signal?: AbortSignal) =>
    request<CourseAssessmentView[]>(`${courseBase(id)}/assessments`, { signal }),
  assessment: (id: string, assessmentId: string, signal?: AbortSignal) =>
    request<CourseAssessmentView>(assessmentBase(id, assessmentId), { signal }),
  createAssessment: (id: string, data: CourseAssessmentCreate, key: string, signal?: AbortSignal) =>
    request<CourseAssessmentView>(`${courseBase(id)}/assessment-jobs`, {
      method: 'POST',
      data,
      idempotencyKey: key,
      signal,
    }),
  completeAssessment: (
    id: string,
    assessmentId: string,
    data: CourseAssessmentComplete,
    key: string,
    signal?: AbortSignal,
  ) =>
    request<CourseAssessmentView>(`${assessmentBase(id, assessmentId)}/complete`, {
      method: 'POST',
      data,
      idempotencyKey: key,
      signal,
    }),
  // A08：按需生成 1–2 个文本应用任务，保存回答后再排队反馈。
  createApplications: (id: string, assessmentId: string, key: string, signal?: AbortSignal) =>
    request<CourseAssessmentView>(`${assessmentBase(id, assessmentId)}/application-jobs`, {
      method: 'POST',
      idempotencyKey: key,
      signal,
    }),
  submitApplicationAnswer: (
    id: string,
    assessmentId: string,
    applicationTaskId: string,
    data: CourseApplicationAnswer,
    key: string,
    signal?: AbortSignal,
  ) =>
    request<CourseApplicationAttemptView>(
      `${assessmentBase(id, assessmentId)}/applications/${segment(applicationTaskId)}/attempts`,
      { method: 'POST', data, idempotencyKey: key, signal },
    ),
  applicationAttempt: (
    id: string,
    assessmentId: string,
    attemptId: string,
    signal?: AbortSignal,
  ) =>
    request<CourseApplicationAttemptView>(
      `${assessmentBase(id, assessmentId)}/attempts/${segment(attemptId)}`,
      { signal },
    ),
  retryApplicationFeedback: (
    id: string,
    assessmentId: string,
    attemptId: string,
    key: string,
    signal?: AbortSignal,
  ) =>
    request<CourseApplicationAttemptView>(
      `${assessmentBase(id, assessmentId)}/attempts/${segment(attemptId)}/feedback-jobs`,
      { method: 'POST', idempotencyKey: key, signal },
    ),
}

export const courseKeys = {
  all: (identity: string | number) => [identity, 'courses'] as const,
  capabilities: (identity: string | number) => [identity, 'courses', 'capabilities'] as const,
  lists: (identity: string | number) => [identity, 'courses', 'list'] as const,
  list: (identity: string | number, page = 1, pageSize = 6) =>
    [identity, 'courses', 'list', page, pageSize] as const,
  course: (identity: string | number, id: string) => [identity, 'courses', 'course', id] as const,
  lesson: (identity: string | number, id: string, lessonId: string) =>
    [identity, 'courses', 'lesson', id, lessonId] as const,
  progress: (identity: string | number, id: string) =>
    [identity, 'courses', 'progress', id] as const,
  reviews: (identity: string | number, id: string) => [identity, 'courses', 'reviews', id] as const,
  todayAll: (identity: string | number) => [identity, 'courses', 'today'] as const,
  today: (identity: string | number, timezone: string, minutes: number, date: string) =>
    [identity, 'courses', 'today', timezone, minutes, date] as const,
  task: (identity: string | number, id: string, taskId: string, lessonId?: string | null) =>
    [identity, 'courses', 'task', id, lessonId || null, taskId] as const,
  evidence: (identity: string | number, id: string, sourceRef: string, lessonId?: string) =>
    [identity, 'courses', 'evidence', id, lessonId || null, sourceRef] as const,
  outcomes: (identity: string | number, id: string) =>
    [identity, 'courses', 'outcomes', id] as const,
  assessments: (identity: string | number, id: string) =>
    [identity, 'courses', 'assessments', id] as const,
  assessment: (identity: string | number, id: string, assessmentId: string) =>
    [identity, 'courses', 'assessment', id, assessmentId] as const,
  applicationAttempt: (
    identity: string | number,
    id: string,
    assessmentId: string,
    attemptId: string,
  ) => [identity, 'courses', 'application-attempt', id, assessmentId, attemptId] as const,
}

export const courseTaskPending = (task?: { status: string } | null) =>
  !!task && ['pending', 'running'].includes(task.status)

export const courseSourceRevoked = (error: unknown) =>
  error instanceof ApiError &&
  ([403, 410].includes(error.status) || String(error.code).toLowerCase() === 'source_revoked')

export const courseAccessDenied = (error: unknown) => courseSourceRevoked(error) ||
  (error instanceof ApiError && [401, 404].includes(error.status))

const courseErrors: Record<string, string> = {
  teaching_agents_unavailable: '标准教学暂不可用，请核对教学方式后再次提交。',
  source_not_ready: '资料还未处理完成，请等待就绪后重新选择。',
  source_revoked: '课程资料已不可用，相关内容已隐藏。请重新选择资料创建课程。',
  source_unavailable: '所选资料不可用，请检查资料状态并重新选择。',
  course_scope_too_large: '所选资料范围过大，请缩小到相关章节后创建课程。',
  generation_validation_failed: '本次生成未通过内容检查，可以重新生成。',
  insufficient_evidence: '当前资料不足以支持这节课，请补充资料后创建新课程。',
  material_gap: '当前资料未覆盖这节课，请补充资料后创建新课程。',
  revision_conflict: '内容版本已更新，请刷新并核对后重试。',
  idempotency_conflict: '该请求与此前的提交不一致，请核对当前内容后重试。',
  budget_exceeded: '已达到本次或当日调用预算，请稍后重试。',
  provider_not_configured: '模型服务尚未配置，请联系管理员配置后重试。',
  course_not_ready: '请等待课程纲要生成完成后再开始学习。',
  no_wrong_questions: '这次练习没有可补练的错题，可以继续下一课。',
  quiz_incomplete: '请先完成并确认原练习，再针对错题补练。',
  course_review_not_due: '这节课还未到建议复习时间；如需现在开始，请点击“提前复习”。',
  course_review_conflict: '复习安排已更新，请核对最新状态后重试。',
  content_version_conflict: '课文版本已更新，请刷新这一课后继续。',
  course_tutor_busy: '本课已有助教回答正在准备，请等待完成或取消后再提问。',
  course_quality_unavailable: '本次教学核对未完成，已保留原有内容。可稍后重新生成。',
  course_assessment_no_taught_goals: '请先学完至少一个目标对应的课时，再开始结业检查；资料缺口的目标仍保持待验证。',
  course_assessment_completed: '本次检查已封存。需要继续检验时，请创建下一组检查。',
  course_assessment_incomplete: '请先完成并确认本组客观题的结算，再封存本次检查。',
  course_assessment_invalid: '本次结业题的目标对应关系未通过核对，请重新开始一组检查。',
  course_assessment_evidence_changed: '检查题目或结算证据已变化，请刷新后核对最新结果。',
  course_criterion_invalid: '所选目标不属于当前课程版本，请刷新后重新选择。',
  course_application_no_taught_goals: '当前还没有已教且可用于应用练习的目标。',
  course_application_question_changed: '应用任务内容已更新，请刷新后查看最新题目。',
  course_application_task_replaced: '应用任务已更新，请刷新后继续。',
  content_filtered: '这次回答未通过内容检查，请调整后重新提交。',
}

export function courseLocalDate(now: Date, timezone: string) {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: timezone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(now)
  const part = (name: string) => parts.find((item) => item.type === name)?.value || ''
  return `${part('year')}-${part('month')}-${part('day')}`
}

export function courseReviewTime(review: Pick<CourseReviewView, 'due_at' | 'timezone'>) {
  const date = new Date(review.due_at)
  if (Number.isNaN(date.getTime())) return '时间待更新'
  try {
    return new Intl.DateTimeFormat('zh-CN', {
      timeZone: review.timezone,
      dateStyle: 'medium',
      timeStyle: 'short',
    }).format(date)
  } catch {
    return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(
      date,
    )
  }
}

export function courseTaskErrorMessage(
  task?: { error_code?: string | null; error_message?: string | null } | null,
) {
  const code = task?.error_code || ''
  return (
    providerErrorMessage(code.toUpperCase()) ||
    courseErrors[code.toLowerCase()] ||
    task?.error_message ||
    '本次生成未完成，可以重新生成。'
  )
}

export function courseErrorMessage(error: unknown) {
  if (error instanceof ApiError) {
    if (courseSourceRevoked(error)) return courseErrors.source_revoked
    if (error.status === 404) return '课程或课时不存在，或当前账号无权访问。'
    if (error.status === 401) return '登录已失效，请重新登录。'
    if (error.status === 409)
      return (
        courseErrors[String(error.code).toLowerCase()] ||
        error.message ||
        courseErrors.revision_conflict
      )
    const providerMessage = providerErrorMessage(String(error.code).toUpperCase())
    if (providerMessage) return providerMessage
    if (error.status === 0 || error.status >= 500 || error.code === 'INVALID_RESPONSE')
      return '提交或读取结果尚未确认，请检查网络后重试；重复提交会沿用原请求。'
    return courseErrors[String(error.code).toLowerCase()] || error.message
  }
  return error instanceof Error ? error.message : String(error || '操作未完成，请重试。')
}

/** Store only request fingerprints and keys; the auth provider clears these on account changes. */
export function createCourseSubmissionKeys(identity: string | number, entry: string) {
  const memory = new Map<string, string>()
  const fingerprints = new Map<string, string>()
  const storageName = `qa-submission:${identity}:course:${entry}`
  const read = (): Record<string, string> => {
    const candidate: unknown = JSON.parse(sessionStorage.getItem(storageName) || '{}')
    if (!candidate || typeof candidate !== 'object' || Array.isArray(candidate)) return {}
    return Object.fromEntries(
      Object.entries(candidate).filter(
        ([hash, key]) =>
          /^[a-f0-9]{64}$/.test(hash) &&
          typeof key === 'string' &&
          /^[a-zA-Z0-9-]{1,128}$/.test(key),
      ),
    )
  }
  const keyFor = async (operation: string, semanticRequest: string) => {
    const semantic = `${operation}:${semanticRequest}`
    const remembered = memory.get(semantic)
    if (remembered) return remembered
    let fingerprint: string | undefined
    let persisted: Record<string, string> = {}
    try {
      const bytes = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(semantic))
      fingerprint = Array.from(new Uint8Array(bytes), (byte) =>
        byte.toString(16).padStart(2, '0'),
      ).join('')
      fingerprints.set(semantic, fingerprint)
      persisted = read()
    } catch {
      // Keep retries stable in memory when the browser blocks storage or Web Crypto.
    }
    const key = (fingerprint && persisted[fingerprint]) || crypto.randomUUID()
    memory.set(semantic, key)
    if (fingerprint) {
      try {
        sessionStorage.setItem(storageName, JSON.stringify({ ...persisted, [fingerprint]: key }))
      } catch {
        /* Optional storage. */
      }
    }
    return key
  }
  return Object.assign(keyFor, {
    settle(operation: string, semanticRequest: string) {
      const semantic = `${operation}:${semanticRequest}`
      memory.delete(semantic)
      const fingerprint = fingerprints.get(semantic)
      fingerprints.delete(semantic)
      if (!fingerprint) return
      try {
        const remaining = read()
        delete remaining[fingerprint]
        if (Object.keys(remaining).length)
          sessionStorage.setItem(storageName, JSON.stringify(remaining))
        else sessionStorage.removeItem(storageName)
      } catch {
        /* The confirmed in-memory request is already cleared. */
      }
    },
  })
}
