import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { feedbackForAttempt, newlySavedCheck, teachingFeedbackState } from '../features/courses/courseActionState'
import { renderApp } from '../test/renderApp'
import { apiFailure, json, session } from '../test/fixtures'
import { courseCheckFixture, courseFixture, courseLessonFixture, courseOutcomesFixture,
  courseProgressFixture, courseTutorFixture } from '../test/courseFixtures'
import type { CourseSelfCheckView, CourseTutorTurnView } from '../types/course'

const lessonPath = '/api/v1/courses/course-1/lessons/lesson-1'
const checksPath = `${lessonPath}/self-check-attempts`
const turnsPath = `${lessonPath}/tutor-turns`
function fixtureApi(path: string) {
  if (path.endsWith('/auth/capabilities')) return json({})
  if (path.endsWith('/auth/session')) return json(session)
  if (path === '/api/v1/experience/events') return json(null)
  if (path === '/api/v1/courses/course-1') return json(courseFixture)
  if (path === lessonPath) return json(courseLessonFixture)
  if (path.endsWith('/course-1/progress')) return json(courseProgressFixture)
  if (path.endsWith('/course-1/reviews')) return json([])
  // A07 结业面板挂到课程页后，outcome/assessment 读取失败会被视为课程不可访问。
  if (path.endsWith('/course-1/outcomes')) return json(courseOutcomesFixture)
  if (path.endsWith('/course-1/assessments')) return json([])
  return apiFailure(404)
}
const mount = (handler: (path: string, init: RequestInit) => Response | Promise<Response>) =>
  renderApp('/study/courses/course-1?lesson=lesson-1', handler)
async function firstCheck() {
  const textbox = await screen.findByRole('textbox', { name: /填写你的理解/ })
  return { textbox, item: within(textbox.closest('li')!) }
}
afterEach(() => vi.unstubAllGlobals())

describe('saved self checks and teaching feedback', () => {
  it('saves without a tutor call and restores the same answer after reopening the lesson', async () => {
    let attempts: CourseSelfCheckView[] = []
    let writes = 0
    const handler = (path: string, init: RequestInit) => {
      if (path === checksPath && init.method === 'POST') {
        writes++
        attempts = [{ ...courseCheckFixture, answer: JSON.parse(String(init.body)).answer }]
        return json(attempts[0], 201)
      }
      if (path.startsWith(checksPath)) return json(attempts)
      if (path.startsWith(turnsPath)) return json([])
      return fixtureApi(path)
    }
    const first = mount(handler)
    const { textbox, item } = await firstCheck()
    await userEvent.type(textbox, String(courseCheckFixture.answer))
    await userEvent.click(item.getByRole('button', { name: '保存回答' }))
    expect(await item.findByRole('button', { name: '回答已保存' })).toBeDisabled()
    expect(item.getByText(/已保存于/)).toBeVisible()
    first.unmount()
    first.client.clear()
    mount(handler)
    // B02：重开后输入为空；旧答案保存成功后经「比较以前的回答」对照。
    expect((await firstCheck()).textbox).toHaveValue('')
    expect(writes).toBe(1)
  })

  it('confirms a lost save response only from a new matching record', async () => {
    let attempts: CourseSelfCheckView[] = []
    let reads = 0
    let writes = 0
    mount((path, init) => {
      if (path === checksPath && init.method === 'POST') {
        writes++
        attempts = [{ ...courseCheckFixture, answer: JSON.parse(String(init.body)).answer }]
        throw new TypeError('connection lost after the write')
      }
      if (path.startsWith(checksPath)) { reads++; return json(attempts) }
      if (path.startsWith(turnsPath)) return json([])
      return fixtureApi(path)
    })
    const { textbox, item } = await firstCheck()
    await userEvent.type(textbox, String(courseCheckFixture.answer))
    await userEvent.click(item.getByRole('button', { name: '保存回答' }))
    expect(await item.findByRole('button', { name: '回答已保存' })).toBeDisabled()
    expect(writes).toBe(1)
    expect(reads).toBeGreaterThanOrEqual(2)
    expect(newlySavedCheck([courseCheckFixture], { check_ref: 'check-1', expected_content_version: 1,
      answer: courseCheckFixture.answer }, new Set(['attempt-1']))).toBeUndefined()
  })

  it('checks an unknown save before retrying the identical request, even after the draft changes', async () => {
    const writes: { key: string | null; body: string }[] = []
    let attempts: CourseSelfCheckView[] = []
    mount((path, init) => {
      if (path === checksPath && init.method === 'POST') {
        writes.push({ key: new Headers(init.headers).get('Idempotency-Key'), body: String(init.body) })
        if (writes.length === 1) throw new TypeError('connection lost')
        attempts = [{ ...courseCheckFixture, answer: JSON.parse(String(init.body)).answer }]
        return json(attempts[0], 201)
      }
      if (path.startsWith(checksPath)) return json(attempts)
      if (path.startsWith(turnsPath)) return json([])
      return fixtureApi(path)
    })
    const { textbox, item } = await firstCheck()
    await userEvent.type(textbox, '原回答')
    await userEvent.click(item.getByRole('button', { name: '保存回答' }))
    await item.findByText(/提交结果尚未确认/)
    await userEvent.clear(textbox)
    await userEvent.type(textbox, '后来修改的草稿')
    await userEvent.click(item.getByRole('button', { name: '核对保存结果' }))
    await userEvent.click(await item.findByRole('button', { name: '重试原回答的保存' }))
    await waitFor(() => expect(writes).toHaveLength(2))
    expect(writes[0].key).toBeTruthy()
    expect(writes[1]).toEqual(writes[0])
    expect(attempts[0].answer).toBe('原回答')
    expect(textbox).toHaveValue('后来修改的草稿')
    expect(await item.findByText(/修改尚未保存/)).toBeVisible()
  })

  it('reads completed feedback until its answer arrives without creating another tutor task', async () => {
    let ready = false
    let reads = 0
    let tutorWrites = 0
    mount((path, init) => {
      if (path.startsWith(checksPath)) return json([courseCheckFixture])
      if (path.startsWith(turnsPath)) {
        if (init.method === 'POST') tutorWrites++
        reads++
        return json([{ ...courseTutorFixture, answer: ready ? '这里的变量仍在作用域内。' : null }])
      }
      return fixtureApi(path)
    })
    const { item } = await firstCheck()
    expect(await item.findByText(/反馈已生成，正在读取/)).toBeVisible()
    expect(item.queryByText(/本次生成未完成/)).not.toBeInTheDocument()
    ready = true
    await userEvent.click(item.getByRole('button', { name: '刷新反馈' }))
    expect(await item.findByText('这里的变量仍在作用域内。')).toBeVisible()
    expect(reads).toBeGreaterThan(1)
    expect(tutorWrites).toBe(0)
    expect(teachingFeedbackState(courseTutorFixture)).toBe('syncing')
    expect(feedbackForAttempt(courseCheckFixture, { ...courseTutorFixture, check_attempt_id: 'other-attempt' })).toBeNull()
  })

  it('retries a failed feedback turn while retaining its saved answer and attempt', async () => {
    let turn: CourseTutorTurnView = { ...courseTutorFixture,
      task: { ...courseTutorFixture.task, status: 'failed', stage: 'failed', error_code: 'provider_not_configured' } }
    const writes: string[] = []
    mount((path, init) => {
      if (init.method === 'POST' && path.startsWith(turnsPath)) {
        writes.push(path)
        turn = { ...turn, answer: '这次反馈对应原来保存的回答。',
          task: { ...turn.task, task_id: 'tutor-task-2', status: 'completed', stage: 'completed' } }
        return json(turn, 202)
      }
      if (path.startsWith(checksPath)) return json([courseCheckFixture])
      if (path.startsWith(turnsPath)) return json([turn])
      return fixtureApi(path)
    })
    const { textbox, item } = await firstCheck()
    await userEvent.click(await item.findByRole('button', { name: '重试这次反馈' }))
    expect(await item.findByText('这次反馈对应原来保存的回答。')).toBeVisible()
    expect(textbox).toHaveValue('')
    expect(turn.check_attempt_id).toBe(courseCheckFixture.attempt_id)
    expect(writes).toEqual([`${turnsPath}/turn-1/retry`])
  })
})
