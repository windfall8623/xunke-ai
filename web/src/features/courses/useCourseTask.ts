import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'
import { useIdentityKey } from '../../app/AuthProvider'
import { courseKeys, coursesApi, courseTaskPending } from '../../services/courses'
import { ApiError } from '../../services/http'
import type { CourseTaskView } from '../../types/course'
import type { TaskEvent, TaskStreamState } from '../../types/taskEvent'
import { useSettleWatch, useTaskEvents, type SettleWatch } from '../tasks/useTaskEvents'
import { useCourseOperation } from './useCourseOperation'

export function useCourseTask(courseId: string, initial?: CourseTaskView | null) {
  const identity = useIdentityKey()
  const client = useQueryClient()
  const operation = useCourseOperation()
  const settled = useRef('')
  const streamStateRef = useRef<TaskStreamState>('closed')
  const settleStateRef = useRef<SettleWatch>({ taskId: null, active: false, expired: false })
  const queryKey = courseKeys.task(identity, courseId, initial?.task_id || '', initial?.lesson_id)
  const query = useQuery({
    queryKey,
    queryFn: async ({ signal }) => {
      const task = await coursesApi.task(initial!.task_id, signal)
      if (task.course_id !== courseId || (task.lesson_id || null) !== (initial!.lesson_id || null))
        throw new ApiError('任务不属于当前课程或课时。', 404, 'course_task_not_found')
      return task
    },
    initialData: initial || undefined,
    enabled: !!initial,
    staleTime: 0,
    gcTime: 0,
    retry: false,
    refetchOnMount: 'always',
    refetchInterval: (state) => {
      const current = state.state.data
      const settle = settleStateRef.current
      if (settle.active && !settle.expired)
        return current && ['failed', 'cancelled'].includes(current.status) ? 2000 : false
      if (!courseTaskPending(current)) return false
      // SSE 流存活时降为保险刷新，connecting/closed/polling 态保持原频率。
      return streamStateRef.current === 'streaming' ? 30_000 : 2500
    },
    refetchIntervalInBackground: false,
  })
  const task = query.data || initial
  const settle = useSettleWatch(task, () => {
    // 调和收尾完成：业务记录（课程/课时/进度）可能已更新，做一次最终刷新。
    if (!task) return
    void client.invalidateQueries({ queryKey: courseKeys.course(identity, courseId) })
    void client.invalidateQueries({ queryKey: courseKeys.progress(identity, courseId) })
    void client.invalidateQueries({ queryKey: courseKeys.lists(identity) })
    if (task.lesson_id)
      void client.invalidateQueries({
        queryKey: courseKeys.lesson(identity, courseId, task.lesson_id),
      })
  })
  settleStateRef.current = settle
  const handleTaskEvent = (event: TaskEvent) => {
    if (!initial?.task_id || event.type === 'reset' || event.type === 'source_revoked') return
    const { payload } = event
    client.setQueryData<CourseTaskView>(queryKey, (current) => {
      if (!current || current.task_id !== initial.task_id) return current
      return {
        ...current,
        status: payload.status as CourseTaskView['status'],
        stage: payload.stage || payload.status,
        error_code: payload.error_code ?? current.error_code,
        business_settled: payload.business_settled,
      }
    })
    if (['completed', 'failed', 'cancelled'].includes(event.type))
      void client.invalidateQueries({ queryKey })
  }
  const streamState = useTaskEvents({
    path: initial?.task_id ? `/courses/tasks/${initial.task_id}/events` : undefined,
    taskId: initial?.task_id,
    enabled: !!initial?.task_id && (courseTaskPending(task) || settle.active),
    onEvent: handleTaskEvent,
    onResume: () => void client.invalidateQueries({ queryKey }),
  })
  streamStateRef.current = streamState
  useEffect(() => {
    if (!task || courseTaskPending(task)) return
    const terminal = `${task.task_id}:${task.status}`
    if (settled.current === terminal) return
    settled.current = terminal
    void client.invalidateQueries({ queryKey: courseKeys.course(identity, courseId) })
    void client.invalidateQueries({ queryKey: courseKeys.progress(identity, courseId) })
    void client.invalidateQueries({ queryKey: courseKeys.lists(identity) })
    if (task.lesson_id)
      void client.invalidateQueries({
        queryKey: courseKeys.lesson(identity, courseId, task.lesson_id),
      })
  }, [task, client, identity, courseId])
  const cancel = () => {
    if (!task || !courseTaskPending(task)) return
    void operation.run(
      'cancel',
      (signal) => coursesApi.cancelTask(task.task_id, signal),
      (result) => {
        client.setQueryData(queryKey, result)
      },
    )
  }
  return {
    task,
    query,
    cancel,
    cancelling: operation.pending !== null,
    cancelError: operation.error,
    settling: settle.active,
  }
}
