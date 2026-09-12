import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useIdentityKey } from '../app/AuthProvider'
import { ErrorNotice, Loading, PageHeading, StatusBadge } from '../components/ui'
import { useSettleWatch, useTaskEvents, type SettleWatch } from '../features/tasks/useTaskEvents'
import { cancelPracticeTask, getPracticeTask, practiceKeys } from '../services/practice'
import { providerErrorMessage } from '../services/providerErrors'
import { studyErrorMessage } from '../services/study'
import type { PracticeTask } from '../types/practice'
import type { TaskEvent, TaskStreamState } from '../types/taskEvent'

type ObservedTask = PracticeTask & { business_settled?: boolean }
const activeStatuses = ['pending', 'running']
const taskStages: Record<string, string> = {
  queued: '等待开始',
  starting: '正在开始任务',
  retrieving: '正在查找相关资料',
  generating: '正在生成练习题目',
  validating: '正在核验题目依据',
  grading: '正在根据资料和评分要点核对你的回答。',
  saving: '正在保存任务结果',
}

const taskErrors: Record<string, string> = {
  RERANKER_TIMEOUT: '资料筛选超时，请稍后重试。',
  RETRIEVAL_UNAVAILABLE: '资料检索暂不可用，请稍后重试。',
  SOURCE_UNAVAILABLE: '所选资料已不可用，请重新选择资料。',
  INSUFFICIENT_EVIDENCE: '所选资料不足以支持这组练习，请调整目标或题型。',
  GENERATION_VALIDATION_FAILED: '本次结果未通过依据核验，请调整目标后重试。',
  BUDGET_EXCEEDED: '本次任务达到调用预算，请减少题量后重试。',
  deadline_exceeded: '任务处理超时，请稍后重试。',
}

export function PracticeTaskPage() {
  const { taskId = '' } = useParams()
  const identity = useIdentityKey()
  const client = useQueryClient()
  const navigate = useNavigate()
  const [execution, setExecution] = useState<{ taskId: string; id: string } | null>(null)
  const streamStateRef = useRef<TaskStreamState>('closed')
  const settleStateRef = useRef<SettleWatch>({ taskId: null, active: false, expired: false })
  const [canceling, setCanceling] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const queryKey = practiceKeys.task(identity, taskId)
  const query = useQuery<ObservedTask>({
    queryKey,
    queryFn: ({ signal }) => getPracticeTask(taskId, signal),
    retry: false,
    staleTime: 0,
    gcTime: 0,
    refetchInterval: (query) => {
      const current = query.state.data
      const settle = settleStateRef.current
      if (current && ['failed', 'cancelled'].includes(current.status))
        return settle.taskId === taskId && settle.active && !settle.expired ? 2000 : false
      if (!activeStatuses.includes(current?.status || '')) return false
      return streamStateRef.current === 'streaming' ? 30_000 : 2500
    },
    refetchIntervalInBackground: false,
  })
  const task = query.data
  const settle = useSettleWatch(
    task && { ...task, execution_id: execution?.taskId === taskId ? execution.id : undefined },
    () => {
      if (task?.practice_id)
        void client.invalidateQueries({
          queryKey: practiceKeys.practice(identity, task.practice_id),
        })
    },
  )
  settleStateRef.current = settle
  const handleTaskEvent = (event: TaskEvent) => {
    if (event.type === 'source_revoked') {
      void client.invalidateQueries({ queryKey })
      return
    }
    if (!event.executionId.startsWith(`${taskId}.a`)) return
    setExecution((current) =>
      current?.taskId === taskId && current.id === event.executionId
        ? current
        : { taskId, id: event.executionId },
    )
    if (
      event.type === 'reset' ||
      !['phase', 'snapshot'].includes(event.type) ||
      ('payload' in event && !activeStatuses.includes(event.payload.status))
    ) {
      void client.invalidateQueries({ queryKey })
      return
    }
    const { payload } = event
    client.setQueryData<ObservedTask>(queryKey, (current) =>
      current?.task_id === taskId
        ? {
            ...current,
            status: payload.status as PracticeTask['status'],
            stage: payload.stage || payload.status,
          }
        : current,
    )
  }
  const streamState = useTaskEvents({
    path: taskId ? `/practice/tasks/${encodeURIComponent(taskId)}/events` : undefined,
    taskId,
    enabled:
      !!taskId &&
      (activeStatuses.includes(task?.status || '') ||
        (!!task && ['failed', 'cancelled'].includes(task.status) && !task.business_settled)),
    onEvent: handleTaskEvent,
    onResume: () => void client.invalidateQueries({ queryKey }),
  })
  streamStateRef.current = streamState
  useEffect(() => {
    if (query.data?.status === 'completed')
      navigate(`/practice/${encodeURIComponent(query.data.practice_id)}`, { replace: true })
  }, [query.data, navigate])
  if (query.error)
    return (
      <ErrorNotice
        error={studyErrorMessage(query.error)}
        onRetry={() => {
          void query.refetch()
        }}
      />
    )
  const terminal = task && ['failed', 'cancelled'].includes(task.status)
  return (
    <div className="narrow-page stack-form">
      <PageHeading
        eyebrow="循课 · 练习任务"
        title={
          terminal
            ? '这次任务暂未完成'
            : task?.operation === 'grade'
              ? '正在评分'
              : '正在准备综合练习'
        }
        description="可以离开此页，稍后通过任务地址继续查看。"
      />
      {!task ? (
        <Loading />
      ) : (
        <section className="card stack-form">
          <StatusBadge status={task.status} />
          <p role="status">
            {terminal
              ? providerErrorMessage(task.error_code) ||
                taskErrors[task.error_code || ''] ||
                task.error_message ||
                '任务已停止，请返回学习空间后重试。'
              : taskStages[task.stage] ||
                (task.operation === 'grade'
                  ? '正在根据资料和评分要点核对你的回答。'
                  : '正在读取固定范围的资料、生成题目并核验依据。')}
          </p>
          {settle.active && (
            <p className="tiny muted" role="status">
              记录同步中
            </p>
          )}
          <div className="button-row">
            <Link className="button secondary" to="/study">
              返回学习空间
            </Link>
            <button
              className="button secondary"
              onClick={() => {
                void query.refetch()
              }}
            >
              刷新进度
            </button>
            {!terminal && (
              <button
                className="text-button"
                disabled={canceling}
                onClick={async () => {
                  setCanceling(true)
                  setError(null)
                  try {
                    await cancelPracticeTask(taskId)
                    await query.refetch()
                  } catch (cause) {
                    setError(cause)
                  } finally {
                    setCanceling(false)
                  }
                }}
              >
                取消任务
              </button>
            )}
          </div>
        </section>
      )}
      {error != null && <ErrorNotice error={studyErrorMessage(error)} />}
    </div>
  )
}
