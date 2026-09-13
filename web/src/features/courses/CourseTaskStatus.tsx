import { CircleStop, RefreshCw } from 'lucide-react'
import { ErrorNotice, Loading } from '../../components/ui'
import {
  courseErrorMessage,
  courseTaskErrorMessage,
  courseTaskPending,
} from '../../services/courses'
import type { CourseTaskView } from '../../types/course'
import { useCourseTask } from './useCourseTask'
import { CourseOperationNotice } from './CourseOperationNotice'
import { recordExperienceEvent } from '../../services/experienceEvents'

// 只映射任务阶段流里的真实公开阶段；generating 走按 kind 的兜底文案，
// 不虚构百分比或预计完成时间。
const stageLabels: Record<string, string> = {
  queued: '已排队，等待开始',
  pending: '已排队，等待开始',
  starting: '正在准备生成',
  retrieving: '正在查找本课依据',
  planning: '课程设计',
  teaching: '讲解生成',
  reviewing: '教学检查',
  revising: '根据反馈修订',
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
  const { task, query, cancel, cancelling, cancelError, cancelState, settling, settleExpired, refreshBusiness } = useCourseTask(courseId, initial)
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
            : `${label}已生成，正在读取`}
        </h3>
      )}
      <p className="muted" role="status">
        {running
          ? '可以离开此页，稍后回到课程继续查看。'
          : task.status === 'cancelled'
            ? '已保存的其他课时仍可阅读。需要时可重新生成本次内容。'
            : failed
              ? courseTaskErrorMessage(task)
              : query.error ? '结果读取暂未完成，请刷新结果。' : '正在核对并读取已保存的内容…'}
      </p>
      {settling && <p className="tiny muted">任务已结束，记录同步中</p>}
      <ErrorNotice
        error={query.error ? courseErrorMessage(query.error) : null}
        onRetry={() => {
          void query.refetch()
        }}
      />
      <CourseOperationNotice state={cancelState} error={cancelError}
        onRecover={() => { void query.refetch(); refreshBusiness() }} recoveryLabel="核对任务状态"
        disabled={query.isFetching || cancelling} />
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
            onClick={() => {
              void recordExperienceEvent({ event_id: crypto.randomUUID(), name: 'task_retry_clicked',
                course_id: courseId, lesson_id: task.lesson_id || undefined, task_id: task.task_id })
              onRetry()
            }}
            disabled={disabled || cancelling || (settling && !settleExpired)}
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
            refreshBusiness()
          }}
        >
          {task.status === 'completed' ? '刷新结果' : '刷新状态'}
        </button>
      </div>
    </section>
  )
}
