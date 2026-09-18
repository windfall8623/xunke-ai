import { LoaderCircle, RefreshCw, Square } from 'lucide-react'
import { ErrorNotice, LlmSettingsLink } from '../../components/ui'
import { providerErrorMessage } from '../../services/providerErrors'
import type { QaTask } from '../../types/qa'
import { activeTask } from './useQaSession'

// 只映射任务阶段流里的真实公开阶段；不虚构百分比或预计完成时间。
const stages: Record<string, string> = {
  pending: '正在排队',
  queued: '正在排队',
  starting: '正在准备回答',
  retrieving: '正在检索资料',
  generating: '正在生成回答',
  completed: '回答完成',
}

export function qaFailureLabel(code?: string | null, fallback?: string | null) {
  const errors: Record<string, string> = {
    PROVIDER_UNAVAILABLE: '回答服务暂不可用',
    LLM_UNAVAILABLE: '回答服务暂不可用',
    RETRIEVAL_UNAVAILABLE: '资料检索暂不可用，请稍后重试。',
    RERANKER_TIMEOUT: '资料筛选超时，请稍后重试。',
    GENERATION_VALIDATION_FAILED: '本次回答未通过依据核验，请调整问题后重试。',
    ANSWER_VALIDATION_FAILED: '本次回答未通过依据核验，请调整问题后重试。',
    BUDGET_EXCEEDED: '本次任务已达到调用预算，请稍后重试。',
    SOURCE_UNAVAILABLE: '所选资料已不可用，请更改问答范围。',
    SOURCE_REVOKED: '所选资料已不可用，请更改问答范围。',
    TIMEOUT: '回答服务超时，请稍后重试。',
  }
  return (
    providerErrorMessage(code) || fallback || errors[code || ''] || '本次回答未能完成，请稍后重试。'
  )
}

export function TaskProgress({
  task,
  cancelling,
  cancelError,
  taskError,
  settling = false,
  onCancel,
  onRefresh,
  onRetry,
}: {
  task: QaTask | null
  cancelling: boolean
  cancelError: unknown
  taskError: unknown
  /** 失败/取消后业务记录尚未确认同步；超时后仍展示，等待用户手动重试。 */
  settling?: boolean
  onCancel: () => void
  onRefresh: () => void
  onRetry?: () => void
}) {
  const running = activeTask(task)
  return (
    <div className={`qa-task qa-task-${task?.status || 'pending'}`} aria-live="polite">
      <p role="status">
        {running && <LoaderCircle size={17} className="spin" />}
        {task?.status === 'cancelled'
          ? '已取消本次回答'
          : task?.status === 'failed'
            ? qaFailureLabel(task.error_code, task.error_message)
            : stages[task?.stage || 'queued'] || '正在准备回答'}
      </p>
      {running ? (
        <p className="tiny muted">进度已保存，重新打开此会话可继续查看。</p>
      ) : (
        settling && <p className="tiny muted">任务已结束，记录同步中</p>
      )}
      {task?.status === 'failed' && <LlmSettingsLink code={task.error_code} />}
      <ErrorNotice error={taskError} onRetry={onRefresh} />
      <ErrorNotice error={cancelError} />
      <div className="button-row">
        {running && (
          <button className="text-button" type="button" disabled={cancelling} onClick={onCancel}>
            <Square size={14} />
            {cancelling ? '正在取消…' : '取消回答'}
          </button>
        )}
        {task?.status === 'failed' && onRetry && (
          <button className="text-button" type="button" onClick={onRetry}>
            <RefreshCw size={14} />
            重试这个问题
          </button>
        )}
      </div>
    </div>
  )
}
