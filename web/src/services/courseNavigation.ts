export function coursePath(courseId: string, lessonId?: string | null) {
  const path = `/study/courses/${encodeURIComponent(courseId)}`
  return lessonId ? `${path}?lesson=${encodeURIComponent(lessonId)}` : path
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
