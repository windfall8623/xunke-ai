import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { CheckCircle2, X, XCircle } from 'lucide-react'
import { useAuth } from '../app/AuthProvider'
import { api } from '../services/api'
import type { ApiSchemas } from '../types/api'

type OverviewTask = ApiSchemas['TaskOverviewItem']

type Toast = {
  id: string
  tone: 'success' | 'error'
  text: string
  link?: { to: string; label: string }
}

const TERMINAL = new Set(['completed', 'failed', 'cancelled'])
const TOAST_LIFETIME_MS = 7000

function describeTask(task: OverviewTask): string {
  const course = task.course_title ? `课程《${task.course_title}》` : '课程'
  switch (task.kind) {
    case 'course_outline':
      return `${course}的纲要`
    case 'course_lesson':
      return `${course}的课时${task.title ? `「${task.title}」` : '内容'}`
    case 'quiz':
      return task.title ? `练习「${task.title}」` : '生成的练习'
    case 'report':
      return '练习报告'
    case 'practice_generate':
      return task.title ? `练习「${task.title}」` : '练习内容'
    case 'practice_grade':
      return '讲解评分'
    case 'ingest':
      return task.title ? `资料「${task.title}」` : '资料处理'
    case 'delete':
      return task.title ? `资料「${task.title}」` : '资料删除'
    case 'images':
      return '练习配图'
    default:
      return '后台任务'
  }
}

function targetPath(task: OverviewTask): string | null {
  switch (task.kind) {
    case 'course_outline':
    case 'course_lesson':
      return task.course_id ? `/study/courses/${task.course_id}` : null
    case 'quiz':
      return `/tasks/${task.task_id}`
    case 'report':
      return task.quiz_id ? `/quizzes/${task.quiz_id}/report` : null
    case 'practice_generate':
    case 'practice_grade':
      return `/practice/tasks/${task.task_id}`
    case 'ingest':
    case 'delete':
      return '/knowledge'
    default:
      return null
  }
}

/**
 * 全局任务通知：轮询 /tasks/active，对快照做状态差分，完成/失败时弹出
 * 可点击跳转的 toast。首帧只建立基线；任务详情页就在当前路由时不打扰。
 */
export function TaskNotifications() {
  const { status } = useAuth()
  const location = useLocation()
  const navigate = useNavigate()
  const seen = useRef<Map<string, string> | null>(null)
  const pathname = useRef(location.pathname)
  pathname.current = location.pathname
  const [toasts, setToasts] = useState<Toast[]>([])

  const overview = useQuery({
    queryKey: ['task-overview'],
    queryFn: ({ signal }) => api.taskOverview(signal),
    enabled: status === 'authenticated',
    refetchInterval: 6000,
    refetchIntervalInBackground: false,
    staleTime: 5000,
  })

  useEffect(() => {
    if (status !== 'authenticated') {
      seen.current = null
      setToasts([])
    }
  }, [status])

  useEffect(() => {
    const data = overview.data
    if (!data || status !== 'authenticated') return
    const previous = seen.current
    const tasks = data.tasks ?? []
    const current = new Map<string, string>()
    for (const task of tasks) current.set(task.task_id, task.status)
    const fresh: Toast[] = []
    if (previous) {
      for (const task of tasks) {
        const before = previous.get(task.task_id)
        // 只在"进行中 → 终态"的跃迁上提醒；首帧基线与重复终态都不打扰。
        if (!before || before === task.status || TERMINAL.has(before)) continue
        if (!TERMINAL.has(task.status)) continue
        const link = targetPath(task)
        if (link && (pathname.current === link || pathname.current.includes(task.task_id)))
          continue
        const completed = task.status === 'completed'
        fresh.push({
          id: `${task.task_id}:${task.status}`,
          tone: completed ? 'success' : 'error',
          text: completed
            ? `${describeTask(task)}已准备好`
            : `${describeTask(task)}未完成，可打开查看原因后重试`,
          link: link ? { to: link, label: completed ? '查看' : '打开' } : undefined,
        })
      }
    }
    seen.current = current
    if (fresh.length) setToasts((list) => [...list, ...fresh].slice(-4))
  }, [overview.data, status])

  useEffect(() => {
    if (!toasts.length) return
    const timers = toasts.map((toast) =>
      window.setTimeout(() => {
        setToasts((list) => list.filter((item) => item.id !== toast.id))
      }, TOAST_LIFETIME_MS),
    )
    return () => timers.forEach((timer) => window.clearTimeout(timer))
  }, [toasts])

  if (status !== 'authenticated' || !toasts.length) return null
  return (
    <div className="task-toasts" role="status" aria-live="polite">
      {toasts.map((toast) => (
        <div key={toast.id} className={`task-toast ${toast.tone}`}>
          {toast.tone === 'success' ? <CheckCircle2 size={18} /> : <XCircle size={18} />}
          <div className="task-toast-body">
            <span>{toast.text}</span>
            {toast.link && (
              <button
                type="button"
                className="text-button"
                onClick={() => {
                  setToasts((list) => list.filter((item) => item.id !== toast.id))
                  navigate(toast.link!.to)
                }}
              >
                {toast.link.label}
              </button>
            )}
          </div>
          <button
            type="button"
            className="task-toast-close"
            aria-label="关闭提醒"
            onClick={() => setToasts((list) => list.filter((item) => item.id !== toast.id))}
          >
            <X size={14} />
          </button>
        </div>
      ))}
    </div>
  )
}
