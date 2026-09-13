import { ArrowRight } from 'lucide-react'
import { formatDate } from '../../components/ui'
import type { CourseCriterionOutcome } from '../../types/course'
import {
  EVIDENCE_TYPE_LABELS,
  OUTCOME_STATUS_LABELS,
  evidenceOriginLabel,
  type AssessmentGoal,
} from './courseOutcomeFacts'

/**
 * 按目标展示只读结果。
 *
 * 状态完全来自服务端投影：阅读、保存回答、暂定反馈与自评都不会显示为已验证。
 */
export function CourseGoalList({
  goals,
  showCoverage = false,
  onLesson,
}: {
  goals: AssessmentGoal[]
  /** 是否标注该目标是否在本次检查的覆盖范围内。 */
  showCoverage?: boolean
  onLesson?: (lessonId: string) => void
}) {
  if (!goals.length)
    return (
      <p className="notice" role="status">
        这门课程还没有可检验的学习目标。补充目标或重新生成纲要后可以开始结业检查。
      </p>
    )
  return (
    <ul className="course-goal-list">
      {goals.map((goal) => (
        <li key={goal.courseCriterionId} className={`course-goal ${goal.status}`}>
          <div className="section-line">
            <strong>{goal.title}</strong>
            <span className={`course-goal-status ${goal.status}`}>
              {OUTCOME_STATUS_LABELS[goal.status]}
            </span>
            {goal.definition && (
              <span className="badge">{EVIDENCE_TYPE_LABELS[goal.definition.evidence_type]}类目标</span>
            )}
            {showCoverage && (
              <span className="tiny muted">{goal.covered ? '本次检查已覆盖' : '本次检查未覆盖'}</span>
            )}
          </div>
          <p className="tiny muted">{goal.reason}</p>
          {!!goal.definition?.expectation && (
            <p className="tiny muted">达成标准：{goal.definition.expectation}</p>
          )}
          {goal.evidenceCount > 0 && (
            <p className="tiny muted">已保留 {goal.evidenceCount} 条学习记录。</p>
          )}
          {!!goal.definition?.lesson_ids?.length && onLesson && (
            <div className="button-row">
              {goal.definition.lesson_ids.map((lessonId, index) => (
                <button
                  type="button"
                  className="text-button"
                  key={lessonId}
                  onClick={() => onLesson(lessonId)}
                >
                  回到相关课时 {goal.definition!.lesson_ids!.length > 1 ? index + 1 : ''}
                  <ArrowRight size={14} />
                </button>
              ))}
            </div>
          )}
        </li>
      ))}
    </ul>
  )
}

export function CourseGoalEvidence({ outcome }: { outcome: CourseCriterionOutcome }) {
  const refs = outcome.evidence_refs || []
  if (!refs.length) return null
  return (
    <ul className="course-goal-evidence">
      {refs.map((ref, index) => (
        <li key={`${ref.origin_id}:${ref.attempt_id || index}`}>
          <span className="badge">{evidenceOriginLabel(ref.origin_kind)}</span>
          <span className="tiny muted">{formatDate(ref.occurred_at)}</span>
        </li>
      ))}
    </ul>
  )
}
