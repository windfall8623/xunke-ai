import { Download } from 'lucide-react'
import { useState } from 'react'
import { downloadMarkdown, getCourseExport } from '../../services/courseExports'

export function CourseExportActions({ courseId }: { courseId: string }) {
  const [state, setState] = useState<'idle' | 'working' | 'done' | 'failed'>('idle')
  const [message, setMessage] = useState<string | null>(null)

  async function download() {
    if (state === 'working') return
    setState('working')
    setMessage(null)
    try {
      const view = await getCourseExport(courseId)
      downloadMarkdown(view.filename, view.markdown)
      setState('done')
    } catch (cause) {
      setState('failed')
      setMessage(cause instanceof Error ? cause.message : '导出未完成，请稍后重试')
    }
  }

  return (
    <div className="course-export-actions">
      <button type="button" className="button secondary" disabled={state === 'working'} onClick={() => void download()}>
        <Download size={16} />
        {state === 'working' ? '正在整理…' : state === 'done' ? '已下载' : '导出学习成果'}
      </button>
      <a className="button secondary" href={`/study/courses/${encodeURIComponent(courseId)}/print`} target="_blank" rel="noreferrer">
        打印视图
      </a>
      {message && <p role="alert" className="tiny">{message}</p>}
    </div>
  )
}
