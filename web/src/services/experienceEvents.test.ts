import { describe, expect, it, vi } from 'vitest'
import { recordExperienceEvent } from './experienceEvents'

describe('experience diagnostics', () => {
  it('drops failures and duplicate events without exposing arbitrary fields', async () => {
    const fetcher = vi.fn().mockRejectedValue(new Error('offline'))
    vi.stubGlobal('fetch', fetcher)
    const event = { event_id: 'diagnostic-1', name: 'lesson_opened' as const, answer: 'private' }
    await expect(recordExperienceEvent(event)).resolves.toBeUndefined()
    await recordExperienceEvent(event)
    expect(fetcher).toHaveBeenCalledTimes(1)
    expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual({ event_id: 'diagnostic-1', name: 'lesson_opened' })
    vi.unstubAllGlobals()
  })
})
