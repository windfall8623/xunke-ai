import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { documentFixture, json, session } from '../test/fixtures'
import { renderApp } from '../test/renderApp'

afterEach(() => vi.unstubAllGlobals())

describe('knowledge workbench', () => {
  it('emphasizes the first upload and compacts it without losing the uploader after success', async () => {
    let uploaded = false
    renderApp('/knowledge', (path, init) => {
      if (path.endsWith('/auth/session')) return json(session)
      if (init.method === 'POST') {
        uploaded = true
        return json(documentFixture, 202)
      }
      return json({ items: uploaded ? [documentFixture] : [], total: uploaded ? 1 : 0 })
    })
    await screen.findByText('从第一份资料开始')
    const upload = screen.getByRole('region', { name: '上传学习资料' })
    expect(upload).toHaveClass('is-empty')
    await userEvent.upload(
      screen.getByLabelText('选择资料文件'),
      new File(['集合基础'], '笔记.txt', { type: 'text/plain' }),
    )
    await screen.findByRole('article', { name: documentFixture.file_name })
    expect(upload).toHaveClass('is-compact')
    expect(within(upload).getByRole('button', { name: '上传资料' })).toBeEnabled()
  })

  it('filters file rows and clears a search without hiding upload or version controls', async () => {
    renderApp('/knowledge', (path) => {
      if (path.endsWith('/auth/session')) return json(session)
      return json({ items: [documentFixture], total: 1 })
    })
    const row = await screen.findByRole('article', { name: documentFixture.file_name })
    expect(within(row).getByRole('link', { name: '向这份资料提问' })).toHaveAttribute(
      'href',
      '/qa?doc_id=doc-1',
    )
    await userEvent.type(screen.getByLabelText('搜索资料'), '不存在')
    expect(screen.queryByRole('article')).not.toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '没有找到相关资料' })).toBeVisible()
    await userEvent.click(screen.getByRole('button', { name: '清除搜索' }))
    expect(screen.getByLabelText('搜索资料')).toHaveValue('')
    const restored = screen.getByRole('article', { name: documentFixture.file_name })
    await userEvent.click(within(restored).getByText('章节与版本'))
    expect(within(restored).getByText('version-1')).toBeVisible()
    expect(within(restored).getByText('第一节 集合基础')).toBeVisible()
  })

  it('preserves reprocessing, replacement and explicit deletion confirmation in file rows', async () => {
    const writes: { path: string; init: RequestInit }[] = []
    let removed = false
    renderApp('/knowledge', (path, init) => {
      if (path.endsWith('/auth/session')) return json(session)
      if (init.method === 'POST' || init.method === 'DELETE') {
        writes.push({ path, init })
        if (init.method === 'DELETE') removed = true
        return json(documentFixture)
      }
      return json({ items: removed ? [] : [documentFixture], total: removed ? 0 : 1 })
    })
    const row = await screen.findByRole('article', { name: documentFixture.file_name })
    await userEvent.click(within(row).getByText('章节与版本'))
    await userEvent.selectOptions(within(row).getByLabelText('处理方式'), 'structure-v1')
    await userEvent.click(within(row).getByRole('button', { name: '重新处理' }))
    await waitFor(() => expect(writes).toHaveLength(1))
    expect(writes[0].path).toMatch(/\/doc-1\/reindex$/)
    expect(JSON.parse(writes[0].init.body as string)).toEqual({ index_profile_id: 'structure-v1' })
    await userEvent.click(within(row).getByRole('button', { name: '替换文件' }))
    const replacement = await screen.findByRole('dialog', {
      name: `替换：${documentFixture.file_name}`,
    })
    await userEvent.upload(
      within(replacement).getByLabelText('选择替换文件'),
      new File(['新版集合'], '新版.txt', { type: 'text/plain' }),
    )
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(writes[1].path).toMatch(/\/doc-1\/versions$/)
    expect(((writes[1].init.body as FormData).get('file') as File).name).toBe('新版.txt')
    await userEvent.click(
      within(row).getByRole('button', { name: `删除 ${documentFixture.file_name}` }),
    )
    await userEvent.click(screen.getByRole('button', { name: '保留资料' }))
    expect(writes).toHaveLength(2)
    await userEvent.click(
      within(row).getByRole('button', { name: `删除 ${documentFixture.file_name}` }),
    )
    await userEvent.click(screen.getByRole('button', { name: '确认删除' }))
    await waitFor(() => expect(screen.queryByRole('article')).not.toBeInTheDocument())
    expect(writes[2].init.method).toBe('DELETE')
    expect(screen.getByRole('region', { name: '上传学习资料' })).toHaveClass('is-empty')
  })
})
