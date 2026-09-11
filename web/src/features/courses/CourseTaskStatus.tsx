import { CircleStop, RefreshCw } from 'lucide-react'
import { ErrorNotice, Loading } from '../../components/ui'
import {
  courseErrorMessage,
  courseTaskErrorMessage,
  courseTaskPending,
} from '../../services/courses'
import type { CourseTaskView } from '../../types/course'
import { useCourseTask } from './useCourseTask'

const stageLabels: Record<string, string> = {
  queued: '已排队，等待开始',
  pending: '已排队，等待开始',
  resolving_scope: '正在确认资料范围',
  preparing_sources: '正在读取课程资料',
  preparing_course_sources: '正在读取课程资料',
  generating_outline: '正在生成课程纲要',
  generating_lesson: '正在生成本课内容',
  saving_course: '正在保存课程内容',
  retrieving: '正在查找本课依据',
  retrieval: '正在查找本课依据',
  planning: '正在梳理学习目标',
  validating: '正在检查内容',
  validation: '正在检查内容',
  repairing: '正在修正内容结构',
  saving: '正在保存内容',
  publishing: '正在保存内容',
}

export function CourseTaskStatus({
  courseId,
  task: initial,
  onRetry,
  disabled = false,
}: {
  courseId: string
  task: CourseTaskView
  onRetry?: () => void
  disabled?: boolean
}) {
  const { task, query, cancel, cancelling, cancelError } = useCourseTask(courseId, initial)
  if (!task) return null
  const running = courseTaskPending(task)
  const failed = task.status === 'failed' || task.status === 'cancelled'
  const label = task.kind === 'course_outline' ? '课程纲要' : '本课内容'
  return (
    <section className="course-task card" aria-label={`${label}生成状态`}>
      {running ? (
        <Loading>{stageLabels[task.stage] || `正在生成${label}`}</Loading>
      ) : (
        <h3>
          {failed
            ? `${label}${task.status === 'cancelled' ? '已取消' : '生成未完成'}`
            : `${label}已保存`}
        </h3>
      )}
      <p className="muted" role="status">
        {running
          ? '可以离开此页，稍后回到课程继续查看。'
          : task.status === 'cancelled'
            ? '已保存的其他课时仍可阅读。需要时可重新生成本次内容。'
            : failed
              ? courseTaskErrorMessage(task)
              : '正在读取已保存的内容…'}
      </p>
      <ErrorNotice
        error={query.error ? courseErrorMessage(query.error) : null}
        onRetry={() => {
          void query.refetch()
        }}
      />
      <ErrorNotice error={cancelError ? courseErrorMessage(cancelError) : null} />
      <div className="button-row">
        {running && (
          <button
            type="button"
            className="button secondary"
            onClick={cancel}
            disabled={cancelling || disabled}
          >
            <CircleStop size={16} />
            {cancelling ? '正在取消…' : '取消本次生成'}
          </button>
        )}
        {failed && onRetry && (
          <button
            type="button"
            className="button primary"
            onClick={onRetry}
            disabled={disabled || cancelling}
          >
            <RefreshCw size={16} />
            {disabled ? '正在提交…' : '重新生成'}
          </button>
        )}
        <button
          type="button"
          className="text-button"
          disabled={query.isFetching}
          onClick={() => {
            void query.refetch()
          }}
        >
          刷新状态
        </button>
      </div>
    </section>
  )
}
