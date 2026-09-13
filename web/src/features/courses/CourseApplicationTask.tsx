import { useQuery } from '@tanstack/react-query'
import { FileText, RefreshCw, Save } from 'lucide-react'
import { useEffect, useId, useState } from 'react'
import { useIdentityKey } from '../../app/AuthProvider'
import { ErrorNotice, Loading, formatDate } from '../../components/ui'
import {
  COURSE_APPLICATION_ANSWER_MAX,
  courseAccessDenied,
  courseErrorMessage,
  courseKeys,
  coursesApi,
  courseTaskErrorMessage,
} from '../../services/courses'
import type {
  CourseApplicationAttemptView,
  CourseApplicationTaskView,
  CourseHelpUsage,
} from '../../types/course'
import { CourseOperationNotice } from './CourseOperationNotice'
import type { CourseOperationState } from './courseActionState'
import {
  HELP_USAGE_LABELS,
  applicationFeedbackState,
  criterionCreditLabel,
  isProvisionalFeedback,
} from './courseOutcomeFacts'

/**
 * 文本应用任务：排队、作答与阅读反馈。
 *
 * 服务器只接收文本，不执行用户提交的代码或命令。模型反馈与正式确认分开展示，
 * 反馈失败也不会丢弃已保存的回答。
 */
export function CourseApplicationTask({
  courseId,
  assessmentId,
  task,
  index,
  sealed,
  disabled,
  operationState,
  operationError,
  onSubmit,
  onRetryFeedback,
  recovery,
  onRecover,
  onReplay,
  onUnavailable,
  onEvidence,
}: {
  courseId: string
  assessmentId: string
  task: CourseApplicationTaskView
  index: number
  sealed: boolean
  disabled: boolean
  operationState: CourseOperationState
  operationError: unknown
  onSubmit: (
    task: CourseApplicationTaskView,
    answer: string,
    helpUsage: CourseHelpUsage,
  ) => Promise<CourseApplicationAttemptView | undefined>
  onRetryFeedback: (attempt: CourseApplicationAttemptView) => void
  recovery?: { checked: boolean } | null
  onRecover: () => void
  onReplay: () => void
  onUnavailable?: () => void
  onEvidence?: (sourceRef: string) => void
}) {
  const identity = useIdentityKey()
  const fieldId = useId()
  const attemptId = task.latest_attempt_id || ''
  const attemptQuery = useQuery({
    queryKey: courseKeys.applicationAttempt(identity, courseId, assessmentId, attemptId),
    queryFn: ({ signal }) =>
      coursesApi.applicationAttempt(courseId, assessmentId, attemptId, signal),
    enabled: !!attemptId,
    staleTime: 0,
    gcTime: 0,
    retry: false,
    refetchOnMount: 'always',
    refetchInterval: (state) => {
      const status = state.state.data?.feedback_task?.status
      return status === 'pending' || status === 'running' ? 3000 : false
    },
    refetchIntervalInBackground: false,
  })
  const inaccessible = courseAccessDenied(attemptQuery.error)
  const attempt = inaccessible ? undefined : attemptQuery.data
  const [answer, setAnswer] = useState('')
  const [helpUsage, setHelpUsage] = useState<CourseHelpUsage>('unknown')
  const [dirty, setDirty] = useState(false)
  useEffect(() => {
    if (!dirty) {
      setAnswer(attempt?.answer || '')
      setHelpUsage(attempt?.help_usage || 'unknown')
    }
  }, [attempt?.attempt_id, attempt?.answer, attempt?.help_usage, dirty])
  useEffect(() => {
    if (inaccessible) onUnavailable?.()
  }, [inaccessible, onUnavailable])
  const displayedAnswer = dirty ? answer : attempt?.answer || answer
  const trimmed = displayedAnswer.trim()
  const state = applicationFeedbackState(attempt)
  const feedback = attempt?.feedback
  const provisional = isProvisionalFeedback(feedback)
  const unchanged = !!attempt && trimmed === attempt.answer.trim()
  const overLimit = displayedAnswer.length > COURSE_APPLICATION_ANSWER_MAX
  const unreadReceipt = !!attemptId && !attempt
  const canSubmit = !!trimmed && !overLimit && !disabled && !sealed && !unchanged && !unreadReceipt
  async function submit() {
    if (!canSubmit) return
    const saved = await onSubmit(task, trimmed, helpUsage)
    if (saved) {
      setAnswer(saved.answer)
      setDirty(false)
    }
  }
  if (inaccessible) return null
  if (attemptId && attemptQuery.isPending)
    return <li className="course-application-task"><Loading>正在读取已保存的回答…</Loading></li>
  return (
    <li className="course-application-task">
      <div className="section-line">
        <h4>应用任务 {index + 1}</h4>
        <span className="badge">{task.source_policy === 'topic' ? '基于模型知识' : '依据所选资料'}</span>
      </div>
      <p className="course-application-prompt">{task.prompt}</p>
      {!!task.public_expectations.length && (
        <div className="course-application-expectations">
          <strong className="tiny">这次任务会看这些方面：</strong>
          <ul>
            {task.public_expectations.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      )}
      {!!task.support_quotes?.length && (
        <details className="course-application-quotes">
          <summary>查看可参考的资料片段</summary>
          {task.support_quotes.map((quote, position) => (
            <p key={position}>{quote}</p>
          ))}
        </details>
      )}
      {!!task.source_refs?.length && onEvidence && (
        <div className="course-citations">
          {task.source_refs.map((ref, position) => (
            <button
              type="button"
              className="text-button"
              key={ref}
              onClick={() => onEvidence(ref)}
              aria-label={`查看应用任务 ${index + 1} 的依据 ${position + 1}`}
            >
              <FileText size={13} />
              依据 {position + 1}
            </button>
          ))}
        </div>
      )}
      <div className="course-application-answer">
        <label htmlFor={`${fieldId}-answer`}>你的回答</label>
        <textarea
          id={`${fieldId}-answer`}
          rows={6}
          maxLength={COURSE_APPLICATION_ANSWER_MAX}
          disabled={disabled || sealed || unreadReceipt}
          value={displayedAnswer}
          aria-describedby={`${fieldId}-count ${fieldId}-status`}
          placeholder="用文字写下你的做法与理由…"
          onChange={(event) => {
            setDirty(true)
            setAnswer(event.target.value)
          }}
        />
        <small className="tiny muted" id={`${fieldId}-count`}>
          {displayedAnswer.length} / {COURSE_APPLICATION_ANSWER_MAX}
        </small>
      </div>
      <fieldset className="course-application-help" disabled={disabled || sealed || unreadReceipt}>
        <legend className="tiny">这次作答用过提示或帮助吗？（你自己的说明）</legend>
        {(Object.keys(HELP_USAGE_LABELS) as CourseHelpUsage[]).map((option) => (
          <label key={option} className="course-help-option">
            <input
              type="radio"
              name={`${fieldId}-help`}
              value={option}
              checked={helpUsage === option}
              onChange={() => { setDirty(true); setHelpUsage(option) }}
            />
            <span>{HELP_USAGE_LABELS[option]}</span>
          </label>
        ))}
      </fieldset>
      <div className="button-row">
        <button type="button" className="button primary" disabled={!canSubmit} onClick={() => { void submit() }}>
          <Save size={16} />
          {attempt ? '提交修改后的回答' : '提交回答'}
        </button>
        {attempt && ['failed', 'cancelled', 'queue_unavailable'].includes(state) && (
          <button
            type="button"
            className="button secondary"
            disabled={disabled || sealed}
            onClick={() => onRetryFeedback(attempt)}
          >
            <RefreshCw size={16} />
            重试这次反馈
          </button>
        )}
        {attempt && ['preparing', 'syncing'].includes(state) && (
          <button
            type="button"
            className="text-button"
            disabled={attemptQuery.isFetching}
            onClick={() => {
              void attemptQuery.refetch()
            }}
          >
            刷新反馈状态
          </button>
        )}
      </div>
      <p className="tiny muted" role="status" aria-live="polite" id={`${fieldId}-status`}>
        {sealed
          ? '本次检查已封存，回答保持只读。'
          : attempt && unchanged
            ? `回答已保存于 ${formatDate(attempt.saved_at)}。`
            : attempt
              ? '修改尚未提交；提交后会保存为新的回答，之前的回答仍然保留。'
              : overLimit
                ? `回答超出 ${COURSE_APPLICATION_ANSWER_MAX} 字上限，请精简后提交。`
                : '提交后先保存回答，再请模型给出教学反馈。'}
      </p>
      <CourseOperationNotice
        state={operationState}
        error={operationError}
        onRecover={recovery ? onRecover : () => { void attemptQuery.refetch() }}
        recoveryLabel="核对已保存的回答"
        disabled={operationState.kind === 'submitting'}
      />
      {recovery?.checked && (
        <button type="button" className="text-button" disabled={operationState.kind === 'submitting'} onClick={onReplay}>
          重试原提交
        </button>
      )}
      {attemptQuery.error && (
        <ErrorNotice
          error={courseErrorMessage(attemptQuery.error)}
          onRetry={() => {
            void attemptQuery.refetch()
          }}
        />
      )}
      {attempt && (
        <div className={`course-application-feedback ${state}`}>
          <div className="section-line">
            <strong>模型教学反馈</strong>
            {/* 没有反馈时不显示任何评分徽标；暂定与已确认必须区分。 */}
            {feedback && (
              <span className="badge">{provisional ? '暂定，未正式确认' : '已确认评分'}</span>
            )}
          </div>
          {state === 'ready' || state === 'needs_review' ? (
            <>
              {!!feedback?.feedback && <p>{feedback.feedback}</p>}
              {!!feedback?.criterion_results?.length && (
                <ul className="course-application-criteria">
                  {feedback.criterion_results.map((result, position) => (
                    <li key={position}>
                      <span className="badge">{criterionCreditLabel(result.credit)}</span>
                      <span>{typeof result.feedback === 'string' ? result.feedback : '暂无说明'}</span>
                    </li>
                  ))}
                </ul>
              )}
              <p className="tiny muted">
                {provisional
                  ? '这是模型给出的暂定反馈，等待人工复核，不作为目标已验证的依据。'
                  : '这次评分已确认。目标是否验证仍以下方“课程目标结果”为准。'}
              </p>
            </>
          ) : (
            <p role="status">{ANSWER_STATE_TEXT[state]}</p>
          )}
          {['failed', 'cancelled'].includes(state) && attempt.feedback_task && (
            <p className="tiny muted">{courseTaskErrorMessage(attempt.feedback_task)}</p>
          )}
        </div>
      )}
    </li>
  )
}

const ANSWER_STATE_TEXT: Record<string, string> = {
  not_submitted: '还没有提交回答。',
  queue_unavailable: '回答已保存，反馈还没有排队成功，可以重试反馈。',
  preparing: '回答已保存，反馈等待中。',
  syncing: '反馈已生成，正在读取。已保存的回答不会丢失。',
  ready: '已有反馈，待复核。',
  needs_review: '已有反馈，待复核。',
  failed: '这次反馈没有完成。回答已经保存，可以稍后重试反馈。',
  cancelled: '这次反馈已取消。回答已经保存，可以稍后重试反馈。',
}
