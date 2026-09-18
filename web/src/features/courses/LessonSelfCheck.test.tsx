import { describe, expect, it } from 'vitest'
import { selfCheckRoundState, type RecallRound } from './courseActionState'

const round = (overrides: Partial<RecallRound> = {}): RecallRound => ({
  intentId: 'recall-1',
  baselineAttemptId: null,
  baselineSeen: false,
  savedAttemptId: null,
  revealed: false,
  ...overrides,
})

describe('self check recall round (B02)', () => {
  it('requires a newly persisted attempt before showing previous answers', () => {
    expect(selfCheckRoundState(round(), { attempt_id: 'old', answer: '旧' }, '').canReveal).toBe(false)
    expect(
      selfCheckRoundState(round({ baselineSeen: true, baselineAttemptId: 'old' }),
        { attempt_id: 'old', answer: '旧' }, '').canReveal,
    ).toBe(false)
    expect(
      selfCheckRoundState(round({ baselineSeen: true, baselineAttemptId: 'old' }),
        { attempt_id: 'new', answer: '本次' }, '本次').canReveal,
    ).toBe(true)
  })

  it('treats a recovered receipt outside the frozen baseline as this round saved', () => {
    // 恢复路径：第一次保存网络失败，回执稍后读回——本轮视为已保存。
    const state = selfCheckRoundState(
      round({ baselineSeen: true, baselineAttemptId: 'old' }),
      { attempt_id: 'new', answer: '本次' }, '本次',
    )
    expect(state.roundSaved).toBe(true)
    expect(state.savedAttemptId).toBe('new')
  })

  it('marks the draft unsaved after editing a saved round', () => {
    const state = selfCheckRoundState(
      round({ baselineSeen: true, baselineAttemptId: 'old', savedAttemptId: 'new' }),
      { attempt_id: 'new', answer: '已保存内容' }, '改过的草稿',
    )
    expect(state.roundSaved).toBe(true)
    expect(state.draftDiffers).toBe(true)
  })

  it('does not mark the entry baseline itself as a new save', () => {
    const state = selfCheckRoundState(
      round({ baselineSeen: true, baselineAttemptId: 'old' }),
      { attempt_id: 'old', answer: '旧回答' }, '旧回答',
    )
    expect(state.roundSaved).toBe(false)
    expect(state.savedAttemptId).toBeNull()
  })
})
