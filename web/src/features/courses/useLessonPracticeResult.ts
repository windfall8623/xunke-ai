import { useQuery } from '@tanstack/react-query'
import { useEffect } from 'react'
import { useIdentityKey } from '../../app/AuthProvider'
import { api } from '../../services/api'
import { courseSourceRevoked, courseTaskPending } from '../../services/courses'
import { ApiError } from '../../services/http'
import type { CourseLessonView } from '../../types/course'
import { currentInitialLessonQuiz, matchesLessonQuiz, type LessonPracticeResult, type LessonPracticeState } from './lessonStudyFacts'

/** One current-version initial quiz; task completion only means the questions were generated. */
export function useLessonPracticeResult(lesson: CourseLessonView, onUnavailable: () => void) {
  const identity = useIdentityKey()
  const link = currentInitialLessonQuiz(lesson)
  const quizId = link?.task.quiz_id || link?.task.result?.quiz_id
  const query = useQuery({
    queryKey: [identity, 'quiz', quizId],
    queryFn: ({ signal }) => api.quiz(quizId!, signal),
    enabled: lesson.status === 'ready' && !!quizId && link?.task.status === 'completed',
    staleTime: 0, gcTime: 0, retry: false, refetchOnMount: 'always', refetchOnWindowFocus: 'always',
  })
  const inaccessible = courseSourceRevoked(query.error) ||
    (query.error instanceof ApiError && [401, 404].includes(query.error.status)) ||
    query.data?.source_status === 'source_revoked'
  useEffect(() => { if (inaccessible) onUnavailable() }, [inaccessible, onUnavailable])
  let state: LessonPracticeState = 'none'
  let result: LessonPracticeResult | null = null
  let message = '尚未开始本课首次练习。'
  if (inaccessible) {
    state = 'unavailable'
    message = '本课练习资料不可用，相关结果已隐藏。'
  } else if (link && courseTaskPending(link.task)) {
    state = 'preparing'
    message = '题目准备中，练习尚未完成。'
  } else if (link) {
    state = 'unconfirmed'
    message = query.error ? '结果暂未读回，请刷新本课结果。' : '正在读取本课练习记录…'
    if (!quizId) message = '题目已生成，练习关联尚未确认。'
    else if (query.data && !query.error && query.isFetchedAfterMount) {
      if (!matchesLessonQuiz(query.data, lesson, link)) message = '练习关联尚未确认，暂不计入本课结果。'
      else if (query.data.status === 'settled') {
        state = 'settled'
        result = { answered: query.data.answer_records.length,
          correct: query.data.answer_records.filter((answer) => answer.is_correct).length,
          total: query.data.questions.length }
        message = '本课首次练习已完成结算。'
      } else if (query.data.status === 'completed') message = '历史练习状态待确认，暂不计入已完成结果。'
      else {
        state = 'answering'
        message = '练习尚未完成，可以继续原来的作答。'
      }
    }
  }
  return { link, query, state, result, message }
}
