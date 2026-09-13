import { describe, expect, it } from 'vitest'
import type { CourseTaskView, TeachingQualitySummary } from '../../types/course'
import { agentProgressFact, teachingQualityFact } from './courseQualityFacts'

const reviewed: TeachingQualitySummary = {
  level: 'lesson',
  status: 'reviewed',
  draft_hash: 'draft-abc',
  artifact_hash: 'artifact-abc',
  reason_code: null,
  warnings: [],
}

const task = (patch: Partial<CourseTaskView> = {}): CourseTaskView => ({
  task_id: 'task-1',
  course_id: 'course-1',
  kind: 'course_lesson',
  status: 'running',
  stage: 'teaching',
  business_settled: false,
  ...patch,
})

describe('teachingQualityFact', () => {
  it('only reports reviewed for a passing report bound to the published artifact', () => {
    expect(teachingQualityFact(reviewed, 'guided').status).toBe('reviewed')
  })

  it('does not claim a review for a course without any quality summary', () => {
    const fact = teachingQualityFact(null, 'fast')
    expect(fact.status).toBe('unreviewed')
    expect(fact.reason).toContain('未请求教学核对')
  })

  it('degrades a reviewed status that is not bound to the current artifact', () => {
    const fact = teachingQualityFact({ ...reviewed, artifact_hash: null }, 'guided')
    expect(fact.status).toBe('unreviewed')
    expect(fact.unbound).toBe(true)
    expect(fact.reason).toContain('原核对结果不适用于当前版本')
  })

  it('drops advisory warnings when the review did not pass', () => {
    const fact = teachingQualityFact(
      { ...reviewed, status: 'needs_revision', artifact_hash: null, warnings: ['部分术语较集中'] },
      'guided',
    )
    expect(fact.status).toBe('needs_revision')
    expect(fact.warnings).toEqual([])
  })

  it('explains a fixed reason code without exposing hashes', () => {
    const fact = teachingQualityFact(
      { ...reviewed, status: 'unreviewed', artifact_hash: null, reason_code: 'review_timeout' },
      'guided',
    )
    expect(fact.reason).toContain('超时')
    expect(fact.reason).not.toContain('draft-abc')
  })
})

describe('agentProgressFact', () => {
  it('shows no collaboration for a fast task that never entered a role stage', () => {
    const fact = agentProgressFact(task({ stage: 'generating' }), 'fast')
    expect(fact.collaborating).toBe(false)
    expect(fact.steps).toEqual([])
  })

  it('marks only the observed stage active and never completes future work', () => {
    const fact = agentProgressFact(task({ stage: 'teaching' }), 'guided')
    expect(fact.collaborating).toBe(true)
    expect(fact.steps.find((step) => step.stage === 'teaching')?.state).toBe('active')
    expect(fact.steps.find((step) => step.stage === 'reviewing')?.state).toBe('expected')
    expect(fact.steps.find((step) => step.stage === 'revising')?.state).toBe('conditional')
  })

  it('treats unobserved stages of a finished task as unknown, not done', () => {
    const fact = agentProgressFact(task({ stage: 'reviewing', status: 'failed' }), 'guided')
    expect(fact.steps.find((step) => step.stage === 'teaching')?.state).toBe('done')
    expect(fact.steps.find((step) => step.stage === 'reviewing')?.state).toBe('unknown')
  })

  it('reports a reused plan for lesson tasks and a real planning stage for outlines', () => {
    expect(agentProgressFact(task({ stage: 'teaching' }), 'guided').planReused).toBe(true)
    const outline = agentProgressFact(
      task({ kind: 'course_outline', stage: 'planning' }),
      'guided',
    )
    expect(outline.planReused).toBe(false)
    expect(outline.steps[0].stage).toBe('planning')
  })

  it('recognizes a review that actually ran for a fast task', () => {
    const fact = agentProgressFact(task({ stage: 'reviewing' }), 'fast', { reviewRequested: false })
    expect(fact.collaborating).toBe(true)
    expect(fact.reviewRequested).toBe(true)
  })
})
