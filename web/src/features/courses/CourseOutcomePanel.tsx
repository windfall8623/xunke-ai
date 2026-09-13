import { useState } from 'react'
import {
  OUTCOME_STATUS_LABELS,
  countOutcomes,
} from './courseOutcomeFacts'
import { CourseOutcomeEvidence } from './CourseOutcomeEvidence'
import type { CourseCriterion, CourseOutcomeSummary } from '../../types/course'

/**
 * 证据可解释的目标仪表盘（B01）。
 *
 * 展示"已验证 n 项 / 共 m 项"等目标计数与逐项目标状态、原因和证据入口；
 * 不计算掌握率百分比，也不用一条识别题正确推断应用或创造目标。
 */
export function CourseOutcomePanel({
  outcomes,
  definitions = [],
  coverage = null,
}: {
  outcomes: CourseOutcomeSummary | null | undefined
  definitions?: CourseCriterion[]
  /** 当前结业检查覆盖的目标 ID；null 表示没有进行中的检查，不显示覆盖标记。 */
  coverage?: string[] | null
}) {
  const [evidenceOpen, setEvidenceOpen] = useState(false)
  if (!outcomes || !outcomes.criteria?.length) {
    return (
      <div className="course-outcome-panel">
        <p className="tiny muted">本课程尚无可验证目标记录；历史课程不会自动补建目标。</p>
      </div>
    )
  }
  const tally = countOutcomes(outcomes.criteria.map((item) => item.status))
  const covered = coverage ? new Set(coverage) : null
  return (
    <div className="course-outcome-panel">
      <p className="course-outcome-tally">
        已验证 {tally.verified} 项 / 共 {outcomes.criteria.length} 项
        {tally.needs_practice > 0 && ` · 需补学 ${tally.needs_practice} 项`}
        {tally.stale > 0 && ` · 待重新验证 ${tally.stale} 项`}
      </p>
      <ul className="course-outcome-list">
        {outcomes.criteria.map((outcome) => (
          <li key={outcome.course_criterion_id} className={`course-outcome-row status-${outcome.status}`}>
            <div>
              <strong>{outcome.title}</strong>
              <span className={`badge outcome-badge outcome-${outcome.status}`}>
                {OUTCOME_STATUS_LABELS[outcome.status]}
              </span>
              {covered && (
                <span className="tiny muted">
                  {covered.has(outcome.course_criterion_id) ? '本次检查已覆盖' : '本次检查未覆盖'}
                </span>
              )}
              <p className="tiny muted">{outcome.reason}</p>
            </div>
            <button
              type="button"
              className="button secondary"
              onClick={() => setEvidenceOpen(true)}
            >
              查看证据
            </button>
          </li>
        ))}
      </ul>
      {evidenceOpen && (
        <CourseOutcomeEvidence
          outcomes={outcomes}
          definitions={definitions}
          onClose={() => setEvidenceOpen(false)}
        />
      )}
    </div>
  )
}
