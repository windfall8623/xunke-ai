import { describe, expect, it } from 'vitest'
import { applyContentFrame, parseContentFrame } from './contentEvents'
import { emptyContentPreview, type ContentFrame } from '../types/contentEvent'

const frame = (overrides: Partial<ContentFrame> = {}): ContentFrame => ({
  schema_version: 'xunke-content.v1', task_id: 'task_1', execution_id: 'task_1.a1',
  generation_revision: 1, seq: 1, type: 'delta', payload: { text: 'first' }, ...overrides,
})

describe('private content revisions', () => {
  it('clears a repaired draft and ignores a replayed fragment', () => {
    const first = applyContentFrame(emptyContentPreview, frame())
    expect(applyContentFrame(first, frame()).text).toBe('first')
    const reset = applyContentFrame(first, frame({ type: 'reset', generation_revision: 2, payload: {} }))
    expect(reset.text).toBe('')
    const next = applyContentFrame(reset, frame({ generation_revision: 2, seq: 2, payload: { text: 'repaired' } }))
    expect(next.text).toBe('repaired')
    expect(applyContentFrame(next, frame()).text).toBe('repaired')
    expect(applyContentFrame(next, frame({ generation_revision: 2, seq: 2, type: 'finalized', payload: {} })).status).toBe('finalized')
  })
  it('rejects a different task and hides revoked content', () => {
    expect(parseContentFrame(frame(), 'task_other')).toBeNull()
    expect(parseContentFrame({ ...frame(), payload: { text: {} } }, 'task_1')).toBeNull()
    const state = applyContentFrame(emptyContentPreview, frame())
    expect(applyContentFrame(state, frame({ type: 'revoked', payload: {} })).text).toBe('')
  })
})
