import { ArrowRight, BookOpen } from 'lucide-react'
import type { LessonPracticeState } from './lessonStudyFacts'

export type LessonFlowActionsProps = {
  read: boolean
  practiceState: LessonPracticeState
  pending: boolean
  onReadAndPractice: () => Promise<void>
  onPractice: () => void
  onSummary: () => void
  onFinishSession: () => void
  onRefresh: () => void
  onCancelRead: () => void
}

export function LessonFlowActions(props: LessonFlowActionsProps) {
  const unconfirmed = ['unconfirmed', 'unavailable'].includes(props.practiceState)
  const settled = props.practiceState === 'settled'
  const label = unconfirmed ? '刷新本课结果' : settled ? '查看本课小结' : !props.read
    ? '记录已读，进入本课练习' : props.practiceState === 'preparing'
      ? '查看练习准备进度' : props.practiceState === 'answering' ? '继续本课练习' : '做本课三题'
  function primaryAction() {
    if (unconfirmed) props.onRefresh()
    else if (settled) props.onSummary()
    else if (!props.read) void props.onReadAndPractice()
    else props.onPractice()
  }
  return (
    <section id="course-practice" className="card lesson-flow-actions" aria-label="本课下一步" tabIndex={-1}>
      <div>
        <h3><BookOpen size={19} />把理解带到练习里</h3>
        <p className="muted">自检和教学反馈帮助整理思路；正式练习会单独记录作答结果。</p>
      </div>
      <div className="button-row">
        <button type="button" className="button primary" disabled={props.pending} onClick={primaryAction}>
          {props.pending ? '正在确认，请稍候…' : label}<ArrowRight size={17} />
        </button>
        <button type="button" className="button secondary" onClick={props.onFinishSession}>
          本次先到这里
        </button>
        {props.read && <button type="button" className="text-button" disabled={props.pending}
          onClick={props.onCancelRead}>取消已读标记</button>}
      </div>
    </section>
  )
}
