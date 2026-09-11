import { useMutation } from '@tanstack/react-query'
import { CheckCircle2, Send } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Dialog } from '../../components/Dialog'
import { ErrorNotice } from '../../components/ui'
import { api } from '../../services/api'
import type { Feedback } from '../../types/api'

export function FeedbackForm({
  quizId,
  questionId,
  onClose,
}: {
  quizId: string
  questionId: string
  onClose: () => void
}) {
  const [reason, setReason] = useState<Feedback['reason']>('incorrect_answer')
  const [comment, setComment] = useState('')
  const [share, setShare] = useState(false)
  const mutation = useMutation({
    mutationFn: () =>
      api.feedback(quizId, {
        question_id: questionId,
        reason,
        comment: comment.trim(),
        allow_evaluation_use: share,
      }),
  })
  function submit(event: FormEvent) {
    event.preventDefault()
    if (!mutation.isPending) mutation.mutate()
  }
  return (
    <Dialog title="反馈题目问题" onClose={onClose}>
      {mutation.isSuccess ? (
        <div className="feedback-success" role="status">
          <CheckCircle2 size={32} />
          <h3>反馈已收到，感谢帮助我们改进。</h3>
          <p>反馈会进入复核流程，原始题目与学习记录保持可回看。</p>
          <button className="button secondary" onClick={onClose}>
            完成
          </button>
        </div>
      ) : (
        <form className="stack-form" onSubmit={submit}>
          <p className="muted tiny">告诉我们你发现的问题。提交前可以先查看原文依据。</p>
          <label>
            问题类型
            <select
              value={reason}
              onChange={(event) => setReason(event.target.value as Feedback['reason'])}
            >
              <option value="incorrect_answer">答案有误</option>
              <option value="unsupported_explanation">解析无依据</option>
              <option value="citation_mismatch">引用不符</option>
              <option value="duplicate">题目重复</option>
              <option value="other">其他</option>
            </select>
          </label>
          <label>
            补充说明
            <textarea
              value={comment}
              onChange={(event) => setComment(event.target.value)}
              maxLength={2000}
              rows={4}
              placeholder="描述问题，必要时注明页码或段落。"
            />
          </label>
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={share}
              onChange={(event) => setShare(event.target.checked)}
            />
            <span>
              允许用于后续评测<small>相关资料仍需经授权核查与人工复核，才会纳入共享评测。</small>
            </span>
          </label>
          <ErrorNotice error={mutation.error} />
          <button type="submit" className="button primary" disabled={mutation.isPending}>
            <Send size={16} />
            {mutation.isPending ? '正在提交…' : '提交反馈'}
          </button>
        </form>
      )}
    </Dialog>
  )
}
