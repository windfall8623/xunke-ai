import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useIdentityKey } from '../../app/AuthProvider'
import { courseAccessDenied, courseKeys, coursesApi, createCourseSubmissionKeys } from '../../services/courses'
import { ApiError } from '../../services/http'
import type {
  CourseApplicationAnswer,
  CourseApplicationAttemptView,
  CourseApplicationTaskView,
  CourseAssessmentView,
  CourseHelpUsage,
} from '../../types/course'
import { isUnconfirmedCourseOperation, type CourseOperationState } from './courseActionState'
import { useCourseOperation } from './useCourseOperation'

const IDLE: CourseOperationState = { kind: 'idle' }
type ApplicationIntent = {
  operation: string
  semantic: string
  applicationTaskId: string
  key?: string
} & ({
  kind: 'answer'
  body: CourseApplicationAnswer
  beforeAttemptId: string | null
} | {
  kind: 'feedback'
  attemptId: string
  beforeTaskId: string | null
})

/** Saved answers and feedback jobs have separate receipts; recovery never silently requeues. */
export function useCourseApplications(
  courseId: string,
  assessmentId: string | null,
  onUnavailable?: () => void,
) {
  const identity = useIdentityKey()
  const client = useQueryClient()
  const operation = useCourseOperation()
  const intent = useRef<ApplicationIntent | null>(null)
  const [recovery, setRecovery] = useState<{ applicationTaskId: string; checked: boolean } | null>(null)
  const keyFor = useMemo(
    () => createCourseSubmissionKeys(identity, `application:${courseId}:${assessmentId || 'none'}`),
    [identity, courseId, assessmentId],
  )
  const inaccessible = courseAccessDenied(operation.error)
  useEffect(() => {
    if (!inaccessible) return
    intent.current = null
    setRecovery(null)
    onUnavailable?.()
  }, [inaccessible, onUnavailable])

  const remember = useCallback((attempt: CourseApplicationAttemptView) => {
    client.setQueryData(
      courseKeys.applicationAttempt(identity, courseId, attempt.course_assessment_id, attempt.attempt_id),
      attempt,
    )
    // This is the saved receipt's ID, not an inferred score, completion or revision.
    const attachReceipt = (current: CourseAssessmentView | undefined) => current && ({
      ...current,
      applications: (current.applications || []).map((task) =>
        task.application_task_id === attempt.application_task_id
          ? { ...task, latest_attempt_id: attempt.attempt_id } : task),
    })
    client.setQueryData<CourseAssessmentView>(
      courseKeys.assessment(identity, courseId, attempt.course_assessment_id), attachReceipt,
    )
    client.setQueryData<CourseAssessmentView[]>(
      courseKeys.assessments(identity, courseId),
      (current) => current?.map((item) => item.course_assessment_id === attempt.course_assessment_id
        ? attachReceipt(item)! : item),
    )
    void client.invalidateQueries({ queryKey: courseKeys.assessments(identity, courseId) })
    void client.invalidateQueries({ queryKey: courseKeys.outcomes(identity, courseId) })
    void client.invalidateQueries({
      queryKey: courseKeys.assessment(identity, courseId, attempt.course_assessment_id),
    })
  }, [client, identity, courseId])

  function assertReceipt(value: CourseApplicationAttemptView, pending: ApplicationIntent) {
    if (!value?.attempt_id || typeof value.answer !== 'string')
      throw new ApiError('回答保存结果尚未确认。', 0, 'INVALID_RESPONSE')
    if (value.course_id !== courseId || value.course_assessment_id !== assessmentId ||
      value.application_task_id !== pending.applicationTaskId ||
      (pending.kind === 'feedback' && value.attempt_id !== pending.attemptId))
      throw new ApiError('这条回答不属于当前应用任务。', 404, 'course_record_not_found')
    return value
  }
  async function readReceipt(pending: ApplicationIntent, signal: AbortSignal) {
    if (!assessmentId) return undefined
    if (pending.kind === 'feedback') {
      const receipt = assertReceipt(
        await coursesApi.applicationAttempt(courseId, assessmentId, pending.attemptId, signal), pending,
      )
      if (signal.aborted) throw new DOMException('已离开应用任务', 'AbortError')
      client.setQueryData(
        courseKeys.applicationAttempt(identity, courseId, assessmentId, receipt.attempt_id), receipt,
      )
      return receipt.feedback_task_id && receipt.feedback_task_id !== pending.beforeTaskId
        ? receipt : undefined
    }
    const current = await coursesApi.assessment(courseId, assessmentId, signal)
    if (current?.course_id !== courseId || current.course_assessment_id !== assessmentId)
      throw new ApiError('这次检查不属于当前课程。', 404, 'course_record_not_found')
    if (signal.aborted) throw new DOMException('已离开应用任务', 'AbortError')
    client.setQueryData(courseKeys.assessment(identity, courseId, assessmentId), current)
    const latestId = current.applications?.find((task) =>
      task.application_task_id === pending.applicationTaskId)?.latest_attempt_id
    if (!latestId || latestId === pending.beforeAttemptId) return undefined
    const receipt = assertReceipt(
      await coursesApi.applicationAttempt(courseId, assessmentId, latestId, signal), pending,
    )
    return receipt.answer.trim() === pending.body.answer.trim() &&
      receipt.help_usage === (pending.body.help_usage || 'unknown') ? receipt : undefined
  }
  function confirm(pending: ApplicationIntent, receipt: CourseApplicationAttemptView) {
    remember(receipt)
    keyFor.settle(pending.kind, pending.semantic)
    intent.current = null
    setRecovery(null)
  }
  function submitIntent(pending: ApplicationIntent) {
    return operation.run(pending.operation, async (signal) => {
      try {
        pending.key ??= await keyFor(pending.kind, pending.semantic)
        if (signal.aborted) throw new DOMException('已离开应用任务', 'AbortError')
        return assertReceipt(pending.kind === 'answer'
          ? await coursesApi.submitApplicationAnswer(courseId, assessmentId!, pending.applicationTaskId,
            pending.body, pending.key, signal)
          : await coursesApi.retryApplicationFeedback(courseId, assessmentId!, pending.attemptId,
            pending.key, signal), pending)
      } catch (cause) {
        if (signal.aborted) throw cause
        if (!isUnconfirmedCourseOperation(cause)) {
          intent.current = null
          setRecovery(null)
          throw cause
        }
        setRecovery({ applicationTaskId: pending.applicationTaskId, checked: false })
        try {
          const receipt = await readReceipt(pending, signal)
          if (receipt) return receipt
        } catch (readError) {
          if (courseAccessDenied(readError) || signal.aborted) throw readError
        }
        throw cause
      }
    }, (receipt) => confirm(pending, receipt))
  }
  async function submit(task: CourseApplicationTaskView, answer: string, helpUsage: CourseHelpUsage) {
    if (!assessmentId || intent.current || operation.pending !== null || inaccessible) return undefined
    const body = { expected_revision: task.revision, answer, help_usage: helpUsage }
    const pending: ApplicationIntent = {
      kind: 'answer', operation: `answer:${task.application_task_id}`,
      applicationTaskId: task.application_task_id, beforeAttemptId: task.latest_attempt_id || null,
      body, semantic: JSON.stringify({ task: task.application_task_id, ...body }),
    }
    intent.current = pending
    return submitIntent(pending)
  }
  function retryFeedback(attempt: CourseApplicationAttemptView) {
    if (!assessmentId || intent.current || operation.pending !== null || inaccessible) return
    const pending: ApplicationIntent = {
      kind: 'feedback', operation: `feedback:${attempt.attempt_id}`,
      applicationTaskId: attempt.application_task_id, attemptId: attempt.attempt_id,
      beforeTaskId: attempt.feedback_task_id || null,
      semantic: JSON.stringify({ attempt: attempt.attempt_id, retry_of: attempt.feedback_task_id || null }),
    }
    intent.current = pending
    void submitIntent(pending)
  }
  async function recover(applicationTaskId: string, retryOriginal = false) {
    const pending = intent.current
    if (!pending || pending.applicationTaskId !== applicationTaskId ||
      operation.pending !== null || inaccessible) return
    if (retryOriginal) return submitIntent(pending)
    return operation.run(pending.operation, async (signal) => {
      const receipt = await readReceipt(pending, signal)
      if (!receipt) {
        setRecovery({ applicationTaskId, checked: true })
        throw new ApiError('尚未核对到这次提交的记录。', 0, 'OPERATION_UNCONFIRMED')
      }
      return receipt
    }, (receipt) => confirm(pending, receipt))
  }
  const stateFor = useCallback(
    (applicationTaskId: string, attemptId?: string | null): CourseOperationState => {
      if (operation.state.kind === 'idle') return IDLE
      const owned = [`answer:${applicationTaskId}`, attemptId ? `feedback:${attemptId}` : '']
      return owned.includes(operation.state.operation) ? operation.state : IDLE
    }, [operation.state],
  )
  return {
    operation, submit, retryFeedback, stateFor, recover, recovery, inaccessible,
    locked: operation.pending !== null || !!recovery,
  }
}

export type CourseApplicationController = ReturnType<typeof useCourseApplications>
