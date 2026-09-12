import { describe, expect, it } from 'vitest'
import { formatDifference, formatMetric } from './metrics'

describe('honest metric presentation', () => {
  it.each(['unknown', 'NA', 'incomplete', 'pending'])(
    'never renders %s as a zero score',
    (status) => {
      expect(formatMetric({ value: null, status, unit: 'ratio' })).toBe('—')
    },
  )
  it('also suppresses stale numeric values attached to unknown metrics', () => {
    expect(formatMetric({ value: 0.8, status: 'unknown', unit: 'ratio' })).toBe('—')
  })
  it('renders known zero separately from missing observations', () => {
    expect(formatMetric({ value: 0, status: 'ok', unit: 'ratio' })).toBe('0.0%')
  })
  it('reports ratio differences as percentage points', () => {
    expect(formatDifference({ value: 0.72, unit: 'ratio' }, { value: 0.765, unit: 'ratio' })).toBe(
      '+4.5 个百分点',
    )
  })
  it('does not invent a difference when the baseline has no observations', () => {
    expect(formatDifference({ value: null, status: 'NA' }, { value: 0.8, unit: 'ratio' })).toBe('—')
  })
})
