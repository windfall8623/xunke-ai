import { describe, expect, it } from 'vitest'
import {
  courseApplicationAttemptFixture,
  courseAssessmentFixture,
  courseCriteriaFixture,
  courseOutcomesFixture,
} from '../../test/courseFixtures'
import type { CourseApplicationAttemptView } from '../../types/course'
import {
  applicationFeedbackState,
  assessmentFlowState,
  assessmentGoals,
  isProvisionalFeedback,
  isVerifiedOutcome,
  outcomeTally,
  uncoveredGoals,
} from './courseOutcomeFacts'

const graded: CourseApplicationAttemptView['feedback'] = {
  assessment_id: 'grade-1',
  status: 'graded',
  confirmation: 'confirmed',
  created_at: '2026-09-13T02:20:00Z',
  criterion_results: [{ criterion_id: 'r1', credit: 'full' }],
}

describe('assessment goal coverage', () => {
  const goals = assessmentGoals(courseAssessmentFixture, courseOutcomesFixture, courseCriteriaFixture)

  it('keeps every course goal visible with its own coverage flag', () => {
    expect(goals).toHaveLength(2)
    expect(goals.find((goal) => goal.courseCriterionId === 'criterion-scope')?.covered).toBe(true)
    expect(goals.find((goal) => goal.courseCriterionId === 'criterion-build')?.covered).toBe(false)
  })

  it('lists goals this check never covered', () => {
    expect(uncoveredGoals(goals).map((goal) => goal.courseCriterionId)).toEqual(['criterion-build'])
  })

  it('never counts an unverified projection as verified', () => {
    expect(goals.every((goal) => !isVerifiedOutcome(goal))).toBe(true)
    expect(outcomeTally(courseOutcomesFixture.criteria || [])).toMatchObject({
      total: 2,
      verified: 0,
      unverified: 2,
    })
  })
})

describe('assessmentFlowState', () => {
  it('separates a sealed flow from goal verification', () => {
    expect(assessmentFlowState({ ...courseAssessmentFixture, status: 'completed' })).toBe('completed')
    expect(assessmentFlowState(courseAssessmentFixture)).toBe('ready_to_complete')
  })

  it('reports generation and terminal states from the server record', () => {
    expect(assessmentFlowState({ ...courseAssessmentFixture, status: 'generating' })).toBe('generating')
    expect(assessmentFlowState({ ...courseAssessmentFixture, status: 'failed' })).toBe('failed')
    expect(assessmentFlowState(null)).toBe('none')
  })
})

describe('application feedback state', () => {
  it('keeps a saved answer visible when the feedback queue was unavailable', () => {
    expect(applicationFeedbackState(courseApplicationAttemptFixture)).toBe('queue_unavailable')
    expect(courseApplicationAttemptFixture.answer).not.toBe('')
  })

  it('separates a failed feedback task from the saved answer', () => {
    const state = applicationFeedbackState({
      ...courseApplicationAttemptFixture,
      feedback_task_id: 'feedback-task-1',
      feedback_task: {
        task_id: 'feedback-task-1',
        status: 'failed',
        stage: 'generating',
        business_settled: false,
        error_code: 'provider_unavailable',
      },
    })
    expect(state).toBe('failed')
  })

  it('treats provisional and needs_review feedback as not confirmed', () => {
    expect(isProvisionalFeedback({ ...graded, confirmation: 'provisional' })).toBe(true)
    expect(isProvisionalFeedback({ ...graded, status: 'needs_review' })).toBe(true)
    expect(isProvisionalFeedback(graded)).toBe(false)
    expect(
      applicationFeedbackState({ ...courseApplicationAttemptFixture, feedback: { ...graded, status: 'needs_review' } }),
    ).toBe('needs_review')
  })
})
