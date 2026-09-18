import { useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { useIdentityKey } from '../../app/AuthProvider'
import { courseKeys, coursesApi, courseSourceRevoked } from '../../services/courses'
import { ApiError } from '../../services/http'
import type { CourseLessonView } from '../../types/course'
import { isUnconfirmedCourseOperation } from './courseActionState'
import type { useCourseOperation } from './useCourseOperation'

type ReadIntent = { expected_revision: number; read: boolean; practice: boolean }
type ReadRecovery = { checked: boolean; revision: number; conflict: boolean }

/** Retry an absolute intent. Re-reading never toggles or silently overwrites a newer revision. */
export function useLessonReadIntent(
  lesson: CourseLessonView,
  operation: ReturnType<typeof useCourseOperation>,
  onPractice: () => void,
) {
  const identity = useIdentityKey()
  const client = useQueryClient()
  const intentRef = useRef<ReadIntent | null>(null)
  const practiceRef = useRef(onPractice)
  practiceRef.current = onPractice
  const [recovery, setRecovery] = useState<ReadRecovery | null>(null)

  function assertCurrent(current: CourseLessonView) {
    if (current.course_id !== lesson.course_id || current.lesson_id !== lesson.lesson_id)
      throw new ApiError('课时不属于当前课程。', 404, 'course_lesson_not_found')
    if (current.content_version !== lesson.content_version)
      throw new ApiError('课文版本已更新，请核对后继续。', 409, 'content_version_conflict')
    return current
  }
  function remember(current: CourseLessonView) {
    client.setQueryData(courseKeys.lesson(identity, lesson.course_id, lesson.lesson_id), current)
    intentRef.current = null
    setRecovery(null)
    for (const queryKey of [
      courseKeys.course(identity, lesson.course_id), courseKeys.progress(identity, lesson.course_id),
      courseKeys.lists(identity), courseKeys.reviews(identity, lesson.course_id), courseKeys.todayAll(identity),
    ]) void client.invalidateQueries({ queryKey })
  }
  function unresolved(current: CourseLessonView, intent: ReadIntent, checked: boolean) {
    const conflict = current.revision !== intent.expected_revision
    setRecovery({ checked: checked || conflict, revision: current.revision, conflict })
    return conflict
      ? new ApiError('内容已更新，请核对后重试。', 409, 'revision_conflict')
      : new ApiError('尚未核对到这次已读操作。', 0, 'OPERATION_UNCONFIRMED')
  }
  async function finish(result: Promise<CourseLessonView | undefined>, intent: ReadIntent) {
    const saved = await result
    if (saved && intent.practice) practiceRef.current()
    return saved
  }
  function submit(intent: ReadIntent) {
    return finish(operation.run('read', async (signal) => {
      try {
        const saved = assertCurrent(await coursesApi.markRead(lesson.course_id, lesson.lesson_id,
          intent.expected_revision, intent.read, signal))
        if (Boolean(saved.read_at) !== intent.read) throw new ApiError('已读结果尚未确认。', 0, 'INVALID_RESPONSE')
        return saved
      } catch (cause) {
        if (signal.aborted) throw cause
        if (!isUnconfirmedCourseOperation(cause) && !(cause instanceof ApiError && cause.status === 409)) {
          intentRef.current = null
          setRecovery(null)
          throw cause
        }
        setRecovery({ checked: false, revision: intent.expected_revision, conflict: false })
        let current: CourseLessonView
        try {
          current = assertCurrent(await coursesApi.lesson(lesson.course_id, lesson.lesson_id, signal))
        } catch (readError) {
          if (courseSourceRevoked(readError) || (readError instanceof ApiError && [401, 404, 409].includes(readError.status)))
            throw readError
          throw cause
        }
        if (Boolean(current.read_at) === intent.read) return current
        throw unresolved(current, intent, false)
      }
    }, remember), intent)
  }
  function mark(read: boolean, practice = false) {
    if (operation.pending !== null || intentRef.current) return Promise.resolve(undefined)
    const intent = { expected_revision: lesson.revision, read, practice }
    intentRef.current = intent
    return submit(intent)
  }
  function recover() {
    const intent = intentRef.current
    if (!intent || operation.pending !== null) return Promise.resolve(undefined)
    return finish(operation.run('read', async (signal) => {
      const current = assertCurrent(await coursesApi.lesson(lesson.course_id, lesson.lesson_id, signal))
      if (Boolean(current.read_at) === intent.read) return current
      throw unresolved(current, intent, true)
    }, remember), intent)
  }
  function retry() {
    const previous = intentRef.current
    if (!previous || !recovery?.checked || operation.pending !== null) return Promise.resolve(undefined)
    // The user has seen the refreshed state and explicitly chose to retry this same read value.
    const intent = { ...previous, expected_revision: recovery.revision }
    intentRef.current = intent
    return submit(intent)
  }
  return { mark, recover, retry, recovery }
}
