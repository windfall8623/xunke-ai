import { act, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { renderApp } from '../test/renderApp'
import { apiFailure, json, session } from '../test/fixtures'
import { courseCheckFixture, courseFixture, courseLessonFixture, courseOutcomesFixture,
  courseProgressFixture, courseQuizFixture, courseQuizLinkFixture, courseTodayFixture } from '../test/courseFixtures'
import type { CourseLessonView } from '../types/course'
import type { Quiz } from '../types/api'

const lessonPath = '/api/v1/courses/course-1/lessons/lesson-1'
const quizPath = '/api/v1/user/quizzes/course-quiz-1'
function fixtureApi(path: string, lesson = courseLessonFixture) {
  if (path.endsWith('/auth/session')) return json(session)
  if (path.endsWith('/auth/capabilities')) return json({})
  if (path === '/api/v1/experience/events') return json(null)
  if (path === '/api/v1/courses/course-1') return json(courseFixture)
  if (path === lessonPath) return json(lesson)
  if (path.endsWith('/course-1/progress')) return json(courseProgressFixture)
  if (path.endsWith('/course-1/reviews') || path.includes('/tutor-turns')) return json([])
  // A07 结业面板挂到课程页后，outcome/assessment 读取失败会被视为课程不可访问。
  if (path.endsWith('/course-1/outcomes')) return json(courseOutcomesFixture)
  if (path.endsWith('/course-1/assessments')) return json([])
  if (path.includes('/self-check-attempts')) return json([courseCheckFixture])
  if (path.startsWith('/api/v1/courses/today')) return json(courseTodayFixture)
  if (path.startsWith('/api/v1/courses?')) return json({ items: [courseFixture,
    { ...courseFixture, course_id: 'course-2', title: '第二门课程' }], total: 2, page: 1, page_size: 6 })
  if (path.startsWith('/api/v1/study/spaces')) return json({ items: [], total: 0, page: 1, page_size: 6 })
  return apiFailure(404)
}
afterEach(() => vi.unstubAllGlobals())

describe('one lesson learning flow', () => {
  it('keeps the server today order and enters its first suggested lesson', async () => {
    renderApp('/study', (path) => fixtureApi(path))
    const today = await screen.findByRole('region', { name: '今日学习建议' })
    const action = await within(today).findByRole('link', { name: '继续阅读' })
    expect(action).toHaveClass('primary')
    expect(action).toHaveAttribute('href', '/study/courses/course-1?lesson=lesson-1')
    expect(within(today).getByRole('link', { name: '做本课三题' })).toHaveClass('secondary')
    expect(screen.getByRole('link', { name: '开始新课程' })).toHaveClass('secondary')
    await userEvent.click(action)
    expect(await screen.findByRole('heading', { name: courseLessonFixture.title })).toBeVisible()
    expect(await screen.findByRole('button', { name: '记录已读，进入本课练习' })).toBeVisible()
  })

  it('confirms an absolute read intent before reopening the existing quiz, then returns to its own summary', async () => {
    let lesson: CourseLessonView = { ...courseLessonFixture, quiz_links: [courseQuizLinkFixture] }
    let quiz: Quiz = { ...courseQuizFixture, status: 'in_progress', answer_records: [] }
    const writes: { path: string; body: unknown }[] = []
    const { client } = renderApp('/study/courses/course-1?lesson=lesson-1', (path, init) => {
      if (init.method === 'PATCH' || (init.method === 'POST' && path !== '/api/v1/experience/events'))
        writes.push({ path, body: init.body ? JSON.parse(String(init.body)) : null })
      if (path === `${lessonPath}/progress` && init.method === 'PATCH') {
        lesson = { ...lesson, read_at: '2026-09-13T01:20:00Z', revision: 2 }
        throw new TypeError('receipt lost after saving read=true')
      }
      if (path === quizPath) return json(quiz)
      return fixtureApi(path, lesson)
    })
    await userEvent.click(await screen.findByRole('button', { name: '记录已读，进入本课练习' }))
    expect(await screen.findByRole('heading', { name: courseQuizFixture.title })).toBeVisible()
    expect(writes).toEqual([{ path: `${lessonPath}/progress`, body: { expected_revision: 1, read: true } }])
    await act(async () => {
      quiz = courseQuizFixture
      await client.invalidateQueries({ predicate: (query) => query.queryKey.includes('quiz') })
    })
    await userEvent.click((await screen.findAllByRole('link', { name: '返回本课小结' }))[0])
    const summary = await screen.findByRole('region', { name: '本课小结' })
    expect(await within(summary).findByText('答对 2 / 3 题')).toBeVisible()
    expect(within(summary).queryByText(/5 \/ 6/)).not.toBeInTheDocument()
    expect(within(summary).getByText('已保存 1 / 3 题')).toBeVisible()
    expect(within(summary).getByText('已记录阅读')).toBeVisible()
    await waitFor(() => expect(summary).toHaveFocus())
    expect(writes).toHaveLength(1)
  })

  it.each(['in_progress', 'completed', 'wrong_context', 'read_error'] as const)(
    'does not infer completed practice or a score from %s', async (scenario) => {
      const lesson = { ...courseLessonFixture, quiz_links: [courseQuizLinkFixture] }
      let writes = 0
      renderApp('/study/courses/course-1?lesson=lesson-1#lesson-summary', (path, init) => {
        if (init.method === 'POST' && path !== '/api/v1/experience/events') writes++
        if (path === quizPath) {
          if (scenario === 'read_error') return apiFailure(503, 'result read unavailable')
          return json({ ...courseQuizFixture,
            status: scenario === 'wrong_context' ? 'settled' : scenario,
            course_context: scenario === 'wrong_context'
              ? { ...courseQuizFixture.course_context, lesson_id: 'lesson-other' } : courseQuizFixture.course_context })
        }
        if (scenario === 'read_error' && path.includes('/self-check-attempts')) return apiFailure(503)
        return fixtureApi(path, lesson)
      })
      const summary = await screen.findByRole('region', { name: '本课小结' })
      const message = scenario === 'in_progress' ? /练习尚未完成/ : scenario === 'completed'
        ? /历史练习状态待确认/ : scenario === 'wrong_context' ? /练习关联尚未确认/ : /结果暂未读回/
      expect(await within(summary).findByText(message)).toBeVisible()
      expect(within(summary).queryByText(/答对 \d/)).not.toBeInTheDocument()
      expect(within(summary).queryByText(/已完成结算/)).not.toBeInTheDocument()
      if (scenario === 'read_error') {
        expect(await within(summary).findByText('保存数量尚未确认')).toBeVisible()
        expect(within(summary).queryByText('已保存 0 / 3 题')).not.toBeInTheDocument()
      }
      expect(writes).toBe(0)
    },
  )

  it('ending an unfinished reading only opens the factual summary', async () => {
    const actions: string[] = []
    renderApp('/study/courses/course-1?lesson=lesson-1', (path, init) => {
      if (init.method === 'POST' || init.method === 'PATCH') actions.push(path)
      return fixtureApi(path)
    })
    await userEvent.click(await screen.findByRole('button', { name: '本次先到这里' }))
    const summary = await screen.findByRole('region', { name: '本课小结' })
    expect(within(summary).getByText('尚未记录已读')).toBeVisible()
    expect(actions.every((path) => path === '/api/v1/experience/events')).toBe(true)
  })
})
