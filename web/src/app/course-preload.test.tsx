import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiFailure, json, learner, session } from '../test/fixtures'
import { renderApp } from '../test/renderApp'

const createdTask = {
  task_id: 'task-1', course_id: 'course-1', kind: 'course_outline', status: 'pending', stage: 'queued',
}

function mountCreation(options: {
  modes?: string[]
  capabilities?: () => Response
  create?: (body: Record<string, unknown>, init: RequestInit) => Response
} = {}) {
  const writes: { body: Record<string, unknown>; key: string | null }[] = []
  const events: Record<string, unknown>[] = []
  const app = renderApp('/study/courses/new', (path, init) => {
    if (path.endsWith('/auth/capabilities')) return json({})
    if (path.endsWith('/auth/session')) return json(session)
    if (path.endsWith('/courses/capabilities')) return options.capabilities?.() || json({ teaching_modes: options.modes || ['fast', 'guided'] })
    if (path.endsWith('/experience/events')) {
      events.push(JSON.parse(init.body as string))
      return json(null)
    }
    if (path === '/api/v1/courses' && init.method === 'POST') {
      const body = JSON.parse(init.body as string)
      writes.push({ body, key: new Headers(init.headers).get('Idempotency-Key') })
      return options.create?.(body, init) || json(createdTask, 202)
    }
    return apiFailure(404)
  })
  return { ...app, writes, events }
}

async function enterTopic() {
  await userEvent.type(await screen.findByLabelText(/学习主题/), 'Python 函数入门')
  await waitFor(() => expect(screen.getByRole('button', { name: '生成课程纲要' })).toBeEnabled())
}

afterEach(() => vi.unstubAllGlobals())

describe('course creation options and safe submission', () => {
  it.each([true, false])('submits the recommended mode and preload_first_lesson=%s', async (preload) => {
    const { writes, events } = mountCreation()
    await enterTopic()
    const details = screen.getByText(/调整学习安排/).closest('details')
    expect(details).not.toHaveAttribute('open')
    expect(screen.getByRole('radio', { name: /标准教学（推荐）/ })).toBeChecked()
    if (!preload) {
      await userEvent.click(screen.getByText(/调整学习安排/))
      await userEvent.click(screen.getByRole('checkbox', { name: /创建后立即准备第一课内容/ }))
    }
    await userEvent.click(screen.getByRole('button', { name: '生成课程纲要' }))
    await waitFor(() => expect(writes).toHaveLength(1))
    expect(writes[0].body).toMatchObject({
      topic: 'Python 函数入门', daily_minutes: 20, lesson_count: 6, timezone: 'Asia/Shanghai',
      preload_first_lesson: preload, teaching_mode: 'guided',
    })
    await waitFor(() => expect(events.map((event) => event.name)).toEqual(['course_create_viewed', 'course_create_submitted']))
    expect(events[1]).toMatchObject({ course_id: 'course-1', task_id: 'task-1' })
  })

  it('lets the learner explicitly select fast generation', async () => {
    const { writes } = mountCreation()
    await enterTopic()
    await userEvent.click(screen.getByRole('radio', { name: /快速生成/ }))
    expect(JSON.parse(sessionStorage.getItem(`course-draft:${learner.id}`) || '{}').draft.teaching_mode).toBe('fast')
    await userEvent.click(screen.getByRole('button', { name: '生成课程纲要' }))
    await waitFor(() => expect(writes[0].body.teaching_mode).toBe('fast'))
  })

  it('visibly selects fast and explains the missing teaching review when guided is disabled', async () => {
    const { writes } = mountCreation({ modes: ['fast'] })
    await enterTopic()
    expect(screen.getByRole('radio', { name: /标准教学（暂不可用）/ })).toBeDisabled()
    expect(screen.getByRole('radio', { name: /快速生成/ })).toBeChecked()
    expect(screen.getByText('本课程使用快速生成，未执行教学检查。')).toBeVisible()
    await userEvent.click(screen.getByRole('button', { name: '生成课程纲要' }))
    await waitFor(() => expect(writes[0].body.teaching_mode).toBe('fast'))
  })

  it('keeps submission disabled while capability discovery has failed', async () => {
    const { writes } = mountCreation({ capabilities: () => apiFailure(503) })
    await userEvent.type(await screen.findByLabelText(/学习主题/), '学习函数')
    expect(await screen.findByText('暂时无法确认教学方式，请重新读取后创建课程。')).toBeVisible()
    expect(screen.getByRole('button', { name: '生成课程纲要' })).toBeDisabled()
    expect(writes).toHaveLength(0)
  })

  it('restores custom legacy drafts, expands their settings and reveals an invalid hidden field', async () => {
    sessionStorage.setItem(`course-draft:${learner.id}`, JSON.stringify({ version: 1, draft: {
      topic: '原课程主题', goal: '用例验证函数', prior_knowledge: '会循环', daily_minutes: 30,
      lesson_count: 4, timezone: 'UTC', preload_first_lesson: false, source_policy: 'topic',
    } }))
    const { writes } = mountCreation()
    await screen.findByDisplayValue('原课程主题')
    expect(screen.getByText(/调整学习安排/).closest('details')).toHaveAttribute('open')
    expect(screen.getByLabelText('希望学会什么')).toHaveValue('用例验证函数')
    expect(screen.getByLabelText('已有基础')).toHaveValue('会循环')
    expect(screen.getByLabelText(/学习时区/)).toHaveValue('UTC')
    expect(screen.getByRole('checkbox', { name: /创建后立即准备第一课内容/ })).not.toBeChecked()
    const minutes = screen.getByLabelText('每天学习时长（分钟）')
    await userEvent.clear(minutes)
    await userEvent.type(minutes, '2')
    await userEvent.click(screen.getByText(/调整学习安排/))
    await userEvent.click(screen.getByRole('button', { name: '生成课程纲要' }))
    await waitFor(() => expect(screen.getByText(/调整学习安排/).closest('details')).toHaveAttribute('open'))
    expect(minutes).toHaveFocus()
    expect(writes).toHaveLength(0)
    await userEvent.clear(minutes)
    await userEvent.type(minutes, '30')
    await userEvent.click(screen.getByRole('button', { name: '生成课程纲要' }))
    await waitFor(() => expect(writes[0].body).toMatchObject({ daily_minutes: 30, lesson_count: 4, timezone: 'UTC', preload_first_lesson: false, teaching_mode: 'guided' }))
  })

  it('retries a lost creation response with the immutable original request and key', async () => {
    let attempts = 0
    const { writes } = mountCreation({ create: () => {
      if (++attempts === 1) throw new TypeError('lost receipt')
      return json(createdTask, 202)
    } })
    await enterTopic()
    await userEvent.click(screen.getByRole('button', { name: '生成课程纲要' }))
    expect(await screen.findByText(/提交结果尚未确认/)).toBeVisible()
    expect(screen.getByLabelText(/学习主题/)).toBeDisabled()
    expect(writes).toHaveLength(1)
    await userEvent.click(screen.getByRole('button', { name: '重试原创建请求' }))
    await waitFor(() => expect(writes).toHaveLength(2))
    expect(writes[1]).toEqual(writes[0])
    expect(writes[0].key).toBeTruthy()
  })

  it('refreshes capabilities after a guided conflict and waits for a reviewed second submission', async () => {
    let available = true
    const { writes } = mountCreation({
      capabilities: () => json({ teaching_modes: available ? ['fast', 'guided'] : ['fast'] }),
      create: () => {
        if (available) {
          available = false
          return new Response(JSON.stringify({ code: 4090, error_code: 'teaching_agents_unavailable', message: 'unavailable' }), { status: 409, headers: { 'Content-Type': 'application/json' } })
        }
        return json(createdTask, 202)
      },
    })
    await enterTopic()
    await userEvent.click(screen.getByRole('button', { name: '生成课程纲要' }))
    await screen.findByText('教学方式的可用状态已变化，请核对上方选择后再次提交。')
    await waitFor(() => expect(screen.getByRole('button', { name: '重试创建课程' })).toBeEnabled())
    expect(screen.getByRole('radio', { name: /快速生成/ })).toBeChecked()
    expect(writes).toHaveLength(1)
    await userEvent.click(screen.getByRole('button', { name: '重试创建课程' }))
    await waitFor(() => expect(writes).toHaveLength(2))
    expect(writes[0].body.teaching_mode).toBe('guided')
    expect(writes[1].body.teaching_mode).toBe('fast')
    expect(writes[1].key).not.toBe(writes[0].key)
  })
})
