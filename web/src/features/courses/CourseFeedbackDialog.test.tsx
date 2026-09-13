import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

const createFeedback = vi.fn()
const listFeedback = vi.fn()
const createCorrection = vi.fn()

vi.mock('../../services/courseFeedback', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../services/courseFeedback')>()
  return {
    ...actual,
    createCourseFeedback: (...args: unknown[]) => createFeedback(...args),
    listCourseFeedback: (...args: unknown[]) => listFeedback(...args),
    createCourseCorrection: (...args: unknown[]) => createCorrection(...args),
  }
})

import { CourseFeedbackDialog } from './CourseFeedbackDialog'

const target = {
  kind: 'self_check',
  lesson_id: 'lesson-1',
  content_version: 1,
  check_attempt_id: 'attempt-1',
} as const

describe('CourseFeedbackDialog', () => {
  it('creates an issue from the entry form and keeps kind selection honest', async () => {
    listFeedback.mockResolvedValue({ items: [], total: 0 })
    createFeedback.mockResolvedValue({
      feedback_id: 'fb-1',
      course_id: 'course-1',
      issue_kind: 'content_error',
      target,
      comment: '这段与资料矛盾。',
      status: 'open',
      revision: 1,
      tutor_turn_id: null,
      quiz_feedback_id: null,
      corrections: [],
      created_at: '2026-09-13T00:00:00Z',
    })
    render(<CourseFeedbackDialog courseId="course-1" entry={{ kind: 'confusion', target }} onClose={() => {}} />)
    await screen.findByText('问题类型')
    await userEvent.click(screen.getByRole('radio', { name: '内容有误' }))
    await userEvent.type(screen.getByLabelText('内容有误说明'), '这段与资料矛盾。')
    await userEvent.click(screen.getByRole('button', { name: '保存这条反馈' }))
    await waitFor(() => expect(createFeedback).toHaveBeenCalled())
    expect(createFeedback.mock.calls[0][1]).toMatchObject({ issue_kind: 'content_error', comment: '这段与资料矛盾。' })
    expect(await screen.findByText('已记录，待处理')).toBeVisible()
    expect(screen.getByText(/尚无已确认纠正/)).toBeVisible()
  })

  it('shows reviewer confirmations separately from provisional notes', async () => {
    listFeedback.mockResolvedValue({
      items: [{
        feedback_id: 'fb-2',
        course_id: 'course-1',
        issue_kind: 'content_error',
        target,
        comment: '原回答与纠正说明并排展示。',
        status: 'open',
        revision: 2,
        tutor_turn_id: null,
        quiz_feedback_id: null,
        created_at: '2026-09-13T00:00:00Z',
        corrections: [
          { correction_id: 'c1', feedback_id: 'fb-2', supersedes_correction_id: null,
            text: '我认为是 in block 而不是 let。', source_refs: [],
            provenance: 'learner_note', confirmation: 'provisional', created_at: '2026-09-13T00:01:00Z' },
          { correction_id: 'c2', feedback_id: 'fb-2', supersedes_correction_id: 'c1',
            text: '对照原文确认：应为 in block。', source_refs: [],
            provenance: 'human_reviewer', confirmation: 'confirmed', created_at: '2026-09-13T00:02:00Z' },
        ],
      }],
      total: 1,
    })
    render(<CourseFeedbackDialog courseId="course-1" entry={{ kind: 'content_error', target }} onClose={() => {}} />)
    expect(await screen.findByText(/复核说明：对照原文确认/)).toBeVisible()
    expect(screen.getByText(/我的纠正：/)).toBeVisible()
    expect(screen.getByText(/已确认内容需要修订/)).toBeVisible()
    expect(screen.queryByText(/尚未确认/)).not.toBeInTheDocument()
    expect(listFeedback).toHaveBeenCalled()
    expect(listFeedback.mock.calls[0][1]).toMatchObject({
      lesson_id: 'lesson-1',
      check_attempt_id: 'attempt-1',
    })
  })
})
