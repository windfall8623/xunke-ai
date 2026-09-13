import { ArrowRight, ClipboardCheck, Lock, Sparkles } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Loading } from '../../components/ui'
import { courseTaskErrorMessage, courseTaskPending } from '../../services/courses'
import { coursePath, withCourseReturn } from '../../services/courseNavigation'
import type { CourseApplicationTaskView, CourseHelpUsage } from '../../types/course'
import { CourseApplicationTask } from './CourseApplicationTask'
import { CourseGoalList } from './CourseGoalList'
import { CourseOperationNotice } from './CourseOperationNotice'
import {
  HELP_USAGE_LABELS,
  assessmentFlowState,
  uncoveredGoals,
  type AssessmentGoal,
} from './courseOutcomeFacts'
import type { CourseAssessmentController } from './useCourseAssessment'
import type { CourseApplicationController } from './useCourseApplications'

const FLOW_TEXT: Record<string, string> = {
  generating: '正在准备本次检查的题目。可以离开此页，稍后回来继续。',
  ready: '题目已准备好，进入作答后回来封存本次检查。',
  in_progress: '本次检查已开始。完成并确认结算后，可以封存这次检查。',
  ready_to_complete: '客观题已确认结算，可以封存本次检查。',
  completed: '本次检查流程已完成。这只表示这一组检查已封存，不代表全部目标已验证。',
  failed: '本次检查没有准备成功，可以重新开始一组检查。',
  cancelled: '本次检查已取消，可以重新开始一组检查。',
}

/** 一次结业检查会话：作答入口、封存、未覆盖目标与文本应用任务。 */
export function CourseAssessmentRun({
  courseId,
  controller,
  applications,
  goals,
  onLesson,
  onEvidence,
  onUnavailable,
}: {
  courseId: string
  controller: CourseAssessmentController
  applications: CourseApplicationController
  goals: AssessmentGoal[]
  onLesson?: (lessonId: string) => void
  onEvidence?: (sourceRef: string) => void
  onUnavailable?: () => void
}) {
  const [helpUsage, setHelpUsage] = useState<CourseHelpUsage>('unknown')
  const assessment = controller.assessment
  if (!assessment) return null
  const state = assessmentFlowState(assessment)
  const pending = controller.operation.pending !== null || applications.operation.pending !== null
  const locked = pending || controller.recovery || applications.locked
  const sealed = state === 'completed'
  const uncovered = uncoveredGoals(goals)
  const quizTaskPending = courseTaskPending(assessment.task)
  const returnTo = coursePath(courseId)
  const applicationTasks: CourseApplicationTaskView[] = assessment.applications || []
  const generatingApplications = courseTaskPending(assessment.application_generation_task)
  return (
    <div className="course-assessment-run">
      <p className="tiny muted" role="status" aria-live="polite">
        {FLOW_TEXT[state] || '正在读取本次检查的状态。'}
      </p>
      {state === 'generating' && quizTaskPending && <Loading>正在准备结业检查题目…</Loading>}
      {['failed', 'cancelled'].includes(state) && assessment.task && (
        <p className="notice">{courseTaskErrorMessage(assessment.task)}</p>
      )}
      <div className="button-row">
        {assessment.quiz_id ? (
          <Link
            className="button primary"
            to={withCourseReturn(`/quizzes/${encodeURIComponent(assessment.quiz_id)}`, returnTo)}
          >
            <ClipboardCheck size={16} />
            {assessment.quiz_settled ? '查看本次检查的作答' : '进入本次检查作答'}
            <ArrowRight size={15} />
          </Link>
        ) : (
          assessment.task &&
          quizTaskPending && (
            <Link
              className="button secondary"
              to={withCourseReturn(`/tasks/${encodeURIComponent(assessment.task.task_id)}`, returnTo)}
            >
              查看题目准备进度
            </Link>
          )
        )}
        {!sealed && (
          <button
            type="button"
            className="button secondary"
            disabled={locked || !assessment.quiz_settled}
            onClick={() => {
              void controller.complete(helpUsage)
            }}
          >
            <Lock size={16} />
            {controller.operation.pending === 'complete-assessment' ? '正在封存…' : '封存本次检查'}
          </button>
        )}
        <button
          type="button"
          className="text-button"
          disabled={controller.detailQuery.isFetching}
          onClick={controller.refresh}
        >
          刷新检查状态
        </button>
      </div>
      {!sealed && (
        <fieldset className="course-assessment-help" disabled={locked || !assessment.quiz_settled}>
          <legend className="tiny">封存前，请说明这次作答是否用过提示或帮助</legend>
          {(Object.keys(HELP_USAGE_LABELS) as CourseHelpUsage[]).map((option) => (
            <label key={option} className="course-help-option">
              <input
                type="radio"
                name="assessment-help-usage"
                value={option}
                checked={helpUsage === option}
                onChange={() => setHelpUsage(option)}
              />
              <span>{HELP_USAGE_LABELS[option]}</span>
            </label>
          ))}
          <p className="tiny muted">
            这是你自己的说明，用于记录来源。系统不会据此声称已核验系统外的独立完成情况。
          </p>
        </fieldset>
      )}
      <CourseOperationNotice
        state={controller.operation.state}
        error={controller.operation.error}
        confirmedMessage={
          controller.operation.state.kind === 'confirmed' &&
          controller.operation.state.operation === 'complete-assessment'
            ? '本次检查已封存。目标结果以下方投影为准。'
            : undefined
        }
        onRecover={controller.recovery ? controller.recover : controller.refresh}
        recoveryLabel="核对检查状态"
        disabled={pending}
      />
      {controller.recoveryChecked && (
        <button type="button" className="text-button" disabled={pending} onClick={controller.retryOriginal}>
          重试原检查请求
        </button>
      )}
      <section className="course-assessment-applications" aria-label="文本应用任务">
        <div className="section-line">
          <h4>练习实际情境</h4>
          <span className="badge">每次 1–2 题</span>
        </div>
        <p className="tiny muted">
          用文字完成一个贴近使用场景的任务。服务器只接收文本，不会运行你提交的代码或命令。
        </p>
        {applicationTasks.length ? (
          <ol className="course-application-list">
            {applicationTasks.map((task, index) => (
              <CourseApplicationTask
                key={task.application_task_id}
                courseId={courseId}
                assessmentId={assessment.course_assessment_id}
                task={task}
                index={index}
                sealed={sealed}
                disabled={locked}
                operationState={applications.stateFor(
                  task.application_task_id,
                  task.latest_attempt_id,
                )}
                operationError={applications.operation.error}
                onSubmit={applications.submit}
                onRetryFeedback={applications.retryFeedback}
                recovery={applications.recovery?.applicationTaskId === task.application_task_id
                  ? applications.recovery : null}
                onRecover={() => { void applications.recover(task.application_task_id) }}
                onReplay={() => { void applications.recover(task.application_task_id, true) }}
                onUnavailable={onUnavailable}
                onEvidence={onEvidence}
              />
            ))}
          </ol>
        ) : generatingApplications ? (
          <Loading>正在准备应用任务…</Loading>
        ) : (
          <>
            {assessment.application_generation_task &&
              ['failed', 'cancelled'].includes(assessment.application_generation_task.status) && (
                <p className="notice">
                  {courseTaskErrorMessage(assessment.application_generation_task)}
                </p>
              )}
            {!sealed && (
              <button
                type="button"
                className="button secondary"
                disabled={locked}
                onClick={() => {
                  void controller.createApplications()
                }}
              >
                <Sparkles size={16} />
                {controller.operation.pending === 'applications' ? '正在提交…' : '生成一个应用任务'}
              </button>
            )}
          </>
        )}
      </section>
      <section className="course-assessment-uncovered" aria-label="本次检查未覆盖的目标">
        <h4>本次检查未覆盖的目标（{uncovered.length}）</h4>
        {uncovered.length ? (
          <>
            <p className="tiny muted">
              这一组检查只覆盖了部分目标。以下目标本次没有对应题目，仍需要后续检查或应用任务。
            </p>
            <CourseGoalList goals={uncovered} showCoverage onLesson={onLesson} />
          </>
        ) : (
          <p className="tiny muted">本次检查为当前所有可检验目标都建立了对应题目。</p>
        )}
      </section>
    </div>
  )
}
