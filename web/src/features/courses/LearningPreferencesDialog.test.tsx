import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

const getPreferences = vi.fn()
const updatePreferences = vi.fn()

vi.mock('../../services/studyPreferences', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../services/studyPreferences')>()
  return {
    ...actual,
    getPreferences: (...args: unknown[]) => getPreferences(...args),
    updatePreferences: (...args: unknown[]) => updatePreferences(...args),
  }
})

import { LearningPreferencesDialog } from './LearningPreferencesDialog'

describe('LearningPreferencesDialog', () => {
  it('saves with the server revision and explains difficulty is a user choice', async () => {
    getPreferences.mockResolvedValue({
      revision: 1, daily_minutes: 20, daily_review_limit: 1,
      difficulty: 'mixed', timezone: 'Asia/Shanghai',
    })
    updatePreferences.mockResolvedValue({
      revision: 2, daily_minutes: 45, daily_review_limit: 0,
      difficulty: 'hard', timezone: 'Asia/Shanghai',
    })
    render(<LearningPreferencesDialog onClose={() => {}} />)
    await screen.findByDisplayValue('20')
    expect(screen.getByText(/不是系统测得的能力/)).toBeVisible()
    expect(screen.getByText(/时区：Asia\/Shanghai/)).toBeVisible()

    const minutes = screen.getByLabelText('每天学习时间（分钟，5–120）')
    await userEvent.clear(minutes)
    await userEvent.type(minutes, '45')
    await userEvent.click(screen.getByRole('radio', { name: '增加挑战' }))
    const limit = screen.getByLabelText('每天新推荐的复习数量（0–3）')
    await userEvent.clear(limit)
    await userEvent.type(limit, '0')
    await userEvent.click(screen.getByRole('button', { name: '保存学习偏好' }))
    await waitFor(() => expect(updatePreferences).toHaveBeenCalled())
    expect(updatePreferences.mock.calls[0][0]).toEqual({
      expected_revision: 1, daily_minutes: 45, daily_review_limit: 0,
      difficulty: 'hard', timezone: 'Asia/Shanghai',
    })
    await screen.findByText('已保存')
  })

  it('keeps the read failure honest instead of fake defaults', async () => {
    getPreferences.mockRejectedValue(new Error('network down'))
    render(<LearningPreferencesDialog onClose={() => {}} />)
    expect(await screen.findByText('学习偏好暂未读回，请稍后重试。')).toBeVisible()
    expect(screen.queryByRole('button', { name: '保存学习偏好' })).not.toBeInTheDocument()
  })
})
