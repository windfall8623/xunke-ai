import { useEffect, useRef, useState } from 'react'
import { useIdentityKey } from '../../app/AuthProvider'
import { getSessionRevision } from '../../services/http'
import { subscribeTaskEvents } from '../../services/taskEvents'
import type { TaskEvent, TaskStreamState } from '../../types/taskEvent'

const SSE_FAILURE_LIMIT = 3
const POLLING_RECOVERY_MS = 30_000
const SETTLE_WATCH_MS = 60_000

export type UseTaskEventsOptions = {
  /** 形如 '/qa/tasks/{id}/events' 的同源路径；未提供时不订阅。 */
  path?: string
  taskId?: string
  enabled?: boolean
  onEvent?: (event: TaskEvent) => void
  /** 页面回到前台恢复订阅前触发一次业务 GET，由调用方刷新自己的查询。 */
  onResume?: () => void
}

/**
 * 任务阶段订阅的状态机：connecting → streaming；连续失败 3 次降级为 polling，
 * 30 秒后至多尝试恢复一次；页面隐藏时断开并暂停重连，identity / sessionRevision
 * 变化时立即断开旧流，且回调外发前核对身份，防止迟到事件污染新页面。
 */
export function useTaskEvents(options: UseTaskEventsOptions): TaskStreamState {
  const { path, taskId, enabled = true, onEvent, onResume } = options
  const identity = useIdentityKey()
  const sessionRevision = getSessionRevision()
  const [state, setState] = useState<TaskStreamState>('closed')
  const identityRef = useRef(identity)
  identityRef.current = identity
  const eventRef = useRef(onEvent)
  const resumeRef = useRef(onResume)
  useEffect(() => {
    eventRef.current = onEvent
    resumeRef.current = onResume
  })

  useEffect(() => {
    if (!enabled || !path || !taskId) {
      setState('closed')
      return
    }
    const capturedIdentity = identity
    const capturedSession = sessionRevision
    const stillCurrent = () =>
      identityRef.current === capturedIdentity && capturedSession === getSessionRevision()
    let controller: AbortController | null = null
    let failures = 0
    let lastState: TaskStreamState | undefined
    let polling = false
    let recoveryArmed = true
    let paused = document.hidden
    let recoveryTimer: ReturnType<typeof setTimeout> | undefined

    const scheduleRecovery = () => {
      if (!recoveryArmed || paused || recoveryTimer) return
      recoveryArmed = false
      recoveryTimer = setTimeout(() => {
        recoveryTimer = undefined
        if (!stillCurrent() || paused) return
        polling = false
        start()
      }, POLLING_RECOVERY_MS)
    }

    const enterPolling = () => {
      polling = true
      controller?.abort()
      controller = null
      setState('polling')
      scheduleRecovery()
    }

    const start = () => {
      if (paused || polling || controller) return
      failures = 0
      lastState = undefined
      setState('connecting')
      const next = new AbortController()
      controller = next
      void subscribeTaskEvents({
        path,
        taskId,
        identityKey: capturedIdentity,
        sessionRevision: capturedSession,
        signal: next.signal,
        onEvent: (event) => {
          if (!stillCurrent()) return
          eventRef.current?.(event)
        },
        onState: (incoming) => {
          if (!stillCurrent()) return
          if (polling && incoming !== 'streaming') return
          if (incoming === 'streaming') {
            failures = 0
            recoveryArmed = true
          } else if (incoming === 'connecting') {
            // 每条 connecting 代表上一次尝试已失败（或首次连接）。
            if (lastState === 'connecting') failures += 1
            else if (lastState === 'streaming') failures = 1
            if (failures >= SSE_FAILURE_LIMIT) {
              enterPolling()
              return
            }
          }
          lastState = incoming
          setState(incoming)
        },
      }).catch(() => {
        // 路径校验等同步错误已由 onState('closed') 之外的异常路径表达，这里避免未处理拒绝。
      })
    }

    const onVisibility = () => {
      if (document.hidden) {
        paused = true
        controller?.abort()
        controller = null
        if (recoveryTimer) {
          clearTimeout(recoveryTimer)
          recoveryTimer = undefined
          recoveryArmed = true
        }
        return
      }
      if (paused === false) return
      paused = false
      if (!stillCurrent()) return
      resumeRef.current?.()
      if (polling) scheduleRecovery()
      else start()
    }
    document.addEventListener('visibilitychange', onVisibility)
    if (!document.hidden) start()
    return () => {
      paused = true
      controller?.abort()
      controller = null
      if (recoveryTimer) clearTimeout(recoveryTimer)
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [enabled, path, taskId, identity, sessionRevision])

  return state
}

export type SettleWatch = {
  /** 观察窗针对的任务；null 表示无需观察。 */
  taskId: string | null
  /** 失败/取消后业务记录尚未确认同步；超时后仍保持 true 以展示“记录同步中”。 */
  active: boolean
  /** 已超过兜底窗口，调用方应停止 GET 兜底刷新。 */
  expired: boolean
}

/**
 * 失败/取消任务的调和收尾观察窗：business_settled 翻真（SSE 事件或任务 GET）时
 * 触发一次 onSettled 并关闭；60 秒内未收尾则标记 expired，由调用方停止兜底刷新。
 */
export function useSettleWatch(
  task:
    | { task_id: string; status: string; business_settled?: boolean; execution_id?: string }
    | null
    | undefined,
  onSettled: () => void,
): SettleWatch {
  type Window = { taskId: string; executionId?: string; deadline: number }
  const [watched, setWatched] = useState<Window | null>(null)
  const watchedRef = useRef<Window | null>(null)
  const [expired, setExpired] = useState(false)
  const onSettledRef = useRef(onSettled)
  const taskId = task?.task_id
  const executionId = task?.execution_id
  const status = task?.status
  const businessSettled = task?.business_settled
  useEffect(() => {
    onSettledRef.current = onSettled
  })
  useEffect(() => {
    const current = watchedRef.current
    const sameExecution =
      current?.taskId === taskId &&
      (!executionId || !current?.executionId || current.executionId === executionId)
    const failing =
      taskId && ['failed', 'cancelled'].includes(status || '') && businessSettled !== true
    if (failing && taskId) {
      if (sameExecution && current) {
        // GET 不一定带执行编号；补到编号时保留最初截止时间，不能续期观察窗。
        if (executionId && !current.executionId) {
          watchedRef.current = { ...current, executionId }
          setWatched(watchedRef.current)
        }
        return
      }
      watchedRef.current = { taskId, executionId, deadline: Date.now() + SETTLE_WATCH_MS }
      setWatched(watchedRef.current)
      setExpired(false)
      return
    }
    // 先清空再通知：即使回调触发同步刷新，同一观察窗也只通知一次。
    watchedRef.current = null
    setWatched(null)
    setExpired(false)
    if (businessSettled && sameExecution && current) onSettledRef.current()
  }, [taskId, executionId, status, businessSettled])
  useEffect(() => {
    if (!watched) return
    const timer = setTimeout(
      () => {
        if (watchedRef.current === watched) setExpired(true)
      },
      Math.max(0, watched.deadline - Date.now()),
    )
    return () => clearTimeout(timer)
  }, [watched])
  return { taskId: watched?.taskId || null, active: watched !== null, expired }
}
