import { useState } from 'react'
import { Link } from 'react-router-dom'
import { EmptyState } from '../../components/ui'
import type { StudyReview, StudyReviewUpdate } from '../../types/study'
import { studyDate } from './AttemptTimeline'

const statusLabels: Record<StudyReview['status'], string> = {
  scheduled: '待复习',
  claimed: '准备中',
  running: '进行中',
  completed: '已完成',
  failed: '上次生成失败',
  cancelled: '已取消',
}
export function ReviewQueue({
  items,
  pending = false,
  onStart,
  onUpdate,
}: {
  items: StudyReview[]
  pending?: boolean
  onStart?: (review: StudyReview) => void
  onUpdate?: (review: StudyReview, action: StudyReviewUpdate['action'], dueAt?: string) => void
}) {
  if (!items.length)
    return (
      <EmptyState title="当前没有待复习项目">
        完成有概念关联的练习后，系统会根据已确认的学习记录安排复习。
      </EmptyState>
    )
  return (
    <ul className="study-record-list" aria-label="复习队列">
      {items.map((review) => (
        <ReviewItem
          key={review.review_task_id}
          review={review}
          pending={pending}
          onStart={onStart}
          onUpdate={onUpdate}
        />
      ))}
    </ul>
  )
}

function ReviewItem({
  review,
  pending,
  onStart,
  onUpdate,
}: {
  review: StudyReview
  pending: boolean
  onStart?: (review: StudyReview) => void
  onUpdate?: (review: StudyReview, action: StudyReviewUpdate['action'], dueAt?: string) => void
}) {
  const [rescheduling, setRescheduling] = useState(false)
  const [due, setDue] = useState('')
  const runnable =
    review.is_current &&
    !review.paused &&
    ['scheduled', 'failed', 'cancelled'].includes(review.status)
  const active = ['claimed', 'running'].includes(review.status)
  if (review.source_status !== 'active')
    return <li className="card notice">资料已失效，这项复习已隐藏。</li>
  return (
    <li className="card stack-form" id={`review-${review.review_task_id}`}>
      <div className="button-row">
        <span className="badge">{review.paused ? '已暂停' : statusLabels[review.status]}</span>
        <span className="tiny muted">
          {review.space_title} · 范围版本 {review.scope_revision}
        </span>
      </div>
      <h3>
        <Link to={`/study/concepts/${encodeURIComponent(review.concept_id)}`}>
          {review.concept_title}
        </Link>
      </h3>
      <p className="muted">
        复习时间：{studyDate(review.due_at, review.timezone)}（{review.timezone}）
      </p>
      {review.override_due_at && (
        <p className="tiny muted">
          已手动改期；原计划：{studyDate(review.rule_due_at, review.timezone)}
        </p>
      )}
      <div className="button-row">
        {onStart && (
          <button
            className="button primary"
            disabled={pending || !runnable}
            onClick={() => onStart(review)}
          >
            开始复习
          </button>
        )}
        {active && review.task_id && (
          <Link
            className="button secondary"
            to={
              review.origin_kind === 'practice'
                ? `/practice/tasks/${encodeURIComponent(review.task_id)}`
                : `/tasks/${encodeURIComponent(review.task_id)}?returnTo=/study/reviews`
            }
          >
            查看任务
          </Link>
        )}
        {onUpdate && review.is_current && (
          <>
            <button
              className="button secondary"
              disabled={pending || active}
              onClick={() => onUpdate(review, review.paused ? 'resume' : 'pause')}
            >
              {review.paused ? '恢复复习' : '暂停复习'}
            </button>
            <button
              className="text-button"
              disabled={pending || active}
              onClick={() => setRescheduling(!rescheduling)}
            >
              调整日期
            </button>
          </>
        )}
      </div>
      {rescheduling && onUpdate && (
        <form
          className="stack-form"
          onSubmit={(event) => {
            event.preventDefault()
            const date = new Date(due)
            if (Number.isFinite(date.getTime())) {
              onUpdate(review, 'reschedule', date.toISOString())
              setRescheduling(false)
            }
          }}
        >
          <label>
            复习日期（浏览器本地时间）
            <input
              type="datetime-local"
              required
              value={due}
              disabled={pending}
              onChange={(event) => setDue(event.target.value)}
            />
          </label>
          <button className="button secondary" type="submit" disabled={pending || !due}>
            保存日期
          </button>
        </form>
      )}
    </li>
  )
}
