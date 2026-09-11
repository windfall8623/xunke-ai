import { useMutation, useQuery } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { useIdentityKey } from '../../app/AuthProvider'
import { ErrorNotice, Loading } from '../../components/ui'
import { ApiError } from '../../services/http'
import {
  getPracticeReviewContext,
  practiceErrorMessage,
  practiceKeys,
  reviewPracticeAttempt,
} from '../../services/practice'
import type { PracticeReviewBody, PracticeReviewContext } from '../../types/practice'

type Props = { attemptId: string; onChanged: () => Promise<void>; onClose: () => void }

export function ReviewForm({ attemptId, onChanged, onClose }: Props) {
  const identity = useIdentityKey()
  const context = useQuery({
    queryKey: practiceKeys.reviewContext(identity, attemptId),
    queryFn: ({ signal }) => getPracticeReviewContext(attemptId, signal),
    retry: false,
    staleTime: 0,
    gcTime: 0,
  })
  return (
    <section className="stack-form" aria-label="人工复核">
      <div className="button-row">
        <h3>按评分要点复核</h3>
        <button className="text-button" onClick={onClose}>
          收起复核
        </button>
      </div>
      {context.error ? (
        <ErrorNotice
          error={practiceErrorMessage(context.error)}
          onRetry={() => void context.refetch()}
        />
      ) : context.data ? (
        <ReviewFields
          key={`${context.data.current_assessment_id}:${context.data.grading_revision}`}
          context={context.data}
          onChanged={onChanged}
          onRefresh={async () => {
            await Promise.all([context.refetch(), onChanged()])
          }}
          onClose={onClose}
        />
      ) : (
        <Loading>正在读取授权的评分要点…</Loading>
      )}
    </section>
  )
}

type Credit = PracticeReviewBody['criterion_results'][number]['credit']
function ReviewFields({
  context,
  onChanged,
  onRefresh,
  onClose,
}: {
  context: PracticeReviewContext
  onChanged: () => Promise<void>
  onRefresh: () => Promise<void>
  onClose: () => void
}) {
  const [values, setValues] = useState<
    Record<string, { credit: Credit | ''; rationale: string; quote: string }>
  >({})
  const [feedback, setFeedback] = useState('')
  const [uncertain, setUncertain] = useState(false)
  const submission = useRef<{ key: string; body: PracticeReviewBody } | null>(null)
  const review = useMutation({
    mutationFn: (body: PracticeReviewBody) => {
      submission.current ??= { key: crypto.randomUUID(), body }
      return reviewPracticeAttempt(
        context.attempt_id,
        submission.current.body,
        submission.current.key,
      )
    },
    onSuccess: async () => {
      submission.current = null
      await onChanged()
      onClose()
    },
    onError: async (error) => {
      if (error instanceof ApiError && error.status >= 400 && error.status < 500) {
        submission.current = null
        setUncertain(false)
        if ([403, 404, 409, 410].includes(error.status)) await onRefresh()
      } else {
        setUncertain(true)
      }
    },
  })
  const locked = review.isPending || uncertain
  return (
    <form
      className="stack-form"
      onSubmit={(event) => {
        event.preventDefault()
        if (review.isPending) return
        if (submission.current) {
          review.mutate(submission.current.body)
          return
        }
        const results = context.criteria.map((criterion) => {
          const value = values[criterion.criterion_id]
          return {
            criterion_id: criterion.criterion_id,
            credit: value.credit as Credit,
            rationale: value.rationale.trim(),
            answer_quotes: value.quote.trim() ? [value.quote.trim()] : [],
            evidence_refs: criterion.evidence_refs,
          }
        })
        review.mutate({
          expected_assessment_id: context.current_assessment_id,
          expected_grading_revision: context.grading_revision,
          criterion_results: results,
          feedback: feedback.trim(),
          evidence_refs: [...new Set(context.criteria.flatMap((item) => item.evidence_refs))],
        })
      }}
    >
      <p className="muted">原答案：{context.answer.text}</p>
      {context.help_usage !== 'none' && (
        <p className="notice">这次作答使用过资料提示，复核后仍保留辅助作答记录。</p>
      )}
      {context.criteria.map((criterion, index) => {
        const value = values[criterion.criterion_id] || {
          credit: '',
          rationale: '',
          quote: '',
        }
        const update = (next: Partial<typeof value>) =>
          setValues((previous) => ({
            ...previous,
            [criterion.criterion_id]: { ...value, ...next },
          }))
        return (
          <fieldset className="stack-form" key={criterion.criterion_id} disabled={locked}>
            <legend>要点 {index + 1}</legend>
            <p>{criterion.reference_point}</p>
            <p className="tiny muted">权重 {Number(criterion.weight) * 100}%</p>
            <label className="field">
              <span>要点 {index + 1} 的完成程度</span>
              <select
                required
                value={value.credit}
                onChange={(event) => update({ credit: event.target.value as Credit })}
              >
                <option value="">请选择</option>
                <option value="full">完整满足</option>
                <option value="half">部分满足</option>
                <option value="none">尚未满足</option>
              </select>
            </label>
            <label className="field">
              <span>要点 {index + 1} 的判定理由</span>
              <textarea
                required
                maxLength={1000}
                value={value.rationale}
                onChange={(event) => update({ rationale: event.target.value })}
              />
            </label>
            <label className="field">
              <span>要点 {index + 1} 的答案摘录（可选，请逐字摘取）</span>
              <input
                value={value.quote}
                onChange={(event) => update({ quote: event.target.value })}
              />
            </label>
          </fieldset>
        )
      })}
      <label className="field">
        <span>复核反馈</span>
        <textarea
          required
          maxLength={2000}
          value={feedback}
          disabled={locked}
          onChange={(event) => setFeedback(event.target.value)}
        />
      </label>
      {review.error && <ErrorNotice error={practiceErrorMessage(review.error)} />}
      {uncertain && <p className="notice">上次复核结果尚未确认，重试会发送原内容。</p>}
      <button className="button primary" disabled={review.isPending} type="submit">
        {review.isPending ? '正在保存复核…' : uncertain ? '重试原复核' : '确认复核结果'}
      </button>
    </form>
  )
}
