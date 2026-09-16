import { Link } from 'react-router-dom'
import type { CourseLessonSummary, CourseView } from '../../types/course'

// A course keeps the same binding when its title, progress or shelf position changes.
function bindingFor(courseId: string) {
  let hash = 0
  for (const character of courseId) hash = (Math.imul(hash, 31) + character.charCodeAt(0)) | 0
  return (hash >>> 0) % 3
}

export function courseReadingProgress(lessons: CourseLessonSummary[] = []) {
  const available = lessons.filter(
    (lesson) => lesson.availability !== 'material_gap' && lesson.status !== 'source_revoked',
  )
  return { read: available.filter((lesson) => !!lesson.read_at).length, total: available.length }
}

export function CourseReadingProgress({
  lessons,
  label = '课程阅读进度',
}: {
  lessons?: CourseLessonSummary[]
  label?: string
}) {
  const { read, total } = courseReadingProgress(lessons)
  if (!total) return null
  return (
    <div className="course-reading-progress">
      <div className="course-reading-progress-label">
        <span>
          已读 {read} / {total} 节
        </span>
        <span>{Math.round((read / total) * 100)}%</span>
      </div>
      <progress aria-label={label} value={read} max={total} />
    </div>
  )
}

export function CourseCover({
  course,
  to,
  compact = false,
}: {
  course: Pick<CourseView, 'course_id' | 'title' | 'source_policy' | 'source_status' | 'status'>
  to?: string
  compact?: boolean
}) {
  const revoked = course.source_status === 'revoked' || course.status === 'source_revoked'
  const className = `course-cover course-cover-binding-${bindingFor(course.course_id)}${compact ? ' course-cover-compact' : ''}${revoked ? ' is-revoked' : ''}`
  const content = (
    <>
      <span className="course-cover-binding" aria-hidden="true" />
      <span className="course-cover-type">
        {revoked ? '资料已失效' : course.source_policy === 'topic' ? '主题课程' : '资料课程'}
      </span>
      <h3 className="course-cover-title">{revoked ? '资料已失效的课程' : course.title}</h3>
      <span className="course-cover-rule" aria-hidden="true" />
    </>
  )
  if (compact)
    return (
      <div className={className} aria-hidden="true">
        <span className="course-cover-binding" />
        <span className="course-cover-rule" />
      </div>
    )
  return to ? (
    <Link className={className} to={to}>
      {content}
    </Link>
  ) : (
    <div className={className}>{content}</div>
  )
}
