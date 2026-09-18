import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Check, FileSearch, Pause, Play, RefreshCw, Sparkles } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useIdentityKey } from '../app/AuthProvider'
import { ErrorNotice, LlmSettingsLink, Loading, StatusBadge } from '../components/ui'
import { useSettleWatch, useTaskEvents, type SettleWatch } from '../features/tasks/useTaskEvents'
import { api } from '../services/api'
import { providerErrorMessage } from '../services/providerErrors'
import { safeStudyReturn, withCourseReturn } from '../services/courseNavigation'
import type { Task } from '../types/api'
import type { TaskEvent, TaskStreamState } from '../types/taskEvent'

type ObservedTask = Task & { business_settled?: boolean }
const activeStatuses = ['pending', 'queued', 'running']

const stages: Record<string, { label: string; step: number }> = {
  pending: { label: '等待开始', step: 0 },
  queued: { label: '等待开始', step: 0 },
  starting: { label: '正在开始任务', step: 0 },
  resolving_scope: { label: '确认资料范围', step: 0 },
  parsing: { label: '正在读取资料', step: 0 },
  retrieving: { label: '正在查找相关依据', step: 0 },
  retrieval: { label: '正在查找相关依据', step: 0 },
  planning: { label: '正在梳理学习目标', step: 1 },
  generating: { label: '正在生成题目', step: 1 },
  generation: { label: '正在生成题目', step: 1 },
  validating: { label: '正在核验题目依据', step: 2 },
  validation: { label: '正在核验题目依据', step: 2 },
  saving: { label: '正在保存练习', step: 2 },
  completed: { label: '练习准备好了', step: 3 },
}
const errors: Record<string, string> = {
  INSUFFICIENT_EVIDENCE: '所选资料还不足以支持这组题目。可以减少题量，或明确选择更多资料后再试。',
  SOURCE_UNAVAILABLE: '所选资料已失效或尚未就绪，请重新选择资料。',
  RETRIEVAL_UNAVAILABLE: '资料检索暂时不可用，请稍后重试。',
  RERANKER_TIMEOUT: '资料筛选超时，请稍后重试。',
  GENERATION_VALIDATION_FAILED: '这次的题目未能通过依据核验，请调整目标后重试。',
  BUDGET_EXCEEDED: '本次任务已达到调用预算，请稍后重试或减少题量。',
}
export function TaskPage() {
  const { taskId = '' } = useParams()
  const [searchParams] = useSearchParams()
  const returnTo = safeStudyReturn(searchParams.get('returnTo')) || '/'
  const identity = useIdentityKey()
  const client = useQueryClient()
  const [observe, setObserve] = useState(true)
  const [execution, setExecution] = useState<{ taskId: string; id: string } | null>(null)
  const streamStateRef = useRef<TaskStreamState>('closed')
  const settleStateRef = useRef<SettleWatch>({ taskId: null, active: false, expired: false })
  const navigate = useNavigate()
  const queryKey = [identity, 'task', taskId] as const
  const query = useQuery<ObservedTask>({
    queryKey,
    queryFn: ({ signal }) => api.task(taskId, signal),
    refetchInterval: (state) => {
      if (!observe) return false
      const current = state.state.data
      const settle = settleStateRef.current
      if (current && ['failed', 'cancelled'].includes(current.status))
        return settle.taskId === taskId && settle.active && !settle.expired ? 2000 : false
      if (!activeStatuses.includes(current?.status || '')) return false
      return streamStateRef.current === 'streaming' ? 30_000 : 2500
    },
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: observe,
    refetchOnReconnect: observe,
  })
  const task = query.data
  const settle = useSettleWatch(
    task && { ...task, execution_id: execution?.taskId === taskId ? execution.id : undefined },
    () => void client.invalidateQueries({ queryKey }),
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
      // 终态与收尾只触发原业务 GET；结果和跳转目标不从事件中读取。
      void client.invalidateQueries({ queryKey })
      return
    }
    const { payload } = event
    client.setQueryData<ObservedTask>(queryKey, (current) =>
      current?.task_id === taskId
        ? {
            ...current,
            status: payload.status as Task['status'],
            stage: payload.stage || payload.status,
          }
        : current,
    )
  }
  const streamState = useTaskEvents({
    path: taskId ? `/quiz/task/${encodeURIComponent(taskId)}/events` : undefined,
    taskId,
    enabled:
      observe &&
      !!taskId &&
      (activeStatuses.includes(task?.status || '') ||
        (!!task && ['failed', 'cancelled'].includes(task.status) && !task.business_settled)),
    onEvent: handleTaskEvent,
    onResume: () => void client.invalidateQueries({ queryKey }),
  })
  streamStateRef.current = streamState
  useEffect(() => {
    const quizId = task?.quiz_id || task?.result?.quiz_id
    if (task?.status === 'completed' && quizId)
      navigate(withCourseReturn(`/quizzes/${encodeURIComponent(quizId)}`, returnTo), {
        replace: true,
      })
  }, [task, navigate, returnTo])
  const stage = stages[task?.stage || task?.status || 'pending'] || {
    label: '正在准备练习',
    step: 1,
  }
  const failed = task?.status === 'failed' || task?.status === 'cancelled'
  return (
    <div className="narrow-page">
      <Link className="back-link" to={returnTo}>
        <ArrowLeft size={16} />
        {returnTo.startsWith('/study/courses/')
          ? '返回课程'
          : returnTo.startsWith('/qa')
            ? '返回资料问答'
            : '返回学习首页'}
      </Link>
      <section className="card task-card">
        <div className="task-orbit">
          <Sparkles size={38} className={failed ? '' : 'float'} />
        </div>
        <p className="eyebrow">留一点时间，给一次好练习</p>
        <h1>{failed ? '这次练习暂未完成' : '正在准备你的练习'}</h1>
        <p className="muted">你可以离开此页，稍后通过任务地址继续查看。</p>
        {query.isPending && <Loading />}
        <ErrorNotice
          error={query.error}
          onRetry={() => {
            void query.refetch()
          }}
        />
        {task && (
          <>
            <StatusBadge status={task.status} />
            <div className="task-stage" role="status">
              {failed
                ? providerErrorMessage(task.error_code) ||
                  errors[task.error_code || ''] ||
                  task.error_message ||
                  '任务已停止，可调整目标后重试。'
                : stage.label}
            </div>
            {failed && <LlmSettingsLink code={task.error_code} />}
            {settle.active && (
              <p className="tiny muted" role="status">
                记录同步中
              </p>
            )}
            <ol className="task-steps">
              {['读取资料', '生成题目', '核验依据'].map((label, index) => (
                <li
                  key={label}
                  className={
                    stage.step > index ? 'done' : stage.step === index && !failed ? 'current' : ''
                  }
                >
                  <span>{stage.step > index ? <Check size={17} /> : index + 1}</span>
                  {label}
                </li>
              ))}
            </ol>
          </>
        )}
        <div className="button-row centered">
          {failed ? (
            <Link to={returnTo} className="button primary">
              {providerErrorMessage(task?.error_code) ? '返回后重试' : '调整目标后重试'}
              <ArrowLeft size={16} />
            </Link>
          ) : (
            <button className="button secondary" onClick={() => setObserve(!observe)}>
              {observe ? <Pause size={16} /> : <Play size={16} />}
              {observe ? '暂停自动刷新' : '恢复自动刷新'}
            </button>
          )}
          <button
            className="button secondary"
            onClick={() => {
              void query.refetch()
            }}
            disabled={query.isFetching}
          >
            <RefreshCw size={16} />
            刷新进度
          </button>
        </div>
        <p className="tiny muted task-help">
          <FileSearch size={15} />
          暂停刷新只停止页面观察，任务仍会继续处理。
        </p>
      </section>
    </div>
  )
}
