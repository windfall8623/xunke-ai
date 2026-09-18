import { CheckCircle2, CircleAlert, Info } from 'lucide-react'
import type { CourseTeachingMode, TeachingQualitySummary } from '../../types/course'
import { QUALITY_STATUS_LABELS, teachingQualityFact } from './courseQualityFacts'

const LEVEL_LABELS = { outline: '课程纲要', lesson: '本课内容' } as const

/**
 * 教学核对结论的朴素说明。
 *
 * 不显示 draft_hash、prompt、模型原文或内部推理；核对结论与学习成绩使用
 * 不同的展示位置和文案，不共用状态徽标。
 */
export function CourseQualityNotice({
  summary,
  level,
  teachingMode,
  reviewRequested,
  onRequestReview,
  requestPending = false,
  requestDisabled = false,
}: {
  summary?: TeachingQualitySummary | null
  level: 'outline' | 'lesson'
  teachingMode: CourseTeachingMode
  reviewRequested?: boolean
  /** 仅在内容尚未生成、可以显式请求核对时提供。 */
  onRequestReview?: () => void
  requestPending?: boolean
  requestDisabled?: boolean
}) {
  const fact = teachingQualityFact(summary, teachingMode, { reviewRequested })
  const target = LEVEL_LABELS[summary?.level || level]
  const headline =
    fact.status === 'reviewed'
      ? `${target}已完成教学核对`
      : fact.status === 'needs_revision'
        ? `${target}发现需要修改的内容`
        : `${target}尚未完成教学核对`
  const Icon = fact.status === 'reviewed' ? CheckCircle2 : fact.status === 'needs_revision' ? CircleAlert : Info
  return (
    <section
      className={`course-quality-notice ${fact.status}`}
      aria-label={`${target}教学核对状态`}
    >
      <p className="course-quality-headline">
        <Icon size={16} aria-hidden="true" />
        <strong>{headline}</strong>
        <span className="badge">{teachingMode === 'guided' ? '标准教学' : '快速生成'}</span>
      </p>
      <p className="tiny muted">
        {fact.status === 'reviewed'
          ? '教学核对检查了讲解、示例与理解检查是否对应课程目标，不代表课程完全正确，也不代表你已掌握。'
          : fact.status === 'needs_revision'
            ? '本次新稿没有发布，已保存的内容仍可继续阅读。'
            : '这里只说明内容是否经过教学核对，与你的学习成绩无关。'}
      </p>
      {!!fact.reason && (
        <p className="tiny muted" role="status">
          {fact.reason}
        </p>
      )}
      {!!fact.warnings.length && (
        <ul className="course-quality-warnings">
          {fact.warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      )}
      {onRequestReview && fact.status !== 'reviewed' && (
        <button
          type="button"
          className="button secondary"
          disabled={requestPending || requestDisabled}
          onClick={onRequestReview}
        >
          {requestPending ? '正在提交…' : '生成时执行教学核对'}
        </button>
      )}
      <p className="sr-only">{QUALITY_STATUS_LABELS[fact.status]}</p>
    </section>
  )
}
