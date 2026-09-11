import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useIdentityKey } from '../app/AuthProvider'
import { ErrorNotice, Loading, PageHeading, StatusBadge } from '../components/ui'
import { cancelPracticeTask, getPracticeTask, practiceKeys } from '../services/practice'
import { providerErrorMessage } from '../services/providerErrors'
import { studyErrorMessage } from '../services/study'

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
  const navigate = useNavigate()
  const [canceling, setCanceling] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const query = useQuery({
    queryKey: practiceKeys.task(identity, taskId),
    queryFn: ({ signal }) => getPracticeTask(taskId, signal),
    retry: false,
    staleTime: 0,
    gcTime: 0,
    refetchInterval: (query) =>
      ['pending', 'running'].includes(query.state.data?.status || '') ? 2500 : false,
    refetchIntervalInBackground: false,
  })
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
  const task = query.data
  const terminal = task && ['failed', 'cancelled'].includes(task.status)
  return (
    <div className="narrow-page stack-form">
      <PageHeading
        eyebrow="知学 AI · 练习任务"
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
              : task.operation === 'grade'
                ? '正在根据资料和评分要点核对你的回答。'
                : '正在读取固定范围的资料、生成题目并核验依据。'}
          </p>
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
