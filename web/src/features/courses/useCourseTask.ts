import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'
import { useIdentityKey } from '../../app/AuthProvider'
import { courseKeys, coursesApi, courseTaskPending } from '../../services/courses'
import { ApiError } from '../../services/http'
import type { CourseTaskView } from '../../types/course'
import { useCourseOperation } from './useCourseOperation'

export function useCourseTask(courseId: string, initial?: CourseTaskView | null) {
  const identity = useIdentityKey()
  const client = useQueryClient()
  const operation = useCourseOperation()
  const settled = useRef('')
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
    refetchInterval: (state) => (courseTaskPending(state.state.data) ? 2500 : false),
    refetchIntervalInBackground: false,
  })
  const task = query.data || initial
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
  }
}
