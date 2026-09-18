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
  if (path.startsWith('/api/v1/study/spaces') || path.startsWith('/api/v1/study/reviews') || path.startsWith('/api/v1/study/history'))
    return json({ items: [], total: 0, page: 1, page_size: 6 })
  if (path === '/api/v1/knowledge/documents') return json({ items: [], total: 0 })
  if (path === '/api/v1/study/habits') return json({
    local_date: '2026-09-13', timezone: 'Asia/Shanghai', effective_days_total: 2,
    effective_streak_days: 1, rest_days_in_streak: 0, recent_days: [], rule_version: 'learning-habits-v1',
  })
  if (path === '/api/v1/study/habit-preferences') return json({ revision: 1, effective_from: '2026-09-13', weekly_rest_days: [] })
  if (path.startsWith('/api/v1/study/weekly-summary')) return json({
    week_start: '2026-09-07', week_end_exclusive: '2026-09-14', timezone: 'Asia/Shanghai',
    counts: { self_checks_saved: 1, quizzes_settled: 0, practices_completed: 0, applications_submitted: 0, scheduled_reviews_completed: 0 },
  })
  return apiFailure(404)
}
afterEach(() => vi.unstubAllGlobals())

describe('one lesson learning flow', () => {
  it('keeps the bookshelf on its own page alongside saved habits and weekly activity', async () => {
    renderApp('/study', (path) => fixtureApi(path))
    const shelf = await screen.findByRole('region', { name: '我的课程' })
    expect(await within(shelf).findByRole('button', { name: '主题课程 Python 函数入门' })).toBeVisible()
    expect(screen.getAllByRole('heading', { name: '我的课程' })).toHaveLength(1)
    expect(screen.queryByRole('region', { name: '今日学习建议' })).not.toBeInTheDocument()
    expect(await screen.findByRole('region', { name: '有效学习记录' })).toBeVisible()
    expect(await screen.findByRole('region', { name: '本周学习周报' })).toBeVisible()
  })

  it('links an empty daily recommendation to the dedicated bookshelf without duplicating it', async () => {
    renderApp('/', (path) => path.startsWith('/api/v1/courses/today')
      ? json({ ...courseTodayFixture, items: [] }) : fixtureApi(path))
    const link = await screen.findByRole('link', { name: '查看我的课程' })
    expect(link).toHaveAttribute('href', '/study#my-courses')
    expect(screen.queryByRole('region', { name: '我的课程' })).not.toBeInTheDocument()
    await userEvent.click(link)
    expect(await screen.findByRole('group', { name: '选择课程' })).toBeVisible()
  })

  it('keeps the server today order and enters its first suggested lesson', async () => {
    renderApp('/', (path) => fixtureApi(path))
    const today = await screen.findByRole('region', { name: '今日学习建议' })
    const action = await within(today).findByRole('link', { name: '继续阅读' })
    expect(action).toHaveClass('primary')
    expect(action).toHaveAttribute('href', '/study/courses/course-1?lesson=lesson-1')
    expect(within(today).getByRole('link', { name: '做本课三题' })).toHaveClass('secondary')
    expect(screen.getByRole('link', { name: '开始新课程' })).toHaveClass('primary')
    expect(screen.queryByRole('region', { name: '我的课程' })).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: /进入我的书架/ })).toHaveAttribute('href', '/study')
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

  it('retries the same read=true intent only after the learner reviews a newer revision', async () => {
    let lesson: CourseLessonView = { ...courseLessonFixture, quiz_links: [courseQuizLinkFixture] }
    const writes: { expected_revision: number; read: boolean }[] = []
    renderApp('/study/courses/course-1?lesson=lesson-1', (path, init) => {
      if (path === `${lessonPath}/progress` && init.method === 'PATCH') {
        const body = JSON.parse(String(init.body))
        writes.push(body)
        if (writes.length === 1) {
          lesson = { ...lesson, revision: 2 }
          return apiFailure(409, 'revision conflict')
        }
        lesson = { ...lesson, revision: 3, read_at: '2026-09-13T01:20:00Z' }
        return json(lesson)
      }
      if (path === quizPath) return json({ ...courseQuizFixture, status: 'in_progress', answer_records: [] })
      return fixtureApi(path, lesson)
    })
    await userEvent.click(await screen.findByRole('button', { name: '记录已读，进入本课练习' }))
    const retry = await screen.findByRole('button', { name: '核对后重试这次已读操作' })
    expect(screen.getByRole('article', { name: '当前课时' })).toBeVisible()
    expect(screen.queryByRole('heading', { name: courseQuizFixture.title })).not.toBeInTheDocument()
    expect(writes).toEqual([{ expected_revision: 1, read: true }])
    await userEvent.click(retry)
    expect(await screen.findByRole('heading', { name: courseQuizFixture.title })).toBeVisible()
    expect(writes).toEqual([{ expected_revision: 1, read: true }, { expected_revision: 2, read: true }])
  })

  it('recovers a saved read=false operation without toggling it back or opening practice', async () => {
    let lesson: CourseLessonView = { ...courseLessonFixture, read_at: '2026-09-13T01:20:00Z' }
    const writes: unknown[] = []
    renderApp('/study/courses/course-1?lesson=lesson-1', (path, init) => {
      if (path === `${lessonPath}/progress` && init.method === 'PATCH') {
        writes.push(JSON.parse(String(init.body)))
        lesson = { ...lesson, read_at: null, revision: 2 }
        throw new TypeError('read=false receipt lost')
      }
      if (path.endsWith('/quiz-jobs')) writes.push(path)
      return fixtureApi(path, lesson)
    })
    await userEvent.click(await screen.findByRole('button', { name: '取消已读标记' }))
    expect(await screen.findByText('取消已读的操作已保存。')).toBeVisible()
    expect(screen.getByRole('button', { name: '记录已读，进入本课练习' })).toBeEnabled()
    expect(screen.getByRole('region', { name: '本课小结' })).toHaveTextContent('尚未记录已读')
    expect(writes).toEqual([{ expected_revision: 1, read: false }])
  })

  it('abandons an in-flight read intent after explicit lesson navigation', async () => {
    let resolveSave!: (response: Response) => void
    let signal: AbortSignal | null | undefined
    let quizReads = 0
    let writes = 0
    const lesson = { ...courseLessonFixture, quiz_links: [courseQuizLinkFixture] }
    renderApp('/study/courses/course-1?lesson=lesson-1', (path, init) => {
      if (path === `${lessonPath}/progress` && init.method === 'PATCH') {
        writes++
        signal = init.signal
        return new Promise<Response>((resolve) => { resolveSave = resolve })
      }
      if (path === '/api/v1/courses/course-1/lessons/lesson-2')
        return json({ ...courseLessonFixture, lesson_id: 'lesson-2', title: '函数参数' })
      if (path.startsWith('/api/v1/courses/course-1/lessons/lesson-2/self-check-attempts')) return json([])
      if (path === quizPath) {
        quizReads++
        return json({ ...courseQuizFixture, status: 'in_progress', answer_records: [] })
      }
      return fixtureApi(path, lesson)
    })
    await userEvent.click(await screen.findByRole('button', { name: '记录已读，进入本课练习' }))
    await waitFor(() => expect(writes).toBe(1))
    const readsBeforeLeaving = quizReads
    await userEvent.click(screen.getByRole('button', { name: '继续下一课' }))
    expect(await screen.findByRole('heading', { name: '函数参数' })).toBeVisible()
    expect(signal?.aborted).toBe(true)
    await act(async () => { resolveSave(json({ ...lesson, read_at: '2026-09-13T01:20:00Z', revision: 2 })) })
    expect(screen.getByRole('heading', { name: '函数参数' })).toBeVisible()
    expect(screen.queryByRole('heading', { name: courseQuizFixture.title })).not.toBeInTheDocument()
    expect(quizReads).toBe(readsBeforeLeaving)
    expect(writes).toBe(1)
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
