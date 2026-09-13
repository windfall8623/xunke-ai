import { GraduationCap } from 'lucide-react'
import { useMemo } from 'react'
import { ErrorNotice, Loading, formatDate } from '../../components/ui'
import { courseErrorMessage } from '../../services/courses'
import type { CourseView } from '../../types/course'
import { CourseAssessmentRun } from './CourseAssessmentRun'
import { CourseGoalList } from './CourseGoalList'
import { CourseOperationNotice } from './CourseOperationNotice'
import {
  assessmentFlowState,
  assessmentGoals,
  outcomeTally,
} from './courseOutcomeFacts'
import { useCourseApplications } from './useCourseApplications'
import { useCourseAssessment } from './useCourseAssessment'

/**
 * 结业检查与课程目标结果。
 *
 * `completed` 只表示一次检查流程已封存；每个目标是否验证由服务端只读投影决定，
 * 未覆盖的目标始终显式可见。
 */
export function CourseAssessmentPanel({
  course,
  enabled = true,
  onLesson,
  onEvidence,
  onUnavailable,
}: {
  course: CourseView
  enabled?: boolean
  onLesson?: (lessonId: string) => void
  onEvidence?: (sourceRef: string) => void
  onUnavailable?: () => void
}) {
  const controller = useCourseAssessment(course, enabled, onUnavailable)
  const assessment = controller.assessment
  const applications = useCourseApplications(
    course.course_id,
    assessment?.course_assessment_id || null,
    onUnavailable,
  )
  const goals = useMemo(
    () => assessmentGoals(assessment, controller.outcomes, course.course_criteria || []),
    [assessment, controller.outcomes, course.course_criteria],
  )
  const tally = useMemo(() => outcomeTally(controller.outcomes?.criteria || []), [controller.outcomes])
  const state = assessmentFlowState(assessment)
  const canStart = !assessment || ['completed', 'failed', 'cancelled'].includes(state)
  const pending = controller.operation.pending !== null
  const locked = pending || controller.recovery || applications.locked
  if (controller.inaccessible || applications.inaccessible) return null
  return (
    <section id="course-assessment" className="card course-assessment" aria-label="结业检查与课程目标">
      <div className="section-line">
        <h3>
          <GraduationCap size={18} />
          结业检查与课程目标
        </h3>
        {!!tally.total && (
          <span className="badge">
            已验证 {tally.verified} / {tally.total}
          </span>
        )}
      </div>
      <p className="muted">
        用一组客观题和文本应用任务检验课程目标。完成一次检查不等于全部目标已验证；每个目标的状态都按已保存的学习证据显示。
      </p>
      {controller.outcomesQuery.error ? (
        <ErrorNotice
          error={courseErrorMessage(controller.outcomesQuery.error)}
          onRetry={() => {
            void controller.outcomesQuery.refetch()
          }}
        />
      ) : controller.outcomesQuery.isPending ? (
        <Loading>正在读取课程目标结果…</Loading>
      ) : (
        <>
          {!!tally.total && (
            <ul className="course-outcome-tally" role="list">
              <li>
                已验证 <strong>{tally.verified}</strong>
              </li>
              <li>
                需补学 <strong>{tally.needsPractice}</strong>
              </li>
              <li>
                待验证 <strong>{tally.unverified}</strong>
              </li>
              {tally.stale > 0 && (
                <li>
                  证据已过期 <strong>{tally.stale}</strong>
                </li>
              )}
            </ul>
          )}
          <CourseGoalList goals={goals} showCoverage={!!assessment} onLesson={onLesson} />
        </>
      )}
      {controller.listQuery.error && (
        <ErrorNotice
          error={courseErrorMessage(controller.listQuery.error)}
          onRetry={() => {
            void controller.listQuery.refetch()
          }}
        />
      )}
      {controller.detailQuery.error && (
        <ErrorNotice error={courseErrorMessage(controller.detailQuery.error)} onRetry={controller.refresh} />
      )}
      {canStart && (
        <div className="course-assessment-start">
          <div className="button-row">
            <button
              type="button"
              className="button primary"
              disabled={locked || controller.listQuery.isPending || !!controller.listQuery.error ||
                !!controller.detailQuery.error || !controller.outcomes?.criteria?.length}
              onClick={() => {
                void controller.start([])
              }}
            >
              {pending && controller.operation.pending === 'assessment'
                ? '正在提交…'
                : assessment
                  ? '开始下一组检查'
                  : '开始结业检查'}
            </button>
          </div>
          <p className="tiny muted">
            每组检查限 3–6 道客观题和 1–2 个应用任务；范围之外的目标会明确列出，不会声称一次覆盖整门课程。
          </p>
        </div>
      )}
      <CourseOperationNotice
        state={
          controller.operation.state.kind !== 'idle' &&
          controller.operation.state.operation === 'assessment'
            ? controller.operation.state
            : { kind: 'idle' }
        }
        error={controller.operation.error}
        onRecover={controller.recovery ? controller.recover : controller.refresh}
        recoveryLabel="核对已创建的检查"
        disabled={pending}
      />
      {!assessment && controller.recoveryChecked && (
        <button type="button" className="text-button" disabled={pending} onClick={controller.retryOriginal}>
          重试原检查请求
        </button>
      )}
      {assessment && (
        <>
          <div className="section-line course-assessment-current">
            <h4>本次检查</h4>
            <span className="badge">{FLOW_LABELS[state] || '正在读取'}</span>
            {controller.history.length > 1 && (
              <label className="course-assessment-picker">
                <span className="sr-only">选择要查看的检查</span>
                <select
                  value={assessment.course_assessment_id}
                  disabled={locked}
                  onChange={(event) => controller.select(event.target.value)}
                >
                  {controller.history.map((item, index) => (
                    <option key={item.course_assessment_id} value={item.course_assessment_id}>
                      第 {controller.history.length - index} 组 · {FLOW_LABELS[assessmentFlowState(item)]}
                    </option>
                  ))}
                </select>
              </label>
            )}
          </div>
          <CourseAssessmentRun
            key={assessment.course_assessment_id}
            courseId={course.course_id}
            controller={controller}
            applications={applications}
            goals={goals}
            onLesson={onLesson}
            onEvidence={onEvidence}
            onUnavailable={onUnavailable}
          />
        </>
      )}
      {!assessment && !controller.listQuery.isPending && (
        <p className="tiny muted">还没有开始过结业检查。上方目标状态依据已结算且明确关联课程目标的检查证据显示。</p>
      )}
      {!!controller.outcomes && (
        <p className="tiny muted">
          目标版本 {controller.outcomes.criteria_revision}
          {course.updated_at ? ` · 课程更新于 ${formatDate(course.updated_at)}` : ''}
        </p>
      )}
    </section>
  )
}

const FLOW_LABELS: Record<string, string> = {
  none: '尚未开始',
  generating: '题目准备中',
  ready: '待作答',
  in_progress: '进行中',
  ready_to_complete: '可封存',
  completed: '流程已封存',
  failed: '未准备成功',
  cancelled: '已取消',
}
