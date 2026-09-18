import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { formatDate } from '../../components/ui'
import { getCourseExport, type CourseExportView } from '../../services/courseExports'

/** 同一导出快照的打印页：React 原生标签渲染，不把 markdown 转成 HTML。 */
export function CoursePrintPage() {
  const { courseId } = useParams()
  const [view, setView] = useState<CourseExportView | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    if (!courseId) return
    getCourseExport(courseId)
      .then((data) => {
        if (active) setView(data)
      })
      .catch((cause) => {
        if (active) setError(cause instanceof Error ? cause.message : '快照读取失败')
      })
    return () => {
      active = false
    }
  }, [courseId])

  useEffect(() => {
    if (view) window.print()
  }, [view])

  if (error) {
    return (
      <main className="course-print">
        <p role="alert">{error}</p>
        <Link to="/study" className="text-link">返回我的学习</Link>
      </main>
    )
  }
  if (!view) return <main className="course-print">正在整理学习成果…</main>
  const snapshot = view.snapshot
  return (
    <main className="course-print">
      <h1>{snapshot.title} · 学习成果</h1>
      <p className="tiny muted">
        导出时间 {formatDate(snapshot.generated_at)} · 目标版本 {snapshot.criteria_revision} · 仅当前版本
      </p>
      <section>
        <h2>我的学习摘要</h2>
        <ul>{(snapshot.personal_summary ?? []).map((item) => <li key={item}>{item}</li>)}</ul>
      </section>
      <section>
        <h2>目标与证据</h2>
        <ul>
          {(snapshot.outcomes?.criteria ?? []).map((outcome) => (
            <li key={outcome.course_criterion_id}>
              {outcome.title}：{outcome.status}——{outcome.reason}
            </li>
          ))}
        </ul>
      </section>
      <section>
        <h2>我的回答与纠正</h2>
        {(snapshot.records ?? []).map((record, index) => (
          <article className="course-print-record" key={index}>
            <h3>{record.title}</h3>
            <p className="tiny muted">{record.occurred_at}</p>
            {record.own_answer && <pre>{record.own_answer}</pre>}
            {record.feedback_text && <p>{record.feedback_text}</p>}
          </article>
        ))}
      </section>
      {(snapshot.sources ?? []).length > 0 && (
        <section>
          <h2>资料引用</h2>
          <ul>
            {(snapshot.sources ?? []).map((source) => (
              <li key={source.export_ref}>{source.title}{source.locator ? ` · ${source.locator}` : ''}</li>
            ))}
          </ul>
        </section>
      )}
      <p className="tiny muted">{(snapshot.warnings ?? []).join(' ')}</p>
      <p><Link to="/study" className="text-link">返回我的学习</Link></p>
    </main>
  )
}
