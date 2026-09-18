import { courseErrorMessage } from '../../services/courses'
import type { CourseOperationState } from './courseActionState'

export function CourseOperationNotice({
  state,
  error,
  confirmedMessage,
  onRecover,
  recoveryLabel = '核对保存结果',
  disabled = false,
}: {
  state: CourseOperationState
  error?: unknown
  confirmedMessage?: string
  onRecover?: () => void
  recoveryLabel?: string
  disabled?: boolean
}) {
  if (state.kind === 'idle' || (state.kind === 'confirmed' && !confirmedMessage)) return null
  const message = state.kind === 'submitting'
    ? '正在提交，请稍候…'
    : state.kind === 'unconfirmed'
      ? '提交结果尚未确认。请先核对保存结果；重试会沿用这次提交的原始内容。'
      : state.kind === 'failed'
        ? courseErrorMessage(error)
        : confirmedMessage
  return (
    <div className={`course-operation-notice notice ${state.kind}`} role="status" aria-live="polite">
      <p>{message}</p>
      {onRecover && ['unconfirmed', 'failed'].includes(state.kind) && (
        <button type="button" className="text-button" disabled={disabled} onClick={onRecover}>
          {recoveryLabel}
        </button>
      )}
    </div>
  )
}
