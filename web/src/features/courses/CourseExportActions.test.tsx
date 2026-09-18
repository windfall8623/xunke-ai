import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

const getCourseExport = vi.fn()
const downloadMarkdown = vi.fn()

vi.mock('../../services/courseExports', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../services/courseExports')>()
  return {
    ...actual,
    getCourseExport: (...args: unknown[]) => getCourseExport(...args),
    downloadMarkdown: (...args: unknown[]) => downloadMarkdown(...args),
  }
})

import { CourseExportActions } from './CourseExportActions'

describe('CourseExportActions', () => {
  it('downloads the server-provided filename and markdown as a Blob', async () => {
    getCourseExport.mockResolvedValue({
      filename: 'xunke-learning-course_1.md',
      generated_at: '2026-09-13T00:00:00Z',
      snapshot: {},
      markdown: '# 我的课程 · 学习成果',
    })
    render(<CourseExportActions courseId="course-1" />)
    await userEvent.click(screen.getByRole('link', { name: /打印视图/ }))
    expect(screen.getByRole('link', { name: /打印视图/ })).toHaveAttribute(
      'href', '/study/courses/course-1/print',
    )
    await userEvent.click(screen.getByRole('button', { name: '导出学习成果' }))
    await waitFor(() => expect(downloadMarkdown).toHaveBeenCalled())
    expect(getCourseExport).toHaveBeenCalled()
    expect(getCourseExport.mock.calls[0][0]).toBe('course-1')
    expect(downloadMarkdown.mock.calls[0][0]).toBe('xunke-learning-course_1.md')
    expect(downloadMarkdown.mock.calls[0][1]).toContain('# 我的课程')
    expect(await screen.findByText('已下载')).toBeVisible()
  })

  it('keeps failure retryable without starting any generation', async () => {
    getCourseExport.mockRejectedValue(new Error('网络中断'))
    render(<CourseExportActions courseId="course-1" />)
    await userEvent.click(screen.getByRole('button', { name: '导出学习成果' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('网络中断')
    // 失败后按钮仍可用：只重试只读请求。
    expect(screen.getByRole('button', { name: '导出学习成果' })).toBeEnabled()
  })
})
