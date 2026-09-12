import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useRef } from 'react'
import { useIdentityKey } from '../../app/AuthProvider'
import {
  askTutor,
  courseTutorKeys,
  listCheckAttempts,
  listTutorTurns,
  retryTutorTurn,
  saveCheckAttempt,
} from '../../services/courseTutor'
import {
  courseKeys,
  coursesApi,
  courseSourceRevoked,
  courseTaskPending,
  createCourseSubmissionKeys,
} from '../../services/courses'
import { ApiError } from '../../services/http'
import type {
  CourseLessonView,
  CourseSelfCheckCreate,
  CourseSelfCheckView,
  CourseTutorCreate,
  CourseTutorTurnView,
} from '../../types/course'
import type { TaskEvent, TaskStreamState } from '../../types/taskEvent'
import { useSettleWatch, useTaskEvents, type SettleWatch } from '../tasks/useTaskEvents'
import { useCourseOperation } from './useCourseOperation'

export function useLessonTutor(lesson: CourseLessonView, onUnavailable: () => void) {
  const identity = useIdentityKey()
  const client = useQueryClient()
  const operation = useCourseOperation()
  const { course_id: courseId, lesson_id: lessonId, content_version: version } = lesson
  const keyFor = useMemo(
    () => createCourseSubmissionKeys(identity, `tutor:${courseId}:${lessonId}:${version}`),
    [identity, courseId, lessonId, version],
  )
  const turnsKey = courseTutorKeys.turns(identity, courseId, lessonId, version)
  const checksKey = courseTutorKeys.checks(identity, courseId, lessonId, version)
  const streamStateRef = useRef<TaskStreamState>('closed')
  const settleStateRef = useRef<SettleWatch>({ taskId: null, active: false, expired: false })
  const lastActiveTaskId = useRef('')
  function assertCurrent<
    T extends { course_id: string; lesson_id: string; content_version: number },
  >(value: T): T {
    if (
      value.course_id !== courseId ||
      value.lesson_id !== lessonId ||
      value.content_version !== version
    )
      throw new ApiError('这条记录不属于当前课文版本。', 404, 'course_record_not_found')
    return value
  }
  const query = useQuery({
    queryKey: turnsKey,
    queryFn: async ({ signal }) =>
      (await listTutorTurns(courseId, lessonId, version, signal)).map(assertCurrent),
    enabled: lesson.status === 'ready',
    staleTime: 0,
    gcTime: 0,
    retry: false,
    refetchOnMount: 'always',
    refetchInterval: (state) => {
      const settle = settleStateRef.current
      if (settle.active && !settle.expired) return 2000
      if (!state.state.data?.some((turn) => courseTaskPending(turn.task))) return false
      // SSE 流存活时降为保险刷新，connecting/closed/polling 态保持原频率。
      return streamStateRef.current === 'streaming' ? 30_000 : 2500
    },
    refetchIntervalInBackground: false,
  })
  const checksQuery = useQuery({
    queryKey: checksKey,
    queryFn: async ({ signal }) =>
      (await listCheckAttempts(courseId, lessonId, version, signal)).map(assertCurrent),
    enabled: lesson.status === 'ready' && !!lesson.checks?.length,
    staleTime: 0,
    gcTime: 0,
    retry: false,
    refetchOnMount: 'always',
  })
  const errors = [query.error, checksQuery.error, operation.error]
  const inaccessible = errors.some(
    (error) =>
      courseSourceRevoked(error) ||
      (error instanceof ApiError && [401, 404].includes(error.status)),
  )
  const turns = inaccessible || query.error ? [] : query.data || []
  const attempts = inaccessible || checksQuery.error ? [] : checksQuery.data || []
  const activeTurn = turns.find((turn) => courseTaskPending(turn.task))
  const busy = operation.pending !== null || !!activeTurn
  useEffect(() => {
    if (activeTurn) lastActiveTaskId.current = activeTurn.task.task_id
  }, [activeTurn])
  // 刚结束的助教任务也要继续观察调和收尾；activeTurn 消失后按最后活动任务回溯。
  const watchedTask =
    activeTurn?.task ??
    turns.find(
      (turn) => turn.task.task_id === (settleStateRef.current.taskId || lastActiveTaskId.current),
    )?.task
  const settle = useSettleWatch(watchedTask, () => {
    void client.invalidateQueries({ queryKey: turnsKey })
    void client.invalidateQueries({ queryKey: checksKey })
  })
  settleStateRef.current = settle
  const streamTaskId = activeTurn?.task.task_id ?? settle.taskId ?? undefined
  const handleTaskEvent = (event: TaskEvent) => {
    if (!streamTaskId || event.type === 'reset' || event.type === 'source_revoked') return
    const { payload } = event
    client.setQueryData<CourseTutorTurnView[]>(turnsKey, (current) =>
      (current || []).map((turn) =>
        turn.task.task_id === streamTaskId
          ? {
              ...turn,
              task: {
                ...turn.task,
                status: payload.status as CourseTutorTurnView['task']['status'],
                stage: payload.stage || payload.status,
                error_code: payload.error_code ?? turn.task.error_code,
                business_settled: payload.business_settled,
              },
            }
          : turn,
      ),
    )
    // 助教不能只刷任务本身：终态后同时刷新 turns 与自测记录。
    if (['completed', 'failed', 'cancelled'].includes(event.type)) {
      void client.invalidateQueries({ queryKey: turnsKey })
      void client.invalidateQueries({ queryKey: checksKey })
    }
  }
  const streamState = useTaskEvents({
    path: streamTaskId ? `/courses/tasks/${streamTaskId}/events` : undefined,
    taskId: streamTaskId,
    enabled: !inaccessible && lesson.status === 'ready' && (!!activeTurn || settle.active),
    onEvent: handleTaskEvent,
    onResume: () => {
      void client.invalidateQueries({ queryKey: turnsKey })
      void client.invalidateQueries({ queryKey: checksKey })
    },
  })
  streamStateRef.current = streamState
  useEffect(() => {
    if ([query.error, checksQuery.error, operation.error].some(courseSourceRevoked)) onUnavailable()
    if (
      [query.error, checksQuery.error, operation.error].some(
        (error) => error instanceof ApiError && error.status === 409,
      )
    ) {
      void client.invalidateQueries({ queryKey: courseKeys.lesson(identity, courseId, lessonId) })
      void client.invalidateQueries({ queryKey: courseKeys.course(identity, courseId) })
      void client.invalidateQueries({ queryKey: turnsKey })
      void client.invalidateQueries({ queryKey: checksKey })
    }
  }, [
    query.error,
    checksQuery.error,
    operation.error,
    onUnavailable,
    client,
    identity,
    courseId,
    lessonId,
    version,
  ])
  function rememberTurn(turn: CourseTutorTurnView) {
    assertCurrent(turn)
    client.setQueryData<CourseTutorTurnView[]>(turnsKey, (current) =>
      [...(current || []).filter((item) => item.turn_id !== turn.turn_id), turn].sort(
        (a, b) => a.created_at.localeCompare(b.created_at) || a.turn_id.localeCompare(b.turn_id),
      ),
    )
    void client.invalidateQueries({ queryKey: checksKey })
  }
  async function ask(body: CourseTutorCreate) {
    if (busy || query.isPending || query.error || inaccessible || lesson.status !== 'ready') return
    const semantic = JSON.stringify(body)
    return operation.run(
      'ask',
      async (signal) => {
        const key = await keyFor('ask', semantic)
        if (signal.aborted) throw new DOMException('已离开课时', 'AbortError')
        return askTutor(courseId, lessonId, body, key, signal)
      },
      (turn) => {
        rememberTurn(turn)
        keyFor.settle('ask', semantic)
      },
    )
  }
  async function retry(turn: CourseTutorTurnView) {
    if (busy || inaccessible || !['failed', 'cancelled'].includes(turn.task.status)) return
    const semantic = JSON.stringify({ turn_id: turn.turn_id, task_id: turn.task.task_id })
    return operation.run(
      'retry',
      async (signal) => {
        const key = await keyFor('retry', semantic)
        if (signal.aborted) throw new DOMException('已离开课时', 'AbortError')
        return retryTutorTurn(courseId, lessonId, turn.turn_id, key, signal)
      },
      (saved) => {
        rememberTurn(saved)
        keyFor.settle('retry', semantic)
      },
    )
  }
  function cancel(turn: CourseTutorTurnView) {
    if (operation.pending !== null || inaccessible || !courseTaskPending(turn.task)) return
    void operation.run(
      'cancel',
      (signal) => coursesApi.cancelTask(turn.task.task_id, signal),
      (task) => {
        if (task.course_id !== courseId || task.lesson_id !== lessonId) return
        rememberTurn({ ...turn, task, answer: null })
        void query.refetch()
      },
    )
  }
  async function save(checkRef: string, answer: CourseSelfCheckCreate['answer']) {
    if (operation.pending !== null || checksQuery.isPending || checksQuery.error || inaccessible)
      return
    const body: CourseSelfCheckCreate = {
      expected_content_version: version,
      check_ref: checkRef,
      answer,
    }
    const semantic = JSON.stringify(body)
    return operation.run(
      `check:${checkRef}`,
      async (signal) => {
        const key = await keyFor('save-check', semantic)
        if (signal.aborted) throw new DOMException('已离开课时', 'AbortError')
        return saveCheckAttempt(courseId, lessonId, body, key, signal)
      },
      (saved) => {
        assertCurrent(saved)
        client.setQueryData<CourseSelfCheckView[]>(checksKey, (current) => [
          ...(current || []).filter((item) => item.attempt_id !== saved.attempt_id),
          saved,
        ])
        keyFor.settle('save-check', semantic)
      },
    )
  }
  return {
    query,
    checksQuery,
    turns,
    attempts,
    activeTurn,
    busy,
    inaccessible,
    pending: operation.pending,
    error: operation.error,
    settling: settle.active,
    ask,
    retry,
    cancel,
    save,
  }
}

export type LessonTutorController = ReturnType<typeof useLessonTutor>
