import { Check, CircleDashed, Loader2 } from 'lucide-react'
import type { CourseTaskView, CourseTeachingMode } from '../../types/course'
import {
  AGENT_STEP_STATE_LABELS,
  agentProgressFact,
  type AgentStepState,
} from './courseQualityFacts'

function StepIcon({ state }: { state: AgentStepState }) {
  if (state === 'done') return <Check size={15} aria-hidden="true" />
  if (state === 'active') return <Loader2 size={15} className="spin" aria-hidden="true" />
  return <CircleDashed size={15} aria-hidden="true" />
}

/**
 * 真实的角色协作阶段。
 *
 * 只在任务确实进入过 planning/teaching/reviewing/revising 时展示；没有百分比、
 * 没有预计完成时间，也不为未发生的核对或返修播放进度动画。阶段事件不携带
 * prompt、正文或隐藏推理，这里也只显示阶段名称与状态。
 */
export function CourseAgentProgress({
  task,
  teachingMode,
  reviewRequested,
}: {
  task?: CourseTaskView | null
  teachingMode: CourseTeachingMode
  reviewRequested?: boolean
}) {
  const fact = agentProgressFact(task, teachingMode, { reviewRequested })
  if (!fact.collaborating) return null
  return (
    <section className="course-agent-progress" aria-label="教学协作阶段">
      <div className="section-line">
        <h4>教学协作进度</h4>
        <span className="badge">{teachingMode === 'guided' ? '标准教学' : '快速生成 · 已请求核对'}</span>
      </div>
      <ol className="course-agent-steps" role="list">
        {fact.steps.map((step) => (
          <li key={step.stage} className={`course-agent-step ${step.state}`}>
            <StepIcon state={step.state} />
            <span>
              <strong>{step.label}</strong>
              <small>{AGENT_STEP_STATE_LABELS[step.state]}</small>
            </span>
          </li>
        ))}
      </ol>
      <p className="tiny muted" role="status" aria-live="polite">
        {fact.running
          ? `当前阶段：${fact.steps.find((step) => step.state === 'active')?.label || '正在准备'}。可以离开此页，稍后回来继续查看。`
          : '本次任务已结束。未观察到的阶段结果未知，页面只显示已发生的阶段。'}
      </p>
      {fact.planReused && (
        <p className="tiny muted">本课直接读取已保存的课程规划，不重新规划整门课程。</p>
      )}
      {!fact.reviewRequested && (
        <p className="tiny muted">本次生成没有请求教学核对，不会显示已完成核对。</p>
      )}
    </section>
  )
}
