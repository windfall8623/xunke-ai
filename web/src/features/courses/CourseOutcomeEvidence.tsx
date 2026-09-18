import { Link } from 'react-router-dom'
import { Dialog } from '../../components/Dialog'
import { formatDate } from '../../components/ui'
import { evidenceOriginLabel } from './courseOutcomeFacts'
import type { CourseCriterion, CourseOutcomeSummary } from '../../types/course'

function EvidenceRow({
  originKind,
  originId,
  occurredAt,
}: {
  originKind: string
  originId: string
  occurredAt: string
}) {
  const label = `${evidenceOriginLabel(originKind)} · ${formatDate(occurredAt)}`
  if (originKind === 'quiz' && originId) {
    return (
      <li>
        <Link className="text-link" to={`/quizzes/${encodeURIComponent(originId)}`}>
          {label}
        </Link>
      </li>
    )
  }
  return <li>{label}</li>
}

/**
 * 目标证据抽屉：解释每个目标状态由哪些记录支持。
 * 证据逐次授权读取；这里只引用身份与时间，不复制答案正文。
 */
export function CourseOutcomeEvidence({
  outcomes,
  definitions = [],
  onClose,
}: {
  outcomes: CourseOutcomeSummary
  definitions?: CourseCriterion[]
  onClose: () => void
}) {
  const byId = new Map(definitions.map((item) => [item.course_criterion_id, item]))
  return (
    <Dialog title="目标与证据" onClose={onClose} className="course-outcome-evidence">
      <ol className="course-outcome-evidence-list">
        {(outcomes.criteria || []).map((outcome) => {
          const refs = outcome.evidence_refs || []
          return (
            <li key={outcome.course_criterion_id} className="course-outcome-evidence-goal">
              <strong>{outcome.title}</strong>
              <p className="tiny muted">
                {byId.get(outcome.course_criterion_id)?.expectation || outcome.reason}
              </p>
              {refs.length ? (
                <ul>
                  {refs.map((ref, index) => (
                    <EvidenceRow
                      key={`${ref.origin_kind}:${ref.origin_id}:${index}`}
                      originKind={ref.origin_kind}
                      originId={ref.origin_id}
                      occurredAt={ref.occurred_at}
                    />
                  ))}
                </ul>
              ) : (
                <p className="tiny muted">尚无已结算且明确对应本目标的学习证据。</p>
              )}
            </li>
          )
        })}
      </ol>
    </Dialog>
  )
}
