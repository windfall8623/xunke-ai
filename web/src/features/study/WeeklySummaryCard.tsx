import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  getWeeklySummary,
  type WeeklyLearningSummary,
} from '../../services/learningSummary'

const countLabels: Array<[keyof WeeklyLearningSummary['counts'], string]> = [
  ['self_checks_saved', '保存自检'],
  ['quizzes_settled', '完成检查'],
  ['practices_completed', '完成练习'],
  ['applications_submitted', '提交应用'],
  ['scheduled_reviews_completed', '按期复习'],
]

/** 规则周报（B07）：只叙述已保存的事实；无活动周如实显示，不推断学习时长。 */
export function WeeklySummaryCard({ timezone = 'Asia/Shanghai' }: { timezone?: string }) {
  const [summary, setSummary] = useState<WeeklyLearningSummary | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let active = true
    getWeeklySummary(timezone)
      .then((view) => {
        if (active) setSummary(view)
      })
      .catch(() => {
        if (active) setFailed(true)
      })
    return () => {
      active = false
    }
  }, [timezone])

  if (failed) return null
  if (!summary) return null
  const total =
    summary.counts.self_checks_saved + summary.counts.quizzes_settled +
    summary.counts.practices_completed + summary.counts.applications_submitted +
    summary.counts.scheduled_reviews_completed
  if (!total && !(summary.confirmed_corrections ?? []).length) {
    return (
      <section className="card weekly-summary" aria-label="本周学习周报">
        <h3>本周学习周报</h3>
        <p className="tiny muted">本周暂无已保存的学习活动；打开页面本身不会计入学习。</p>
      </section>
    )
  }
  return (
    <section className="card weekly-summary" aria-label="本周学习周报">
      <h3>本周学习周报</h3>
      <ul className="weekly-summary-counts">
        {countLabels.map(([key, label]) => (
          <li key={key}>
            {label} <strong>{summary.counts[key]}</strong>
          </li>
        ))}
      </ul>
      {(summary.confirmed_corrections ?? []).length > 0 && (
        <p className="tiny muted">
          本周有 {(summary.confirmed_corrections ?? []).length} 条已确认纠正，可在对应课时查看。
        </p>
      )}
      {(summary.next_actions ?? []).length > 0 && (
        <p className="tiny muted">
          下一步建议：{(summary.next_actions ?? [])[0]?.title ?? ''}——
          <Link to="/study" className="text-link">进入我的学习</Link>
        </p>
      )}
      <p className="tiny muted">
        以上为已保存的学习活动计数，不代表掌握率；检查正确率与目标状态见各课程页。
      </p>
    </section>
  )
}
