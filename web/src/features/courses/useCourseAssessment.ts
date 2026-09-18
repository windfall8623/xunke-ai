import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useIdentityKey } from '../../app/AuthProvider'
import {
  courseAccessDenied,
  courseKeys,
  coursesApi,
  courseTaskPending,
  createCourseSubmissionKeys,
} from '../../services/courses'
import { ApiError } from '../../services/http'
import type { CourseAssessmentView, CourseHelpUsage, CourseView } from '../../types/course'
import { isUnconfirmedCourseOperation } from './courseActionState'
import { useCourseOperation } from './useCourseOperation'

const POLL_MS = 3000
type AssessmentCommand = {
  name: string
  semantic: string
  key?: string
  request: (key: string, signal: AbortSignal) => Promise<CourseAssessmentView>
}
function assessmentBusy(assessment?: CourseAssessmentView | null) {
  return !!assessment && (
    assessment.status === 'generating' || courseTaskPending(assessment.task) ||
    courseTaskPending(assessment.application_generation_task)
  )
}

/** GET only restores published facts; every new generation is an explicit command. */
export function useCourseAssessment(
  course: CourseView,
  enabled: boolean,
  onUnavailable?: () => void,
) {
  const identity = useIdentityKey()
  const client = useQueryClient()
  const courseId = course.course_id
  const operation = useCourseOperation()
  const intent = useRef<AssessmentCommand | null>(null)
  const [recovery, setRecovery] = useState(false)
  const [recoveryChecked, setRecoveryChecked] = useState(false)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const keyFor = useMemo(
    () => createCourseSubmissionKeys(identity, `assessment:${courseId}`), [identity, courseId],
  )
  function assertCurrent(value: CourseAssessmentView) {
    if (!value?.course_assessment_id)
      throw new ApiError('检查结果尚未确认。', 0, 'INVALID_RESPONSE')
    if (value.course_id !== courseId)
      throw new ApiError('这次检查不属于当前课程。', 404, 'course_record_not_found')
    return value
  }
  const outcomesQuery = useQuery({
    queryKey: courseKeys.outcomes(identity, courseId),
    queryFn: async ({ signal }) => {
      const value = await coursesApi.outcomes(courseId, signal)
      if (value?.course_id !== courseId)
        throw new ApiError('这些目标不属于当前课程。', 404, 'course_record_not_found')
      return value
    },
    enabled, staleTime: 0, gcTime: 0, retry: false, refetchOnMount: 'always',
  })
  const listQuery = useQuery({
    queryKey: courseKeys.assessments(identity, courseId),
    queryFn: async ({ signal }) => (await coursesApi.assessments(courseId, signal)).map(assertCurrent),
    enabled, staleTime: 0, gcTime: 0, retry: false, refetchOnMount: 'always',
    refetchInterval: (state) => state.state.data?.some(assessmentBusy) ? POLL_MS : false,
    refetchIntervalInBackground: false,
  })
  const list = listQuery.data || []
  const current = selectedId
    ? list.find((item) => item.course_assessment_id === selectedId) || null
    : list.find((item) => !['completed', 'failed', 'cancelled'].includes(item.status)) || list[0] || null
  const detailQuery = useQuery({
    queryKey: courseKeys.assessment(identity, courseId, current?.course_assessment_id || ''),
    queryFn: async ({ signal }) => {
      const value = assertCurrent(await coursesApi.assessment(courseId, current!.course_assessment_id, signal))
      if (value.course_assessment_id !== current!.course_assessment_id)
        throw new ApiError('这条记录不属于当前检查。', 404, 'course_record_not_found')
      return value
    },
    enabled: enabled && !!current,
    staleTime: 0, gcTime: 0, retry: false, refetchOnMount: 'always',
    refetchInterval: (state) => assessmentBusy(state.state.data) ? POLL_MS : false,
    refetchIntervalInBackground: false,
  })
  const inaccessible = [outcomesQuery.error, listQuery.error, detailQuery.error, operation.error]
    .some(courseAccessDenied)
  useEffect(() => {
    if (!inaccessible) return
    intent.current = null
    setRecovery(false)
    setRecoveryChecked(false)
    onUnavailable?.()
  }, [inaccessible, onUnavailable])
  const assessment = inaccessible ? null
    : detailQuery.data?.course_assessment_id === current?.course_assessment_id ? detailQuery.data : current
  const refresh = useCallback(() => {
    void client.invalidateQueries({ queryKey: courseKeys.assessments(identity, courseId) })
    void client.invalidateQueries({ queryKey: courseKeys.outcomes(identity, courseId) })
    if (current)
      void client.invalidateQueries({
        queryKey: courseKeys.assessment(identity, courseId, current.course_assessment_id),
      })
  }, [client, identity, courseId, current])
  const remember = useCallback((saved: CourseAssessmentView) => {
    client.setQueryData(courseKeys.assessment(identity, courseId, saved.course_assessment_id), saved)
    client.setQueryData<CourseAssessmentView[]>(courseKeys.assessments(identity, courseId),
      (items) => [saved, ...(items || []).filter((item) => item.course_assessment_id !== saved.course_assessment_id)])
    setSelectedId(saved.course_assessment_id)
    refresh()
  }, [client, identity, courseId, refresh])
  function runCommand(command: AssessmentCommand) {
    return operation.run(command.name, async (signal) => {
      try {
        command.key ??= await keyFor(command.name, command.semantic)
        if (signal.aborted) throw new DOMException('已离开检查', 'AbortError')
        return assertCurrent(await command.request(command.key, signal))
      } catch (cause) {
        if (signal.aborted) throw cause
        if (isUnconfirmedCourseOperation(cause)) {
          setRecovery(true)
          setRecoveryChecked(false)
        } else {
          intent.current = null
          setRecovery(false)
          setRecoveryChecked(false)
        }
        throw cause
      }
    }, (saved) => {
      remember(saved)
      keyFor.settle(command.name, command.semantic)
      intent.current = null
      setRecovery(false)
      setRecoveryChecked(false)
    })
  }
  function dispatch(command: AssessmentCommand) {
    if (intent.current || operation.pending !== null || inaccessible) return Promise.resolve(undefined)
    intent.current = command
    return runCommand(command)
  }
  function start(criterionIds: string[]) {
    if (listQuery.isPending || listQuery.error || detailQuery.error) return Promise.resolve(undefined)
    const body = {
      expected_course_revision: course.revision,
      expected_criteria_revision: course.criteria_revision,
      course_criterion_ids: [...criterionIds].sort(),
    }
    return dispatch({
      name: 'assessment',
      semantic: JSON.stringify({ ...body, after_assessment_id: list[0]?.course_assessment_id || null }),
      request: (key, signal) => coursesApi.createAssessment(courseId, body, key, signal),
    })
  }
  function complete(helpUsage: CourseHelpUsage) {
    if (!assessment) return Promise.resolve(undefined)
    const id = assessment.course_assessment_id
    const body = { expected_revision: assessment.revision, help_usage: helpUsage }
    return dispatch({
      name: 'complete-assessment', semantic: JSON.stringify({ id, ...body }),
      request: (key, signal) => coursesApi.completeAssessment(courseId, id, body, key, signal),
    })
  }
  function createApplications() {
    if (!assessment) return Promise.resolve(undefined)
    const id = assessment.course_assessment_id
    return dispatch({
      name: 'applications',
      semantic: JSON.stringify({ id, criteria_revision: assessment.criteria_revision,
        retry_of: assessment.application_generation_task_id || null }),
      request: (key, signal) => coursesApi.createApplications(courseId, id, key, signal),
    })
  }
  async function recover() {
    if (!intent.current || operation.pending !== null || inaccessible) return
    // A list may contain another tab's new check. Do not infer this command's
    // receipt from timing; explicit replay below retains its exact key and body.
    await Promise.all([
      listQuery.refetch({ cancelRefetch: false }),
      current ? detailQuery.refetch({ cancelRefetch: false }) : Promise.resolve(),
    ])
    if (intent.current) setRecoveryChecked(true)
  }
  function retryOriginal() {
    if (!intent.current || operation.pending !== null || inaccessible || !recoveryChecked) return
    void runCommand(intent.current)
  }
  return {
    outcomes: inaccessible || outcomesQuery.error ? undefined : outcomesQuery.data,
    outcomesQuery, listQuery, detailQuery, assessment, history: inaccessible ? [] : list,
    busy: assessmentBusy(assessment), operation, inaccessible, recovery, recoveryChecked,
    select: setSelectedId, start, complete, createApplications, refresh, recover, retryOriginal,
  }
}

export type CourseAssessmentController = ReturnType<typeof useCourseAssessment>
