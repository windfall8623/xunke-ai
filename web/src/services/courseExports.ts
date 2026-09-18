import { request } from './http'
import type { ApiSchemas } from '../types/api'

export type CourseExportView = ApiSchemas['CourseExportView']

const segment = encodeURIComponent

export function getCourseExport(courseId: string, signal?: AbortSignal) {
  return request<CourseExportView>(
    `/courses/${segment(courseId)}/export?format=markdown&include_history=false`,
    { signal },
  )
}

/** 下载走应用授权 HTTP；浏览器创建 Blob，正文不进地址栏或 localStorage。 */
export function downloadMarkdown(filename: string, markdown: string) {
  const blob = new Blob([markdown], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
