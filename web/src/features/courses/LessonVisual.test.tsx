import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { LessonVisualView, visualIsRenderable } from './LessonVisual'

const flow = {
  kind: 'flow' as const, title: '函数调用流程',
  steps: [
    { label: '传入参数', detail: '把值交给函数' },
    { label: '返回结果', detail: '' },
  ],
  fallback_text: '先传参数，函数执行后返回结果。',
}

describe('LessonVisualView', () => {
  it('renders flow steps as escaped text with an accessible fallback', async () => {
    render(<LessonVisualView visual={flow} />)
    expect(screen.getByText('函数调用流程')).toBeVisible()
    expect(screen.getByText('传入参数')).toBeVisible()
    expect(screen.getByText('把值交给函数')).toBeVisible()
    const fallback = screen.getByText('先传参数，函数执行后返回结果。')
    expect(fallback).not.toBeVisible()
    await userEvent.click(screen.getByText('查看文字说明'))
    expect(fallback).toBeVisible()
    expect(document.querySelector('script')).toBeNull()
  })

  it('renders comparisons as a real table with headers', () => {
    render(<LessonVisualView visual={{
      kind: 'comparison', title: '值类型对比',
      columns: ['值类型', '引用类型'], rows: [['直接存值', '存地址']],
      fallback_text: '两者保存的内容不同。',
    }} />)
    expect(screen.getByRole('columnheader', { name: '值类型' })).toBeVisible()
    expect(screen.getByRole('cell', { name: '直接存值' })).toBeVisible()
  })

  it('only accepts known kinds for rendering', () => {
    expect(visualIsRenderable(flow)).toBe(true)
    expect(visualIsRenderable({ kind: 'svg', body: '<svg/>' })).toBe(false)
    expect(visualIsRenderable(null)).toBe(false)
  })
})
