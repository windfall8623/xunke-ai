import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'
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
import { recordExperienceEvent } from '../../services/experienceEvents'
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
import {
  isUnconfirmedCourseOperation,
  newlySavedCheck,
  teachingFeedbackState,
} from './courseActionState'

type CheckIntent = {
  body: CourseSelfCheckCreate
  semantic: string
  beforeIds: Set<string>
  key?: string
}
type TutorIntent = {
  kind: 'ask' | 'retry'
  body: CourseTutorCreate
  semantic: string
  beforeIds: Set<string>
  previous?: CourseTutorTurnView
  key?: string
}
const inaccessibleError = (error: unknown) => courseSourceRevoked(error) ||
  (error instanceof ApiError && [401, 404].includes(error.status))
const notConfirmed = () => new ApiError('尚未核对到这次提交的记录。', 0, 'OPERATION_UNCONFIRMED')

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
  const checkIntent = useRef<CheckIntent | null>(null)
  const tutorIntent = useRef<TutorIntent | null>(null)
  const [saveRecovery, setSaveRecovery] = useState<{ checkRef: string; checked: boolean } | null>(null)
  const [requestRecovery, setRequestRecovery] = useState<{ checked: boolean } | null>(null)
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
  const inaccessible = errors.some(inaccessibleError)
  const turns = inaccessible ? [] : query.data || []
  const attempts = inaccessible || checksQuery.error ? [] : checksQuery.data || []
  const activeTurn = turns.find((turn) => courseTaskPending(turn.task))
  const syncing = turns.some((turn) => teachingFeedbackState(turn) === 'syncing')
  const busy = operation.pending !== null || !!activeTurn || syncing || !!saveRecovery || !!requestRecovery
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
    if (event.type === 'source_revoked') {
      onUnavailable()
      return
    }
    if (!streamTaskId || event.type === 'reset') return
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
  const syncingTasks = turns.filter((turn) => teachingFeedbackState(turn) === 'syncing')
    .map((turn) => turn.task.task_id).sort().join(',')
  // A successful task may become visible before its business answer. Only GETs run here:
  // one immediate read and at most three additional reads, then manual refresh remains.
  useEffect(() => {
    if (!syncingTasks || inaccessible) return
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | undefined
    const read = async (remaining: number) => {
      const [result] = await Promise.all([
        query.refetch({ cancelRefetch: false }),
        lesson.checks?.length ? checksQuery.refetch({ cancelRefetch: false }) : Promise.resolve(),
      ])
      if (cancelled || inaccessibleError(result.error)) return
      const waiting = (result.data || []).some((turn) =>
        syncingTasks.split(',').includes(turn.task.task_id) && teachingFeedbackState(turn) === 'syncing')
      if (remaining > 0 && (waiting || result.error))
        timer = setTimeout(() => { void read(remaining - 1) }, 1000)
    }
    void read(3)
    return () => { cancelled = true; if (timer) clearTimeout(timer) }
  }, [syncingTasks, inaccessible, query.refetch, checksQuery.refetch, lesson.checks?.length])
  const terminalTasks = turns.filter((turn) => !courseTaskPending(turn.task))
    .map((turn) => `${turn.task.task_id}:${turn.task.status}:${turn.task.business_settled === true}`)
    .sort().join(',')
  useEffect(() => {
    if (!terminalTasks || inaccessible) return
    void client.invalidateQueries({ queryKey: courseKeys.course(identity, courseId) })
    void client.invalidateQueries({ queryKey: courseKeys.lesson(identity, courseId, lessonId) })
    void client.invalidateQueries({ queryKey: courseKeys.progress(identity, courseId) })
    void client.invalidateQueries({ queryKey: courseKeys.lists(identity) })
    void client.invalidateQueries({ queryKey: courseKeys.todayAll(identity) })
  }, [terminalTasks, inaccessible, client, identity, courseId, lessonId])
  useEffect(() => {
    if ([query.error, checksQuery.error, operation.error].some(inaccessibleError)) {
      checkIntent.current = null
      tutorIntent.current = null
      setSaveRecovery(null)
      setRequestRecovery(null)
      onUnavailable()
    }
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
  async function refreshFeedback() {
    await Promise.all([
      query.refetch({ cancelRefetch: false }),
      lesson.checks?.length ? checksQuery.refetch({ cancelRefetch: false }) : Promise.resolve(),
    ])
  }
  async function readTutorReceipt(intent: TutorIntent, signal: AbortSignal) {
    const saved = (await listTutorTurns(courseId, lessonId, version, signal)).map(assertCurrent)
    if (signal.aborted) throw new DOMException('已离开课时', 'AbortError')
    client.setQueryData(turnsKey, saved)
    if (intent.kind === 'retry') return saved.find((turn) =>
      turn.turn_id === intent.previous?.turn_id && turn.task.task_id !== intent.previous.task.task_id)
    return saved.find((turn) => !intent.beforeIds.has(turn.turn_id) &&
      turn.mode === intent.body.mode && (turn.block_index ?? null) === (intent.body.block_index ?? null) &&
      (turn.check_attempt_id ?? null) === (intent.body.check_attempt_id ?? null) &&
      turn.question.trim() === (intent.body.question || '').trim())
  }
  function confirmTutorReceipt(intent: TutorIntent, turn: CourseTutorTurnView) {
    rememberTurn(turn)
    keyFor.settle(intent.kind, intent.semantic)
    tutorIntent.current = null
    setRequestRecovery(null)
  }
  async function submitTutorIntent(intent: TutorIntent) {
    return operation.run(intent.kind, async (signal) => {
      try {
        intent.key ??= await keyFor(intent.kind, intent.semantic)
        if (signal.aborted) throw new DOMException('已离开课时', 'AbortError')
        return assertCurrent(intent.kind === 'retry'
          ? await retryTutorTurn(courseId, lessonId, intent.previous!.turn_id, intent.key, signal)
          : await askTutor(courseId, lessonId, intent.body, intent.key, signal))
      } catch (cause) {
        if (signal.aborted) throw cause
        if (!isUnconfirmedCourseOperation(cause)) {
          tutorIntent.current = null
          setRequestRecovery(null)
          throw cause
        }
        setRequestRecovery({ checked: false })
        try {
          const receipt = await readTutorReceipt(intent, signal)
          if (receipt) return receipt
        } catch (readError) {
          if (inaccessibleError(readError) || signal.aborted) throw readError
        }
        throw cause
      }
    }, (turn) => confirmTutorReceipt(intent, turn))
  }
  async function recoverTutorRequest(retryOriginal = false) {
    const intent = tutorIntent.current
    if (!intent || operation.pending !== null || inaccessible) return
    if (retryOriginal) return submitTutorIntent(intent)
    return operation.run(intent.kind, async (signal) => {
      const receipt = await readTutorReceipt(intent, signal)
      if (!receipt) { setRequestRecovery({ checked: true }); throw notConfirmed() }
      return receipt
    }, (turn) => confirmTutorReceipt(intent, turn))
  }
  async function ask(body: CourseTutorCreate) {
    if (busy || query.isPending || query.error || inaccessible || lesson.status !== 'ready') return
    const intent: TutorIntent = { kind: 'ask', body: { ...body }, semantic: JSON.stringify(body),
      beforeIds: new Set(turns.map((turn) => turn.turn_id)) }
    tutorIntent.current = intent
    return submitTutorIntent(intent)
  }
  async function retry(turn: CourseTutorTurnView) {
    if (busy || inaccessible || !['failed', 'cancelled'].includes(turn.task.status)) return
    void recordExperienceEvent({ event_id: crypto.randomUUID(), name: 'task_retry_clicked',
      course_id: courseId, lesson_id: lessonId, task_id: turn.task.task_id })
    const intent: TutorIntent = { kind: 'retry', body: { expected_content_version: version,
      mode: turn.mode, question: turn.question, check_attempt_id: turn.check_attempt_id,
      block_index: turn.block_index },
      semantic: JSON.stringify({ turn_id: turn.turn_id, task_id: turn.task.task_id }),
      beforeIds: new Set(turns.map((item) => item.turn_id)), previous: turn }
    tutorIntent.current = intent
    return submitTutorIntent(intent)
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
  async function readCheckReceipt(intent: CheckIntent, signal: AbortSignal) {
    const saved = (await listCheckAttempts(courseId, lessonId, version, signal)).map(assertCurrent)
    if (signal.aborted) throw new DOMException('已离开课时', 'AbortError')
    client.setQueryData(checksKey, saved)
    return newlySavedCheck(saved, intent.body, intent.beforeIds)
  }
  function confirmCheckReceipt(intent: CheckIntent, saved: CourseSelfCheckView) {
    assertCurrent(saved)
    client.setQueryData<CourseSelfCheckView[]>(checksKey, (current) => [
      ...(current || []).filter((item) => item.attempt_id !== saved.attempt_id), saved,
    ])
    keyFor.settle('save-check', intent.semantic)
    checkIntent.current = null
    setSaveRecovery(null)
  }
  async function submitCheckIntent(intent: CheckIntent) {
    return operation.run(`check:${intent.body.check_ref}`, async (signal) => {
      try {
        intent.key ??= await keyFor('save-check', intent.semantic)
        if (signal.aborted) throw new DOMException('已离开课时', 'AbortError')
        return assertCurrent(await saveCheckAttempt(courseId, lessonId, intent.body, intent.key, signal))
      } catch (cause) {
        if (signal.aborted) throw cause
        if (!isUnconfirmedCourseOperation(cause)) {
          checkIntent.current = null
          setSaveRecovery(null)
          throw cause
        }
        setSaveRecovery({ checkRef: intent.body.check_ref, checked: false })
        try {
          const receipt = await readCheckReceipt(intent, signal)
          if (receipt) return receipt
        } catch (readError) {
          if (inaccessibleError(readError) || signal.aborted) throw readError
        }
        throw cause
      }
    }, (saved) => confirmCheckReceipt(intent, saved))
  }
  async function save(checkRef: string, answer: CourseSelfCheckCreate['answer'], intentId?: string) {
    if (operation.pending !== null || checkIntent.current || tutorIntent.current ||
      checksQuery.isPending || checksQuery.error || inaccessible) return
    const body: CourseSelfCheckCreate = { expected_content_version: version, check_ref: checkRef,
      answer: Array.isArray(answer) ? [...answer].sort() : answer.trim() }
    // B02：intentId 标识本轮作答。同一轮的网络重试复用同一幂等键；
    // 「再想一次」开启新轮，相同内容也会作为新的 attempt 保存。
    const semantic = JSON.stringify(intentId ? { ...body, intent_id: intentId } : body)
    const intent = { body, semantic, beforeIds: new Set(attempts.map((item) => item.attempt_id)) }
    checkIntent.current = intent
    return submitCheckIntent(intent)
  }
  async function recoverSave(retryOriginal = false) {
    const intent = checkIntent.current
    if (!intent || operation.pending !== null || inaccessible) return
    if (retryOriginal) return submitCheckIntent(intent)
    return operation.run(`check:${intent.body.check_ref}`, async (signal) => {
      const receipt = await readCheckReceipt(intent, signal)
      if (!receipt) {
        setSaveRecovery({ checkRef: intent.body.check_ref, checked: true })
        throw notConfirmed()
      }
      return receipt
    }, (saved) => confirmCheckReceipt(intent, saved))
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
    operationState: operation.state,
    settling: settle.active,
    syncing,
    saveRecovery,
    requestRecovery,
    recoverSave,
    recoverTutorRequest,
    refreshFeedback,
    ask,
    retry,
    cancel,
    save,
  }
}

export type LessonTutorController = ReturnType<typeof useLessonTutor>
