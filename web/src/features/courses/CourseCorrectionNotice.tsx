import { formatDate } from '../../components/ui'
import { confirmedCorrections, correctionEffectLabel, type CourseFeedbackView } from '../../services/courseFeedback'

/**
 * 确认纠正说明（B03）：区分教学解释、个人纠正与权威判分修正。
 * 没有确认纠正时如实说明，不把模型建议当标准答案。
 */
export function CourseCorrectionNotice({ view }: { view: CourseFeedbackView }) {
  const confirmed = confirmedCorrections(view)
  return (
    <div className="course-correction-notice">
      {confirmed.length ? (
        confirmed.map((item) => (
          <p key={item.correction_id} className="correction confirmed">
            已确认纠正（{formatDate(item.created_at)}）：{item.text}
          </p>
        ))
      ) : (
        <p className="tiny muted">尚无已确认纠正；你保存的说明会以暂定状态展示。</p>
      )}
      <p className="tiny muted">{correctionEffectLabel(view)}</p>
    </div>
  )
}
