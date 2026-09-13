import { request } from './http'

export type ExperienceEventName =
  | 'course_create_viewed' | 'course_create_submitted' | 'lesson_opened'
  | 'learning_session_finished' | 'task_retry_clicked'
  | 'response_helpfulness_submitted' | 'content_first_visible' | 'content_stream_interrupted'

export type ExperienceEventInput = {
  event_id: string
  name: ExperienceEventName
  course_id?: string
  lesson_id?: string
  task_id?: string
  elapsed_ms?: number
  helpful?: boolean
}

const recent = new Set<string>()
const submittedAt = new Map<string, number>()

/** Track a user submission, never a GET, remount, or background replay. */
export async function trackContentSubmission<T extends { task_id?: string }>(send: () => Promise<T>): Promise<T> {
  const start = performance.now()
  const result = await send()
  if (result.task_id && !submittedAt.has(result.task_id)) {
    submittedAt.set(result.task_id, start)
    if (submittedAt.size > 256) submittedAt.delete(submittedAt.keys().next().value!)
  }
  return result
}

export function takeContentSubmittedAt(taskId: string): number | undefined {
  const start = submittedAt.get(taskId)
  submittedAt.delete(taskId)
  return start
}

/** Best effort: diagnostics must never alter answers, progress or session UI. */
export async function recordExperienceEvent(event: ExperienceEventInput): Promise<void> {
  if (recent.has(event.event_id)) return
  recent.add(event.event_id)
  if (recent.size > 256) recent.delete(recent.values().next().value!)
  // Explicit projection prevents callers from accidentally transmitting answer text.
  const { event_id, name, course_id, lesson_id, task_id, elapsed_ms, helpful } = event
  try {
    await request('/experience/events', {
      method: 'POST', timeoutMs: 3000, silentAuthFailure: true,
      data: { event_id, name, course_id, lesson_id, task_id, elapsed_ms, helpful },
    })
  } catch {
    // No retry loop, error toast or blocking UI for diagnostic collection.
  }
}
