import { ApiError } from '../../services/http'
import type {
  CourseSelfCheckCreate,
  CourseSelfCheckView,
  CourseTutorTurnView,
} from '../../types/course'

export type CourseOperationState =
  | { kind: 'idle' }
  | { kind: 'submitting'; operation: string }
  | { kind: 'unconfirmed'; operation: string }
  | { kind: 'confirmed'; operation: string }
  | { kind: 'failed'; operation: string }

export type TeachingFeedbackState =
  | 'not_requested'
  | 'preparing'
  | 'syncing'
  | 'ready'
  | 'failed'
  | 'cancelled'

/** A lost response cannot establish whether a write reached the server. */
export function isUnconfirmedCourseOperation(error: unknown) {
  return !(error instanceof ApiError) || error.status === 0 || error.status >= 500 ||
    error.code === 'INVALID_RESPONSE'
}

export function teachingFeedbackState(turn?: CourseTutorTurnView | null): TeachingFeedbackState {
  if (!turn) return 'not_requested'
  if (turn.task.status === 'pending' || turn.task.status === 'running') return 'preparing'
  if (turn.task.status === 'completed') return turn.answer?.trim() ? 'ready' : 'syncing'
  return turn.task.status === 'cancelled' ? 'cancelled' : 'failed'
}

export function feedbackForAttempt(
  attempt: CourseSelfCheckView,
  turn?: CourseTutorTurnView | null,
) {
  return turn?.check_attempt_id === attempt.attempt_id ? turn : null
}

export function checkAnswerKey(answer: CourseSelfCheckCreate['answer']) {
  return JSON.stringify(Array.isArray(answer) ? [...answer].sort() : answer.trim())
}

/** An older identical answer is history, not a receipt for this submission. */
export function newlySavedCheck(
  attempts: CourseSelfCheckView[],
  body: CourseSelfCheckCreate,
  beforeIds: ReadonlySet<string>,
) {
  const latest = attempts
    .filter((attempt) => attempt.check_ref === body.check_ref &&
      attempt.content_version === body.expected_content_version)
    .sort((a, b) => a.saved_at.localeCompare(b.saved_at) || a.attempt_id.localeCompare(b.attempt_id))
    .at(-1)
  return latest && !beforeIds.has(latest.attempt_id) &&
    checkAnswerKey(latest.answer) === checkAnswerKey(body.answer) ? latest : undefined
}
