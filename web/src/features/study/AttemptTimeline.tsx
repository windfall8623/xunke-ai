import { Link } from 'react-router-dom'
import { EmptyState } from '../../components/ui'
import type { StudyHistory } from '../../types/study'

export const projectionLabels: Record<StudyHistory['projection_status'], string> = {
  not_ready: '尚未完成作答',
  pending: '学习记录已保存，统计正在更新',
  pending_assessments: '作答已保存，等待评分确认',
  current: '学习统计已更新',
  failed: '学习记录已保存，统计更新暂未完成',
}

export function studyDate(value?: string | null, timezone?: string) {
  if (!value) return '尚未安排'
  const date = new Date(value)
  if (!Number.isFinite(date.getTime())) return '时间暂不可用'
  return date.toLocaleString('zh-CN', {
    timeZone: timezone,
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function AttemptTimeline({ items }: { items: StudyHistory[] }) {
  if (!items.length)
    return (
      <EmptyState title="还没有学习记录">
        完成一次练习后，这里会记录作答、评分确认和下次复习安排。
      </EmptyState>
    )
  return (
    <ol className="study-record-list" aria-label="学习时间线">
      {items.map((item) => (
        <li className="card stack-form" key={item.history_id}>
          {item.source_status === 'revoked' ? (
            <p className="notice">资料已失效，相关学习内容已隐藏。</p>
          ) : (
            <>
              <div className="button-row">
                <span className="badge">
                  {item.origin_kind === 'quiz' ? '客观题练习' : '综合练习'}
                </span>
                <time dateTime={item.occurred_at}>{studyDate(item.occurred_at)}</time>
              </div>
              <h3>
                <Link
                  to={
                    item.origin_kind === 'quiz'
                      ? `/quizzes/${encodeURIComponent(item.origin_id)}`
                      : `/practice/${encodeURIComponent(item.origin_id)}`
                  }
                >
                  {item.title}
                </Link>
              </h3>
              <p className="muted">
                已作答 {item.attempted_count}/{item.question_count} 题 · 已确认评分{' '}
                {item.confirmed_count} 题
                {item.pending_count > 0 ? ` · ${item.pending_count} 题待确认` : ''}
              </p>
              <p role="status">
                {item.origin_kind === 'quiz' &&
                item.status === 'settled' &&
                item.projection_status === 'not_ready'
                  ? '已完成并结算'
                  : projectionLabels[item.projection_status]}
              </p>
              {item.concepts.length > 0 && (
                <div className="button-row">
                  {item.concepts.map((concept) => (
                    <Link
                      className="text-button"
                      key={concept.concept_id}
                      to={`/study/concepts/${encodeURIComponent(concept.concept_id)}`}
                    >
                      {concept.title}
                    </Link>
                  ))}
                </div>
              )}
              {item.next_reviews.length > 0 && (
                <p className="tiny muted">
                  下次复习：{studyDate(item.next_reviews[0].due_at, item.next_reviews[0].timezone)}
                  {item.next_reviews[0].paused ? '（已暂停）' : ''}
                </p>
              )}
            </>
          )}
        </li>
      ))}
    </ol>
  )
}
