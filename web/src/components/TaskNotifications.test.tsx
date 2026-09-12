import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AuthProvider } from '../app/AuthProvider'
import { apiFailure, json, session } from '../test/fixtures'
import { TaskNotifications } from './TaskNotifications'

const task = {
  task_id: 'task-quiz-1',
  kind: 'quiz',
  status: 'pending',
  stage: 'queued',
  error_code: null,
  title: '光合作用',
  course_id: null,
  course_title: null,
  lesson_id: null,
  quiz_id: null,
  doc_id: null,
  created_at: '2026-09-12T00:00:00Z',
  updated_at: '2026-09-12T00:00:00Z',
}

function mount(initial: string, handler: (path: string) => Response) {
  vi.stubGlobal('fetch', async (path: string) => handler(path))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <AuthProvider>
        <MemoryRouter initialEntries={[initial]}>
          <TaskNotifications />
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  )
  return client
}

afterEach(() => vi.unstubAllGlobals())

function overview(tasks: unknown[]) {
  return json({ tasks, documents: [] })
}

describe('global task notifications', () => {
  it('toasts only on the transition to a terminal state', async () => {
    let completed = false
    const client = mount('/', (path) => {
      if (path.endsWith('/auth/session')) return json(session)
      if (path.endsWith('/tasks/active'))
        return completed ? overview([{ ...task, status: 'completed' }]) : overview([task])
      return apiFailure(404)
    })
    // 首帧快照只做基线，不弹提示。
    await waitFor(() =>
      expect(client.getQueryState(['task-overview'])?.status).toBe('success'),
    )
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    completed = true
    await client.refetchQueries({ queryKey: ['task-overview'] })
    expect(await screen.findByRole('status')).toHaveTextContent('练习「光合作用」已准备好')
    expect(screen.getByRole('button', { name: '查看' })).toBeVisible()
    await userEvent.click(screen.getByRole('button', { name: '关闭提醒' }))
    await waitFor(() => expect(screen.queryByRole('status')).not.toBeInTheDocument())
  })

  it('toasts failures and stays quiet on the task detail page', async () => {
    let completed = false
    const client = mount('/tasks/task-quiz-1', (path) => {
      if (path.endsWith('/auth/session')) return json(session)
      if (path.endsWith('/tasks/active'))
        return completed
          ? overview([{ ...task, status: 'failed', error_code: 'deadline_exceeded' }])
          : overview([task])
      return apiFailure(404)
    })
    await waitFor(() =>
      expect(client.getQueryState(['task-overview'])?.status).toBe('success'),
    )
    completed = true
    await client.refetchQueries({ queryKey: ['task-overview'] })
    // 任务详情页就在当前路由，不重复打扰。
    await new Promise((resolve) => setTimeout(resolve, 30))
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('toasts a failure when the user is elsewhere', async () => {
    let completed = false
    const client = mount('/study', (path) => {
      if (path.endsWith('/auth/session')) return json(session)
      if (path.endsWith('/tasks/active'))
        return completed
          ? overview([{ ...task, status: 'failed', error_code: 'deadline_exceeded' }])
          : overview([task])
      return apiFailure(404)
    })
    await waitFor(() =>
      expect(client.getQueryState(['task-overview'])?.status).toBe('success'),
    )
    completed = true
    await client.refetchQueries({ queryKey: ['task-overview'] })
    expect(await screen.findByRole('status')).toHaveTextContent('练习「光合作用」未完成')
    expect(screen.getByRole('button', { name: '打开' })).toBeVisible()
  })
})
