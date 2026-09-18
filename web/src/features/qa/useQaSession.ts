import { useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useIdentityKey } from '../../app/AuthProvider'
import { ApiError } from '../../services/http'
import { qaApi, qaKeys } from '../../services/qa'
import { qaSubmissionKey } from '../../services/qaDrafts'
import type { SourceScope } from '../../types/api'
import type { QaMessageCreate, QaSessionList, QaTask } from '../../types/qa'
import type { TaskEvent, TaskStreamState } from '../../types/taskEvent'
import { useSettleWatch, useTaskEvents, type SettleWatch } from '../tasks/useTaskEvents'

type Submission = { key: string; data: QaMessageCreate }
export const activeTask = (task?: Pick<QaTask, 'status'> | null) =>
  task?.status === 'pending' || task?.status === 'running'
export const sourceError = (error: unknown) =>
  error instanceof ApiError && [403, 404, 410].includes(error.status)
const revokedCode = (code?: string | null) =>
  ['SOURCE_REVOKED', 'SOURCE_UNAVAILABLE', 'AUTHORIZATION_REVOKED'].includes(code || '')
const uncertainError = (error: unknown) =>
  error instanceof ApiError &&
  (error.status === 0 || error.status >= 500 || error.code === 'INVALID_RESPONSE')

function savedSubmission(storageKey: string): Submission | null {
  try {
    const parsed = JSON.parse(sessionStorage.getItem(storageKey) || 'null') as Submission | null
    return parsed &&
      typeof parsed.key === 'string' &&
      typeof parsed.data?.content === 'string' &&
      parsed.data.content.trim().length > 0 &&
      parsed.data.content.length <= 2000 &&
      Number.isInteger(parsed.data.scope_revision) &&
      parsed.data.scope_revision > 0
      ? parsed
      : null
  } catch {
    return null
  }
}

export function useQaSession(sessionId: string) {
  const identity = useIdentityKey()
  const client = useQueryClient()
  const storageKey = qaSubmissionKey(identity, sessionId)
  const [uncertain, setUncertain] = useState<Submission | null>(() => savedSubmission(storageKey))
  const [question, setQuestion] = useState('')
  const [submitError, setSubmitError] = useState<unknown>(null)
  const [scopeError, setScopeError] = useState<unknown>(null)
  const [cancelError, setCancelError] = useState<unknown>(null)
  const [submitting, setSubmitting] = useState(false)
  const [scopeSaving, setScopeSaving] = useState(false)
  const [cancelling, setCancelling] = useState(false)
  const [privacyHold, setPrivacyHold] = useState(false)
  const [localTask, setLocalTask] = useState<QaTask | null>(null)
  const [submittedQuestion, setSubmittedQuestion] = useState<Submission | null>(null)
  const inFlight = useRef(false)
  const live = useRef(true)
  const controllers = useRef(new Set<AbortController>())
  const terminalIds = useRef(new Set<string>())
  const handledTerminals = useRef(new Set<string>())
  const streamStateRef = useRef<TaskStreamState>('closed')
  const settleStateRef = useRef<SettleWatch>({ taskId: null, active: false, expired: false })
  const queryKey = qaKeys.session(identity, sessionId)
  const messagesKey = qaKeys.messages(identity, sessionId)
  const sessionQuery = useQuery({
    queryKey,
    queryFn: ({ signal }) => qaApi.session(sessionId, signal),
    staleTime: 0,
    gcTime: 0,
    refetchOnMount: 'always',
    retry: false,
  })
  const session = sessionQuery.data
  const hidden =
    privacyHold || sourceError(sessionQuery.error) || session?.source_status === 'revoked'
  const history = useInfiniteQuery({
    queryKey: messagesKey,
    queryFn: ({ signal, pageParam }) => qaApi.messages(sessionId, pageParam, signal),
    initialPageParam: undefined as number | undefined,
    getNextPageParam: (last) => (last.has_more ? (last.next_before ?? undefined) : undefined),
    enabled: !!session && !hidden,
    staleTime: 0,
    gcTime: 0,
    retry: false,
    refetchOnMount: 'always',
  })
  const serverActiveId = session?.active_task_id
  const taskId = activeTask(localTask)
    ? localTask!.task_id
    : serverActiveId && !terminalIds.current.has(serverActiveId)
      ? serverActiveId
      : undefined
  const taskQuery = useQuery({
    queryKey: qaKeys.task(identity, sessionId, taskId),
    queryFn: ({ signal }) => qaApi.task(taskId!, signal),
    enabled: !!taskId && !hidden,
    initialData: taskId && localTask?.task_id === taskId ? localTask : undefined,
    refetchInterval: (query) => {
      if (query.state.error) return false
      const current = query.state.data
      const settle = settleStateRef.current
      if (settle.active && !settle.expired)
        return current && ['failed', 'cancelled'].includes(current.status) ? 2000 : false
      if (!activeTask(current)) return false
      // SSE 流存活时降为保险刷新，connecting/closed/polling 态保持原频率。
      return streamStateRef.current === 'streaming' ? 30_000 : 1500
    },
    refetchIntervalInBackground: false,
    staleTime: 0,
    gcTime: 0,
    retry: false,
  })
  const task = hidden ? null : taskId ? taskQuery.data || localTask : localTask
  const messages = hidden
    ? []
    : [
        ...new Map(
          (history.data?.pages.flatMap((page) => page.items) || []).map((message) => [
            message.message_id,
            message,
          ]),
        ).values(),
      ].sort((a, b) => a.sequence - b.sequence)

  const remember = useCallback(
    (value: Submission | null) => {
      setUncertain(value)
      try {
        if (value) sessionStorage.setItem(storageKey, JSON.stringify(value))
        else sessionStorage.removeItem(storageKey)
      } catch {
        /* The in-memory key still protects retries when storage is unavailable. */
      }
    },
    [storageKey],
  )

  const conceal = useCallback(() => {
    setPrivacyHold(true)
    setQuestion('')
    setSubmittedQuestion(null)
    setLocalTask(null)
    setSubmitError(null)
    remember(null)
    controllers.current.forEach((controller) => controller.abort())
    const sensitive = {
      predicate: (query: { queryKey: readonly unknown[] }) =>
        query.queryKey[0] === identity &&
        query.queryKey[1] === 'qa' &&
        query.queryKey[2] === sessionId &&
        query.queryKey[3] !== 'session',
    }
    void client.cancelQueries(sensitive)
    client.removeQueries(sensitive)
    client.setQueriesData<QaSessionList>({ queryKey: qaKeys.sessions(identity) }, (current) =>
      current
        ? {
            ...current,
            items: current.items.map((item) =>
              item.session_id === sessionId
                ? { ...item, title: '资料已不可用', scope: null, source_status: 'revoked' }
                : item,
            ),
          }
        : current,
    )
  }, [client, identity, sessionId, remember])

  const refresh = useCallback(async () => {
    await Promise.allSettled([
      client.invalidateQueries({ queryKey: qaKeys.session(identity, sessionId) }),
      client.invalidateQueries({ queryKey: qaKeys.messages(identity, sessionId) }),
      client.invalidateQueries({ queryKey: qaKeys.sessions(identity) }),
    ])
  }, [client, identity, sessionId])

  const settle = useSettleWatch(task, refresh)
  settleStateRef.current = settle
  const streamTaskId = taskId ?? settle.taskId ?? undefined
  const handleTaskEvent = (event: TaskEvent) => {
    if (event.type === 'source_revoked') {
      // SSE 可能是撤销的唯一信号：立即走既有的 conceal 路径，
      // 清除本会话敏感缓存并停止读取，不等下一次 GET 才发现。
      conceal()
      return
    }
    if (!streamTaskId || event.type === 'reset') return
    const { payload } = event
    client.setQueryData<QaTask>(qaKeys.task(identity, sessionId, streamTaskId), (current) => {
      if (!current || current.task_id !== streamTaskId) return current
      return {
        ...current,
        status: payload.status as QaTask['status'],
        stage: payload.stage || payload.status,
        error_code: payload.error_code ?? current.error_code,
        business_settled: payload.business_settled,
      }
    })
    if (['completed', 'failed', 'cancelled'].includes(event.type))
      void client.invalidateQueries({ queryKey: qaKeys.task(identity, sessionId, streamTaskId) })
  }
  const streamState = useTaskEvents({
    path: streamTaskId ? `/qa/tasks/${streamTaskId}/events` : undefined,
    taskId: streamTaskId,
    enabled: !hidden && (!!taskId || settle.active),
    onEvent: handleTaskEvent,
    onResume: () => void refresh(),
  })
  streamStateRef.current = streamState

  useEffect(() => {
    live.current = true
    const expire = () => {
      try {
        sessionStorage.removeItem(storageKey)
      } catch {
        /* Storage can be disabled. */
      }
    }
    window.addEventListener('session-expired', expire)
    return () => {
      live.current = false
      controllers.current.forEach((controller) => controller.abort())
      window.removeEventListener('session-expired', expire)
    }
  }, [storageKey])

  useEffect(() => {
    if (
      session?.source_status === 'revoked' ||
      sourceError(sessionQuery.error) ||
      sourceError(history.error) ||
      sourceError(taskQuery.error) ||
      revokedCode(task?.error_code)
    )
      conceal()
  }, [
    session?.source_status,
    sessionQuery.error,
    history.error,
    taskQuery.error,
    task?.error_code,
    conceal,
  ])

  useEffect(() => {
    if (!task || activeTask(task) || handledTerminals.current.has(task.task_id)) return
    handledTerminals.current.add(task.task_id)
    terminalIds.current.add(task.task_id)
    setLocalTask(task)
    void refresh()
  }, [task, refresh])

  useEffect(() => {
    const revokedTasks = new Set(
      history.data?.pages.flatMap((page) =>
        page.items
          .filter((message) => message.status === 'revoked')
          .map((message) => message.task_id),
      ) || [],
    )
    if (!revokedTasks.size) return
    const answerIds = new Set<string>()
    const taskPrefix = [identity, 'qa', sessionId, 'task'] as const
    for (const [, cached] of client.getQueriesData<QaTask>({ queryKey: taskPrefix })) {
      if (cached && revokedTasks.has(cached.task_id) && cached.answer)
        answerIds.add(cached.answer.answer_id)
    }
    if (localTask && revokedTasks.has(localTask.task_id)) {
      if (localTask.answer) answerIds.add(localTask.answer.answer_id)
      setLocalTask(null)
      setSubmittedQuestion(null)
    }
    const affected = {
      predicate: (query: { queryKey: readonly unknown[] }) =>
        query.queryKey[0] === identity &&
        query.queryKey[1] === 'qa' &&
        query.queryKey[2] === sessionId &&
        ((query.queryKey[3] === 'task' && revokedTasks.has(String(query.queryKey[4]))) ||
          (query.queryKey[3] === 'evidence' && answerIds.has(String(query.queryKey[4])))),
    }
    void client.cancelQueries(affected)
    client.removeQueries(affected)
  }, [client, history.data, identity, sessionId, localTask])

  const acceptTask = (value: QaTask) => {
    if (!activeTask(value)) terminalIds.current.add(value.task_id)
    setLocalTask(value)
    client.setQueryData(qaKeys.task(identity, sessionId, value.task_id), value)
    void refresh()
  }

  const busy = submitting || scopeSaving || (!hidden && !!taskId)
  const post = async (submission: Submission) => {
    if (inFlight.current || hidden) return
    inFlight.current = true
    setSubmitting(true)
    setSubmitError(null)
    remember(submission)
    const controller = new AbortController()
    controllers.current.add(controller)
    try {
      const result = await qaApi.ask(sessionId, submission.data, submission.key, controller.signal)
      if (!live.current || controller.signal.aborted) return
      setSubmittedQuestion(submission)
      setQuestion('')
      remember(null)
      acceptTask(result)
    } catch (error) {
      if (!live.current || controller.signal.aborted) return
      if (!uncertainError(error)) remember(null)
      if (sourceError(error)) conceal()
      else {
        setSubmitError(error)
        if (error instanceof ApiError && error.status === 409) void refresh()
      }
    } finally {
      controllers.current.delete(controller)
      inFlight.current = false
      if (live.current) setSubmitting(false)
    }
  }

  const ask = (content = question) => {
    if (!session || busy || uncertain || hidden || !content.trim() || content.length > 2000) return
    void post({
      key: crypto.randomUUID(),
      data: { content: content.trim(), scope_revision: session.scope_revision },
    })
  }

  const updateScope = async (scope: SourceScope) => {
    if (!session || busy || uncertain) return false
    setScopeSaving(true)
    setScopeError(null)
    const controller = new AbortController()
    controllers.current.add(controller)
    try {
      const value = await qaApi.updateScope(
        sessionId,
        { scope, expected_revision: session.scope_revision },
        controller.signal,
      )
      if (!live.current || controller.signal.aborted) return false
      await client.cancelQueries({ queryKey: messagesKey })
      client.setQueryData(queryKey, value)
      client.setQueryData(messagesKey, { pages: [], pageParams: [] })
      setPrivacyHold(false)
      setLocalTask(null)
      setSubmittedQuestion(null)
      void refresh()
      return true
    } catch (error) {
      if (!live.current || controller.signal.aborted) return false
      setScopeError(error)
      if (sourceError(error)) conceal()
      if (error instanceof ApiError && error.status === 409) await refresh()
      return false
    } finally {
      controllers.current.delete(controller)
      if (live.current) setScopeSaving(false)
    }
  }

  const cancel = async () => {
    if (!taskId || cancelling) return
    setCancelling(true)
    setCancelError(null)
    const controller = new AbortController()
    controllers.current.add(controller)
    try {
      const value = await qaApi.cancel(taskId, controller.signal)
      if (!live.current || controller.signal.aborted) return
      await client.cancelQueries({ queryKey: qaKeys.task(identity, sessionId, taskId) })
      acceptTask(value)
    } catch (error) {
      if (!live.current || controller.signal.aborted) return
      if (sourceError(error)) conceal()
      else setCancelError(error)
    } finally {
      controllers.current.delete(controller)
      if (live.current) setCancelling(false)
    }
  }

  return {
    session,
    sessionQuery,
    history,
    messages,
    task,
    taskQuery,
    hidden,
    question,
    setQuestion,
    uncertain,
    submitting,
    submitError,
    busy,
    settling: settle.active,
    ask,
    cancel,
    cancelling,
    cancelError,
    scopeSaving,
    scopeError,
    updateScope,
    conceal,
    refresh,
    submittedQuestion,
    retrySubmission: () => {
      if (uncertain) void post(uncertain)
    },
  }
}
