import type { CourseReturnContext, CourseTodayItem } from '../types/course'

export function coursePath(courseId: string, lessonId?: string | null) {
  const path = `/study/courses/${encodeURIComponent(courseId)}`
  return lessonId ? `${path}?lesson=${encodeURIComponent(lessonId)}` : path
}

/** A server association wins even when a URL carries a different legacy hint. */
export function courseReturnPath(context?: CourseReturnContext | null, legacy?: string | null) {
  return context ? coursePath(context.course_id, context.lesson_id) : safeCourseReturn(legacy)
}

/** The fixed summary anchor is appended after validating the destination, never accepted from a URL hint. */
export function courseSummaryReturnPath(context?: CourseReturnContext | null, legacy?: string | null) {
  const path = courseReturnPath(context, legacy)
  return path ? `${path}#lesson-summary` : null
}

export function scrollCourseSection(id: string, block: ScrollLogicalPosition = 'start', focus = false) {
  const element = document.getElementById(id)
  if (!element) return
  const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  element.scrollIntoView?.({ behavior: reduceMotion ? 'auto' : 'smooth', block })
  if (focus) element.focus({ preventScroll: true })
}

export function courseTodayPath(item: CourseTodayItem) {
  const back = item.course_id ? coursePath(item.course_id, item.lesson_id) : null
  if (item.kind === 'continue_quiz') {
    if (item.quiz_id) return withCourseReturn(`/quizzes/${encodeURIComponent(item.quiz_id)}`, back)
    if (item.task_id) return withCourseReturn(`/tasks/${encodeURIComponent(item.task_id)}`, back)
  }
  if (item.kind === 'study_review' && item.space_id && item.review_task_id)
    return `/study/reviews?space_id=${encodeURIComponent(item.space_id)}&review_task_id=${encodeURIComponent(item.review_task_id)}#review-${encodeURIComponent(item.review_task_id)}`
  if (!back) return null
  if (item.kind === 'course_review') return `${back}#course-review`
  if (item.kind === 'practice_lesson' || item.kind === 'review_lesson')
    return `${back}#course-practice`
  return back
}

/** Navigation hints never authorize a course; each destination re-reads its owner-scoped API. */
export function safeCourseReturn(value: string | null | undefined) {
  return value && /^\/study\/courses\/[A-Za-z0-9_-]+(?:\?lesson=[A-Za-z0-9_-]+)?$/.test(value)
    ? value
    : null
}

export function safeStudyReturn(value: string | null | undefined) {
  return (
    safeCourseReturn(value) ||
    (value && /^\/(?:qa|study)(?:\/[A-Za-z0-9_-]+)*$/.test(value) ? value : null)
  )
}

export function withCourseReturn(path: string, returnTo?: string | null) {
  const safe = safeCourseReturn(returnTo)
  return safe
    ? `${path}${path.includes('?') ? '&' : '?'}returnTo=${encodeURIComponent(safe)}`
    : path
}
