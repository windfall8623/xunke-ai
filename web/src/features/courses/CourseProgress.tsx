import { ArrowRight, BookOpen, CalendarClock, Target } from 'lucide-react'
import { Link } from 'react-router-dom'
import { StatusBadge, formatDate } from '../../components/ui'
import { coursePath, withCourseReturn } from '../../services/courseNavigation'
import { courseReviewTime } from '../../services/courses'
import type {
  CourseLessonSummary,
  CourseNextAction,
  CourseProgressView,
  CourseReviewView,
} from '../../types/course'

const actionLabels: Record<CourseNextAction['type'], string> = {
  continue_quiz: '继续练习',
  review_lesson: '查看待补练',
  learn_lesson: '进入下一课',
  practice_lesson: '进入本课练习',
  view_summary: '回看学习记录',
}

export function CourseProgress({
  progress,
  lessons,
  reviews = [],
  onAction,
  onLesson,
}: {
  progress: CourseProgressView
  lessons: CourseLessonSummary[]
  reviews?: CourseReviewView[]
  onAction: (action: CourseNextAction) => void
  onLesson: (lessonId: string) => void
}) {
  const reviewRuns = progress.review_runs || []
  const titleFor = (id: string) =>
    lessons.find((lesson) => lesson.lesson_id === id)?.title || '相关课时'
  const observed = (progress.weak_points || []).filter(
    (point, index, points) =>
      points.findIndex(
        (other) =>
          other.lesson_id === point.lesson_id && other.knowledge_point === point.knowledge_point,
      ) === index,
  )
  const pending = (progress.pending_weak_points || []).filter(
    (point, index, points) =>
      points.findIndex(
        (other) =>
          other.lesson_id === point.lesson_id && other.knowledge_point === point.knowledge_point,
      ) === index,
  )
  const scheduled = reviews
    .filter((review) => ['scheduled', 'generating', 'ready', 'failed'].includes(review.status))
    .sort((a, b) => a.due_at.localeCompare(b.due_at))
  return (
    <section id="course-progress" className="card course-progress" aria-label="课程学习进度">
      <div className="section-line">
        <h2>我的学习进度</h2>
        <span className="tiny muted">根据已保存的阅读与作答记录更新</span>
      </div>
      <div className="course-progress-stats" id="course-progress-stats">
        <div>
          <span>阅读进度</span>
          <strong>
            {progress.read_lessons}
            <small> / {progress.available_lessons} 节</small>
          </strong>
          <p>已准备 {progress.generated_lessons} 节正文</p>
        </div>
        <div>
          <span>练习完成情况</span>
          <strong>
            {progress.practiced_lessons}
            <small> / {progress.available_lessons} 节</small>
          </strong>
          <p>已完成首次课后检查</p>
        </div>
        <div>
          <span>首次检查表现</span>
          <strong>
            {progress.initial_accuracy == null
              ? '尚未练习'
              : `${Math.round(progress.initial_accuracy * 100)}%`}
          </strong>
          <p>
            {progress.initial_answered
              ? `已答 ${progress.initial_answered} 题，答对 ${progress.initial_correct} 题`
              : '作答后显示实际正确率'}
          </p>
        </div>
        <div>
          <span>补练与复习</span>
          <strong>
            {reviewRuns.length}
            <small> 次</small>
          </strong>
          <p>各次记录单独保留，不覆盖首次成绩</p>
        </div>
      </div>
      {progress.total_lessons > progress.available_lessons && (
        <p className="tiny muted">
          另有 {progress.total_lessons - progress.available_lessons}{' '}
          节存在资料缺口，未计入可学习课时。
        </p>
      )}
      <div className="course-next-action">
        <BookOpen size={22} />
        <div>
          <strong>下一步</strong>
          <p>{progress.next_action.reason}</p>
        </div>
        <button
          type="button"
          className="button secondary"
          onClick={() => onAction(progress.next_action)}
        >
          {actionLabels[progress.next_action.type]}
          <ArrowRight size={16} />
        </button>
      </div>
      <div className="course-weak-points">
        <h3>
          <Target size={17} />
          待补练
        </h3>
        <p className="tiny muted">根据尚未完成后续补练的错题批次显示；补练完成后保留历史作答。</p>
        {!pending.length ? (
          <p className="muted">目前没有待补练的错题批次，可以继续学习或按建议复习。</p>
        ) : (
          <div className="tag-list">
            {pending.map((point) => (
              <button
                type="button"
                className="tag peach"
                key={`${point.lesson_id}:${point.knowledge_point}`}
                onClick={() => onLesson(point.lesson_id)}
              >
                {point.knowledge_point || titleFor(point.lesson_id)}
              </button>
            ))}
          </div>
        )}
      </div>
      {!!observed.length && (
        <details className="course-history-errors">
          <summary>历史错题涉及的知识点（{observed.length}）</summary>
          <p className="tiny muted">
            保留过去每次检查发现的问题；待补练清空不代表这些知识点已长期掌握。
          </p>
          <div className="tag-list">
            {observed.map((point) => (
              <button
                type="button"
                className="tag"
                key={`${point.lesson_id}:${point.knowledge_point}`}
                onClick={() => onLesson(point.lesson_id)}
              >
                {point.knowledge_point || titleFor(point.lesson_id)}
              </button>
            ))}
          </div>
        </details>
      )}
      {!!scheduled.length && (
        <div className="course-progress-reviews">
          <h3>
            <CalendarClock size={17} />
            下次复习建议
          </h3>
          <p className="tiny muted">
            按课时安排再次检查。当前三题结果用于建议次日复习，不代表独立掌握。
          </p>
          {scheduled.map((review) => (
            <div className="course-quiz-row" key={review.review_id}>
              <div>
                <strong>{titleFor(review.lesson_id)}</strong>
                <p className="tiny muted">
                  {courseReviewTime(review)} · {review.timezone}
                </p>
                <p className="tiny muted">{review.reason}</p>
              </div>
              <Link
                className="text-link"
                to={`${coursePath(progress.course_id, review.lesson_id)}#course-review`}
              >
                {['generating', 'ready'].includes(review.status) ? '继续复习' : '查看安排'}
                <ArrowRight size={14} />
              </Link>
            </div>
          ))}
        </div>
      )}
      {!!reviewRuns.length && (
        <div className="course-review-runs">
          <h3>补练与复习记录</h3>
          <p className="muted tiny">错题补练和课时复习分别记录，均不覆盖首次检查的成绩。</p>
          <div className="course-table-scroll">
            <table>
              <thead>
                <tr>
                  <th scope="col">课时</th>
                  <th scope="col">类型</th>
                  <th scope="col">作答情况</th>
                  <th scope="col">状态</th>
                  <th scope="col">时间</th>
                  <th scope="col">入口</th>
                </tr>
              </thead>
              <tbody>
                {reviewRuns.map((run) => (
                  <tr key={run.link_id}>
                    <td>{titleFor(run.lesson_id)}</td>
                    <td>{run.kind === 'scheduled_review' ? '课时复习' : '错题补练'}</td>
                    <td>
                      {run.answered ? `答对 ${run.correct} / 已答 ${run.answered} 题` : '尚未作答'}
                      <small className="muted"> · 共 {run.total} 题</small>
                    </td>
                    <td>
                      <StatusBadge status={run.status} />
                    </td>
                    <td>{formatDate(run.created_at)}</td>
                    <td>
                      {run.quiz_id ? (
                        <Link
                          className="text-link"
                          to={withCourseReturn(
                            `/quizzes/${encodeURIComponent(run.quiz_id)}`,
                            coursePath(progress.course_id, run.lesson_id),
                          )}
                        >
                          查看练习
                        </Link>
                      ) : (
                        <button
                          type="button"
                          className="text-button"
                          onClick={() => onLesson(run.lesson_id)}
                        >
                          查看状态
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  )
}
