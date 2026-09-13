import { useEffect, useState } from 'react'
import { formatDate } from '../../components/ui'
import { listCourseFeedback, type CourseCorrectionView } from '../../services/courseFeedback'
import type { CourseSelfCheckView } from '../../types/course'

/**
 * 自检历史对照（B02）。
 *
 * 仅在本次回答保存成功后展示；每份旧回答并排显示保存时间、内容版本、
 * 当时回答与已确认纠正。没有确认纠正时不杜撰标准答案。
 */
export function SelfCheckHistory({
  courseId,
  lessonId,
  attempts,
}: {
  courseId: string
  lessonId: string
  attempts: CourseSelfCheckView[]
}) {
  if (!attempts.length) {
    return <p className="tiny muted">这道题还没有更早的已保存回答。</p>
  }
  return (
    <div className="self-check-history">
      <p className="tiny muted">
        以下是你更早保存的回答（最近 5 份），仅作对照；自检不计分，也不改变正式成绩。
      </p>
      <ul className="self-check-history-list">
        {attempts.map((attempt) => (
          <HistoryRow
            key={attempt.attempt_id}
            courseId={courseId}
            lessonId={lessonId}
            attempt={attempt}
          />
        ))}
      </ul>
    </div>
  )
}

function HistoryRow({
  courseId,
  lessonId,
  attempt,
}: {
  courseId: string
  lessonId: string
  attempt: CourseSelfCheckView
}) {
  const [corrections, setCorrections] = useState<CourseCorrectionView[] | null>(null)
  useEffect(() => {
    let active = true
    listCourseFeedback(courseId, { lesson_id: lessonId, check_attempt_id: attempt.attempt_id })
      .then((list) => {
        if (!active) return
        const collected = (list.items || []).flatMap((item) => item.corrections ?? [])
        setCorrections(collected)
      })
      .catch(() => {
        if (active) setCorrections([])
      })
    return () => {
      active = false
    }
  }, [courseId, lessonId, attempt.attempt_id])

  return (
    <li className="self-check-history-row">
      <p className="tiny muted">
        {formatDate(attempt.saved_at)} · 内容版本 v{attempt.content_version}
      </p>
      <pre className="self-check-history-answer">{attempt.answer}</pre>
      {corrections === null ? (
        <p className="tiny muted">正在读取纠正记录…</p>
      ) : corrections.length ? (
        <ul className="self-check-history-corrections">
          {corrections.map((item) => (
            <li key={item.correction_id} className={item.confirmation === 'confirmed' ? 'confirmed' : undefined}>
              {item.confirmation === 'confirmed' ? '已确认纠正' : '纠正说明（暂定）'}
              ：{item.text}
              {item.confirmation === 'confirmed' && `（${formatDate(item.created_at)}）`}
            </li>
          ))}
        </ul>
      ) : (
        <p className="tiny muted">尚无已确认纠正。</p>
      )}
    </li>
  )
}
