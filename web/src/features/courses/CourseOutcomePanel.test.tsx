import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { countOutcomes } from './courseOutcomeFacts'
import { CourseOutcomePanel } from './CourseOutcomePanel'
import type { CourseOutcomeSummary } from '../../types/course'

vi.mock('./CourseOutcomeEvidence', () => ({
  CourseOutcomeEvidence: ({ onClose }: { onClose: () => void }) => (
    <div role="dialog" aria-label="目标与证据">
      证据抽屉
      <button type="button" onClick={onClose}>关闭</button>
    </div>
  ),
}))

const summary = (statuses: string[]): CourseOutcomeSummary => ({
  course_id: 'course-1',
  criteria_revision: 1,
  criteria: statuses.map((status, index) => ({
    course_criterion_id: `cc-${index}`,
    criteria_revision: 1,
    title: `目标 ${index + 1}`,
    status,
    reason: `状态原因：${status}`,
    evidence_refs: status === 'verified'
      ? [{ origin_kind: 'quiz', origin_id: 'quiz-1', occurred_at: '2026-09-13T02:00:00Z' }]
      : [],
  })),
}) as unknown as CourseOutcomeSummary

describe('CourseOutcomePanel', () => {
  it('counts four states without inventing a mastery percentage', () => {
    expect(countOutcomes(['verified', 'needs_practice', 'unverified', 'stale'])).toEqual({
      verified: 1, needs_practice: 1, unverified: 1, stale: 1,
    })
  })

  it('renders status labels, reasons and an evidence drawer per goal', async () => {
    render(
      <MemoryRouter>
        <CourseOutcomePanel
          outcomes={summary(['verified', 'needs_practice', 'unverified', 'stale'])}
        />
      </MemoryRouter>,
    )
    expect(screen.getByText(/已验证 1 项 \/ 共 4 项/)).toBeVisible()
    expect(screen.getByText(/待重新验证 1 项/)).toBeVisible()
    expect(screen.getAllByText(/状态原因：/)).toHaveLength(4)
    expect(screen.queryByText(/掌握率/)).not.toBeInTheDocument()

    await userEvent.click(screen.getAllByRole('button', { name: '查看证据' })[0])
    expect(screen.getByRole('dialog', { name: '目标与证据' })).toBeVisible()
    await userEvent.click(screen.getByRole('button', { name: '关闭' }))
    expect(screen.queryByRole('dialog', { name: '目标与证据' })).not.toBeInTheDocument()
  })

  it('shows the legacy empty state without calling any model', () => {
    render(
      <MemoryRouter>
        <CourseOutcomePanel outcomes={summary([])} />
      </MemoryRouter>,
    )
    expect(screen.getByText(/本课程尚无可验证目标记录/)).toBeVisible()
    expect(screen.queryByRole('button', { name: '查看证据' })).not.toBeInTheDocument()
  })
})
