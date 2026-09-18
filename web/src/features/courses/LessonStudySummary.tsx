import { ArrowRight, CheckCircle2 } from 'lucide-react'
import { Link } from 'react-router-dom'
import { formatDate } from '../../components/ui'
import type { CourseLessonView, CourseNextAction, CourseWeakPoint } from '../../types/course'
import { LessonText } from './LessonText'
import { lessonNextActionLabels, type LessonStudyFacts } from './lessonStudyFacts'

export function LessonStudySummary({ lesson, facts, practiceMessage, weakPoints, progressState, nextAction, onNextAction, onRefresh }: {
  lesson: CourseLessonView
  facts: LessonStudyFacts
  practiceMessage: string
  weakPoints: CourseWeakPoint[]
  progressState: 'loading' | 'confirmed' | 'unconfirmed'
  nextAction?: CourseNextAction
  onNextAction: (action: CourseNextAction) => void
  onRefresh: () => void
}) {
  const currentWeakPoints = [...new Set(weakPoints.filter((point) => point.lesson_id === lesson.lesson_id)
    .map((point) => point.knowledge_point).filter(Boolean))]
  return (
    <section id="lesson-summary" className="card lesson-study-summary" aria-label="本课小结" tabIndex={-1}>
      <div className="section-line"><h3>本课小结</h3><span className="badge">按已保存记录整理</span></div>
      {lesson.objective && <p className="course-objective">本课目标：{lesson.objective}</p>}
      <div className="lesson-summary-recap">
        {facts.recap.map((text, index) => <LessonText key={index} text={text} />)}
        {!facts.recap.length && <p className="muted">本课尚未保存内容回顾，可返回正文继续阅读。</p>}
      </div>
      <dl className="lesson-summary-facts">
        <div><dt>阅读记录</dt><dd>{facts.readAt ? <><CheckCircle2 size={16} />已记录阅读</> : '尚未记录已读'}</dd>
          {facts.readAt && <dd className="tiny muted">{formatDate(facts.readAt)}</dd>}</div>
        <div><dt>自检回答</dt><dd>{facts.savedCheckCount === null
          ? facts.selfCheckState === 'loading' ? '正在读取保存记录…' : '保存数量尚未确认'
          : `已保存 ${facts.savedCheckCount} / ${facts.checkCount} 题`}</dd>
          <dd className="tiny muted">自检不计分，教学反馈单独保存。</dd></div>
        <div><dt>本课首次练习</dt><dd>{facts.practice
          ? `答对 ${facts.practice.correct} / ${facts.practice.total} 题` : practiceMessage}</dd>
          {facts.practice && <dd className="tiny muted">已作答 {facts.practice.answered} 题，已完成结算。</dd>}</div>
      </dl>
      <div className="lesson-summary-weak-points">
        <h4>待巩固</h4>
        {progressState !== 'confirmed' ? <p className="muted">待巩固记录暂未读回。</p>
          : currentWeakPoints.length ? <ul>{currentWeakPoints.map((point) => <li key={point}>{point}</li>)}</ul>
            : <p className="muted">当前没有本课待巩固记录；阅读和自检不代表已经掌握。</p>}
      </div>
      {nextAction && <p className="muted">下一步：{nextAction.reason}</p>}
      <div className="button-row">
        {nextAction && <button type="button" className="button primary" onClick={() => onNextAction(nextAction)}>
          {lessonNextActionLabels[nextAction.type]}<ArrowRight size={16} /></button>}
        <Link className="button secondary" to="/study">返回我的学习</Link>
        <button type="button" className="text-button" onClick={onRefresh}>刷新本课记录</button>
      </div>
    </section>
  )
}
