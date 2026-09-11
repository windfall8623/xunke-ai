import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { useAuth, useIdentityKey } from '../../app/AuthProvider'
import { ErrorNotice } from '../../components/ui'
import { ApiError } from '../../services/http'
import {
  cancelPracticeTask,
  practiceErrorMessage,
  practiceKeys,
  retryPracticeGrading,
  selfReviewPracticeAttempt,
} from '../../services/practice'
import { studyKeys } from '../../services/study'
import type { PracticeAttempt, PracticeSelfReviewBody } from '../../types/practice'
import { AssessmentFeedback } from './AssessmentFeedback'
import { ReviewForm } from './ReviewForm'

export function PracticeAttemptActions({ attempt }: { attempt: PracticeAttempt }) {
  const { user } = useAuth()
  const identity = useIdentityKey()
  const client = useQueryClient()
  const [reviewOpen, setReviewOpen] = useState(false)
  const history = attempt.assessment_history || []
  const retryKey = useRef<string | null>(null)
  const onChanged = async () => {
    await Promise.all([
      client.invalidateQueries({ queryKey: practiceKeys.practice(identity, attempt.practice_id) }),
      client.invalidateQueries({ queryKey: practiceKeys.attempt(identity, attempt.attempt_id) }),
      client.invalidateQueries({
        queryKey: practiceKeys.reviewContext(identity, attempt.attempt_id),
      }),
      client.invalidateQueries({ queryKey: studyKeys.all(identity) }),
    ])
  }
  const retry = useMutation({
    mutationFn: () => {
      retryKey.current ??= crypto.randomUUID()
      return retryPracticeGrading(attempt.attempt_id, retryKey.current)
    },
    onSuccess: async () => {
      retryKey.current = null
      await onChanged()
    },
    onError: async (error) => {
      if (error instanceof ApiError && error.status >= 400 && error.status < 500) {
        retryKey.current = null
        await onChanged()
      }
    },
  })
  const cancel = useMutation({
    mutationFn: () => cancelPracticeTask(attempt.active_task_id!),
    onSuccess: onChanged,
    onError: onChanged,
  })
  const gradingActive = ['pending', 'running'].includes(attempt.grading_status || '')
  const canRetry =
    attempt.answer.type === 'short_answer' &&
    ['failed', 'cancelled'].includes(attempt.grading_status || '') &&
    attempt.current_assessment?.confirmation !== 'confirmed'
  return (
    <div className="stack-form">
      {attempt.answer.type === 'short_answer' && (
        <div className="button-row">
          {gradingActive && attempt.active_task_id && (
            <button
              className="button secondary"
              disabled={cancel.isPending}
              onClick={() => cancel.mutate()}
            >
              {cancel.isPending ? '正在取消…' : '取消本次评分'}
            </button>
          )}
          {canRetry && (
            <button
              className="button secondary"
              disabled={retry.isPending}
              onClick={() => retry.mutate()}
            >
              {retry.isPending ? '正在请求评分…' : '重试评分'}
            </button>
          )}
          {user?.role === 'evaluator' && !reviewOpen && (
            <button className="button secondary" onClick={() => setReviewOpen(true)}>
              人工复核
            </button>
          )}
        </div>
      )}
      {(retry.error || cancel.error) && (
        <ErrorNotice error={practiceErrorMessage(retry.error || cancel.error)} />
      )}
      {reviewOpen && user?.role === 'evaluator' && (
        <ReviewForm
          attemptId={attempt.attempt_id}
          onChanged={onChanged}
          onClose={() => setReviewOpen(false)}
        />
      )}
      <SelfReviewForm attempt={attempt} onChanged={onChanged} />
      {!!history.length && (
        <details className="stack-form">
          <summary>评分记录（{history.length}）</summary>
          {history.map((assessment) => (
            <section className="stack-form" key={assessment.assessment_id}>
              <p className="tiny muted">
                {assessment.source === 'human'
                  ? '人工复核'
                  : assessment.source === 'model'
                    ? '自动评分'
                    : '规则评分'}
                {assessment.assessment_id === attempt.current_assessment?.assessment_id
                  ? ' · 当前结果'
                  : ' · 历史结果'}
              </p>
              <AssessmentFeedback assessment={assessment} />
            </section>
          ))}
        </details>
      )}
    </div>
  )
}

const ratingLabel = { understood: '已经理解', needs_practice: '还需练习', unsure: '暂不确定' }
function SelfReviewForm({
  attempt,
  onChanged,
}: {
  attempt: PracticeAttempt
  onChanged: () => Promise<void>
}) {
  const [rating, setRating] = useState<PracticeSelfReviewBody['self_rating']>('unsure')
  const selfReviews = attempt.self_reviews || []
  const [notes, setNotes] = useState('')
  const [uncertain, setUncertain] = useState(false)
  const pending = useRef<{ key: string; body: PracticeSelfReviewBody } | null>(null)
  const save = useMutation({
    mutationFn: () => {
      pending.current ??= { key: crypto.randomUUID(), body: { self_rating: rating, notes } }
      return selfReviewPracticeAttempt(
        attempt.attempt_id,
        pending.current.body,
        pending.current.key,
      )
    },
    onSuccess: async () => {
      pending.current = null
      setNotes('')
      setUncertain(false)
      await onChanged()
    },
    onError: async (error) => {
      if (error instanceof ApiError && error.status >= 400 && error.status < 500) {
        pending.current = null
        setUncertain(false)
        if ([403, 404, 409, 410].includes(error.status)) await onChanged()
      } else setUncertain(true)
    },
  })
  return (
    <details className="stack-form">
      <summary>自我核对{selfReviews.length ? `（${selfReviews.length}）` : ''}</summary>
      <p className="tiny muted">记录自己的理解程度和疑问，自评不会改变题目评分。</p>
      {selfReviews.map((review) => (
        <p key={review.annotation_id}>
          {ratingLabel[review.self_rating]}
          {review.notes ? `：${review.notes}` : ''}
        </p>
      ))}
      <form
        className="stack-form"
        onSubmit={(event) => {
          event.preventDefault()
          if (!save.isPending) save.mutate()
        }}
      >
        <label className="field">
          <span>我的理解程度</span>
          <select
            value={rating}
            disabled={save.isPending || uncertain}
            onChange={(event) =>
              setRating(event.target.value as PracticeSelfReviewBody['self_rating'])
            }
          >
            {Object.entries(ratingLabel).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>自评笔记</span>
          <textarea
            value={notes}
            maxLength={1000}
            disabled={save.isPending || uncertain}
            onChange={(event) => setNotes(event.target.value)}
          />
        </label>
        {save.error && <ErrorNotice error={practiceErrorMessage(save.error)} />}
        {uncertain && <p className="notice">保存结果尚未确认，重试会使用原自评内容。</p>}
        {save.isSuccess && <p role="status">自评已保存</p>}
        <button className="button secondary" disabled={save.isPending} type="submit">
          {save.isPending ? '正在保存…' : uncertain ? '重试原自评' : '保存自评'}
        </button>
      </form>
    </details>
  )
}
