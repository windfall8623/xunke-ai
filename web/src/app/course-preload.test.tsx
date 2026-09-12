import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AppRoutes } from './router'
import { apiFailure, json, session } from '../test/fixtures'

function mount(handler: (path: string, init: RequestInit) => Response) {
  vi.stubGlobal('fetch', async (path: string, init: RequestInit = {}) => handler(path, init))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return {
    ...render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={['/study/courses/new']}>
          <AppRoutes />
        </MemoryRouter>
      </QueryClientProvider>,
    ),
    client,
  }
}

afterEach(() => vi.unstubAllGlobals())

describe('course creation preload option', () => {
  it.each([true, false])(
    'submits preload_first_lesson=%s with the create request',
    async (preload) => {
      const writes: { path: string; data: unknown }[] = []
      mount((path, init) => {
        if (path.endsWith('/auth/capabilities')) return json({})
        if (path.endsWith('/auth/session')) return json(session)
        if (init.method === 'POST') writes.push({ path, data: JSON.parse(init.body as string) })
        if (path === '/api/v1/courses')
          return json({
            task_id: 'task-1',
            course_id: 'course-1',
            kind: 'course_outline',
            status: 'pending',
            stage: 'queued',
          })
        return apiFailure(404)
      })
      expect(
        await screen.findByRole('checkbox', { name: /创建后立即准备第一课内容/ }),
      ).toBeChecked()
      await userEvent.type(screen.getByLabelText(/学习主题/), 'Python 函数入门')
      if (!preload)
        await userEvent.click(screen.getByRole('checkbox', { name: /创建后立即准备第一课内容/ }))
      await userEvent.click(screen.getByRole('button', { name: '生成课程纲要' }))
      await waitFor(() => expect(writes.map((write) => write.path)).toEqual(['/api/v1/courses']))
      expect(writes[0].data).toMatchObject({
        topic: 'Python 函数入门',
        preload_first_lesson: preload,
      })
    },
  )
})
