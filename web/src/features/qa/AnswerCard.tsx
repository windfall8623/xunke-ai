import { useEffect, useRef, useState } from 'react'
import { BookOpenCheck, Copy, Quote, ThumbsDown, ThumbsUp } from 'lucide-react'
import { Dialog } from '../../components/Dialog'
import { ErrorNotice } from '../../components/ui'
import { qaApi } from '../../services/qa'
import type { QaAnswer, QaFeedback } from '../../types/qa'
import { sourceError } from './useQaSession'

const outcomes: Record<QaAnswer['answer_status'], string> = {
  answered: '回答完成',
  partial: '部分回答',
  needs_clarification: '需要澄清',
  insufficient_evidence: '资料不足',
  conflicting_sources: '资料存在冲突',
}

export function AnswerCard({
  answer,
  onEvidence,
  onUnavailable,
  onPractice,
}: {
  answer: QaAnswer
  onEvidence: (answerId: string, evidenceId: string) => void
  onUnavailable: () => void
  onPractice?: () => void
}) {
  const [copied, setCopied] = useState(false)
  const [copyError, setCopyError] = useState<unknown>(null)
  const [feedback, setFeedback] = useState<QaFeedback['rating'] | null>(null)
  const [saved, setSaved] = useState(false)
  async function copy() {
    setCopyError(null)
    try {
      if (!navigator.clipboard) throw new Error('当前浏览器无法复制，请选中回答文字复制。')
      await navigator.clipboard.writeText(answer.blocks.map((block) => block.text).join('\n\n'))
      setCopied(true)
    } catch (error) {
      setCopyError(error)
    }
  }
  return (
    <div className="qa-answer">
      <div className="qa-answer-heading">
        <span className={`badge qa-outcome qa-outcome-${answer.answer_status}`}>
          {outcomes[answer.answer_status]}
        </span>
        <span className="muted tiny">范围版本 {answer.scope_revision}</span>
      </div>
      {answer.blocks.map((block) => (
        <section className={`qa-answer-block qa-block-${block.kind}`} key={block.block_id}>
          <p>{block.text}</p>
          {!!block.citation_refs?.length && (
            <div className="qa-citations" aria-label="本段引用">
              {(block.citation_refs || []).map((ref) => {
                const index = answer.evidence.findIndex((item) => item.evidence_id === ref)
                const evidence = answer.evidence[index]
                return evidence ? (
                  <button
                    key={ref}
                    className="qa-citation"
                    type="button"
                    aria-label={`查看引用 ${index + 1}：${evidence.title}`}
                    onClick={(event) => {
                      // Pointer activation does not focus buttons in every browser.
                      event.currentTarget.focus({ preventScroll: true })
                      onEvidence(answer.answer_id, ref)
                    }}
                  >
                    <Quote size={13} />
                    <span>
                      {index + 1}. {evidence.title}
                    </span>
                  </button>
                ) : null
              })}
            </div>
          )}
        </section>
      ))}
      <div className="qa-answer-actions">
        {onPractice && (
          <button className="text-button" type="button" onClick={onPractice}>
            <BookOpenCheck size={15} />
            练一练
          </button>
        )}
        <button
          className="text-button"
          type="button"
          onClick={() => {
            void copy()
          }}
        >
          <Copy size={15} />
          {copied ? '已复制' : '复制回答'}
        </button>
        {saved ? (
          <span className="tiny" role="status">
            反馈已保存
          </span>
        ) : (
          <>
            <button className="text-button" type="button" onClick={() => setFeedback('helpful')}>
              <ThumbsUp size={15} />
              有帮助
            </button>
            <button className="text-button" type="button" onClick={() => setFeedback('unhelpful')}>
              <ThumbsDown size={15} />
              有待改进
            </button>
          </>
        )}
      </div>
      <ErrorNotice error={copyError} />
      {feedback && (
        <FeedbackDialog
          answerId={answer.answer_id}
          rating={feedback}
          onClose={() => setFeedback(null)}
          onSaved={() => {
            setSaved(true)
            setFeedback(null)
          }}
          onUnavailable={onUnavailable}
        />
      )}
    </div>
  )
}

function FeedbackDialog({
  answerId,
  rating,
  onClose,
  onSaved,
  onUnavailable,
}: {
  answerId: string
  rating: QaFeedback['rating']
  onClose: () => void
  onSaved: () => void
  onUnavailable: () => void
}) {
  const [reason, setReason] = useState<NonNullable<QaFeedback['reason']> | ''>('')
  const [comment, setComment] = useState('')
  const [consent, setConsent] = useState(false)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const request = useRef<AbortController | null>(null)
  useEffect(() => () => request.current?.abort(), [])
  async function submit() {
    if (pending) return
    setPending(true)
    setError(null)
    const controller = new AbortController()
    request.current = controller
    try {
      await qaApi.feedback(
        answerId,
        {
          rating,
          ...(reason ? { reason } : {}),
          comment: comment.trim(),
          evaluation_consent: consent,
        },
        controller.signal,
      )
      if (!controller.signal.aborted) onSaved()
    } catch (cause) {
      if (controller.signal.aborted) return
      if (sourceError(cause)) onUnavailable()
      else setError(cause)
    } finally {
      if (!controller.signal.aborted) setPending(false)
    }
  }
  return (
    <Dialog title="回答反馈" onClose={onClose}>
      <form
        className="qa-feedback-form"
        onSubmit={(event) => {
          event.preventDefault()
          void submit()
        }}
      >
        <p>{rating === 'helpful' ? '这份回答对你有帮助。' : '告诉我们哪里需要改进。'}</p>
        {rating === 'unhelpful' && (
          <label>
            问题类型（选填）
            <select
              value={reason}
              disabled={pending}
              onChange={(event) => setReason(event.target.value as typeof reason)}
            >
              <option value="">请选择</option>
              <option value="incorrect">内容不正确</option>
              <option value="unsupported">缺乏资料支持</option>
              <option value="incomplete">回答不完整</option>
              <option value="other">其他</option>
            </select>
          </label>
        )}
        <label>
          补充说明（选填）
          <textarea
            rows={3}
            maxLength={2000}
            value={comment}
            disabled={pending}
            onChange={(event) => setComment(event.target.value)}
          />
        </label>
        <label className="checkbox-row">
          <input
            type="checkbox"
            checked={consent}
            disabled={pending}
            onChange={(event) => setConsent(event.target.checked)}
          />
          <span>
            允许将本轮问答用于评测改进
            <small>可选，包含本轮问题、回答与来源；不勾选也可提交反馈。</small>
          </span>
        </label>
        <ErrorNotice error={error} />
        <div className="button-row">
          <button className="button secondary" type="button" onClick={onClose}>
            返回
          </button>
          <button className="button primary" type="submit" disabled={pending}>
            {pending ? '正在提交…' : '提交反馈'}
          </button>
        </div>
      </form>
    </Dialog>
  )
}
