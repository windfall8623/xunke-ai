import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

const requestMock = vi.fn((path: string, options?: { method?: string }) => {
  if (path === '/study/habits') {
    return Promise.resolve({
      local_date: '2026-09-13',
      timezone: 'Asia/Shanghai',
      effective_streak_days: 2,
      rest_days_in_streak: 1,
      effective_days_total: 5,
      last_effective_local_date: '2026-09-12',
      recent_days: [
        { local_date: '2026-09-12', kind: 'learning', activity_count: 2 },
        { local_date: '2026-09-13', kind: 'today_pending', activity_count: 0 },
      ],
      milestones: [
        { effective_days: 1, reached: true, reached_on: '2026-09-01' },
        { effective_days: 3, reached: false, reached_on: null },
      ],
      rule_version: 'learning-habits-v1',
    })
  }
  if (path === '/study/habit-preferences' && options?.method === 'PATCH') {
    return Promise.resolve({
      revision: 3, weekly_rest_days: [5, 6], effective_from: '2026-09-13',
    })
  }
  return Promise.resolve({ revision: 2, weekly_rest_days: [6], effective_from: '2026-09-13' })
})

vi.mock('../../services/http', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../services/http')>()
  return { ...actual, request: (path: string, options?: { method?: string }) => requestMock(path, options) }
})

import { LearningHabitCard } from './LearningHabitCard'

describe('LearningHabitCard', () => {
  it('explains that counts come from saved activities, not mastery or page views', async () => {
    render(<LearningHabitCard />)
    expect(await screen.findByText(/连续有效学习/)).toBeVisible()
    expect(screen.getByText(/期间休息 1 天/)).toBeVisible()
    expect(screen.getByText(/累计 5 天/)).toBeVisible()
    expect(screen.getByText(/按已保存的学习活动统计，不代表已掌握/)).toBeVisible()
    expect(screen.getByText(/打开页面不计入/)).toBeVisible()
    expect(screen.getByText('2')).toBeVisible()
  })

  it('saves rest-day changes with the server revision and shows honest framing', async () => {
    render(<LearningHabitCard />)
    // 等待已保存的休息偏好读回，再点击新的休息日。
    await waitFor(() => {
      expect(requestMock.mock.calls.some(([path]) => path === '/study/habit-preferences')).toBe(true)
    })
    await userEvent.click(await screen.findByRole('button', { name: '周六' }))
    await waitFor(() => {
      const patch = requestMock.mock.calls.find(
        ([path, options]) => path === '/study/habit-preferences' &&
          (options as { method?: string } | undefined)?.method === 'PATCH',
      ) as unknown as [string, { data: unknown }] | undefined
      expect(patch).toBeTruthy()
      expect(patch![1].data).toEqual({
        expected_revision: 2, weekly_rest_days: [5, 6],
      })
    })
  })
})
