import type { Quiz } from '../../types/api'
import type { CourseLessonView, CourseNextAction, CourseQuizLinkView, CourseSelfCheckView } from '../../types/course'

export type LessonPracticeState = 'none' | 'preparing' | 'answering' | 'settled' | 'unconfirmed' | 'unavailable'
export type LessonPracticeResult = { answered: number; correct: number; total: number }
export type LessonStudyFacts = {
  readAt: string | null
  selfCheckState: 'loading' | 'confirmed' | 'unconfirmed' | 'unavailable'
  savedCheckCount: number | null
  checkCount: number
  practice: LessonPracticeResult | null
  practiceState: LessonPracticeState
  recap: string[]
}

export function currentInitialLessonQuiz(lesson: CourseLessonView) {
  return (lesson.quiz_links || []).filter((link) => link.lesson_id === lesson.lesson_id &&
    link.content_version === lesson.content_version && link.kind === 'initial' &&
    !['failed', 'cancelled'].includes(link.task.status))
    .sort((a, b) => a.created_at.localeCompare(b.created_at) || a.link_id.localeCompare(b.link_id)).at(-1)
}

export function matchesLessonQuiz(quiz: Quiz, lesson: CourseLessonView, link: CourseQuizLinkView) {
  const context = quiz.course_context
  return quiz.quiz_id === (link.task.quiz_id || link.task.result?.quiz_id) &&
    context?.course_id === lesson.course_id && context.lesson_id === lesson.lesson_id &&
    context.link_id === link.link_id && context.content_version === lesson.content_version &&
    context.kind === link.kind
}

export function lessonStudyFacts(
  lesson: CourseLessonView,
  attempts: CourseSelfCheckView[],
  selfCheckState: LessonStudyFacts['selfCheckState'],
  practiceState: LessonPracticeState,
  practice: LessonPracticeResult | null,
): LessonStudyFacts {
  const validRefs = new Set((lesson.checks || []).map((check) => check.check_ref))
  return {
    readAt: lesson.read_at || null,
    selfCheckState,
    savedCheckCount: selfCheckState === 'confirmed' ? new Set(attempts.filter((attempt) =>
      attempt.course_id === lesson.course_id && attempt.lesson_id === lesson.lesson_id &&
      attempt.content_version === lesson.content_version && validRefs.has(attempt.check_ref))
      .map((attempt) => attempt.check_ref)).size : null,
    checkCount: validRefs.size,
    practice: practiceState === 'settled' ? practice : null,
    practiceState,
    recap: (lesson.blocks || []).filter((block) => block.type === 'recap').map((block) => block.text),
  }
}

export const lessonNextActionLabels: Record<CourseNextAction['type'], string> = {
  continue_quiz: '继续这次练习', review_lesson: '回看并补练', learn_lesson: '继续下一课',
  practice_lesson: '做本课三题', view_summary: '查看课程学习记录',
}
