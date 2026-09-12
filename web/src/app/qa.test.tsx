import { act, fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { apiFailure, json, session } from '../test/fixtures'
import { qaAnswer, qaDocument, qaEvidence, qaMessages, qaSession, qaTask } from '../test/qaFixtures'
import { renderApp } from '../test/renderApp'

type Handler = (path: string, init: RequestInit) => Response | Promise<Response> | undefined
function api(handler: Handler = () => undefined) {
  return (path: string, init: RequestInit) => {
    const custom = handler(path, init)
    if (custom) return custom
    if (path.endsWith('/auth/session')) return json(session)
    if (path.endsWith('/knowledge/documents')) return json({ items: [qaDocument], total: 1 })
    if (path.includes('/qa/sessions?'))
      return json({ items: [qaSession], total: 1, page: 1, page_size: 20 })
    if (path.endsWith('/qa/sessions/session-1')) return json(qaSession)
    if (path.includes('/qa/sessions/session-1/messages'))
      return json({ items: qaMessages, has_more: false, next_before: null })
    return apiFailure(404, '测试接口不存在')
  }
}

describe('knowledge QA', () => {
  it('opens ready document entry, keeps its selection, and creates a chapter-scoped session', async () => {
    const creations: unknown[] = []
    renderApp(
      '/knowledge',
      api((path, init) => {
        if (path.endsWith('/qa/sessions') && init.method === 'POST') {
          creations.push(JSON.parse(init.body as string))
          return json(qaSession, 201)
        }
      }),
    )
    await userEvent.click(await screen.findByRole('link', { name: '向这份资料提问' }))
    expect(await screen.findByRole('heading', { name: '新建资料问答' })).toBeVisible()
    expect(screen.getByRole('checkbox', { name: qaDocument.file_name })).toBeChecked()
    await userEvent.click(screen.getByRole('checkbox', { name: '第一节 集合基础' }))
    await userEvent.type(screen.getByLabelText('会话标题（选填）'), '集合学习')
    await userEvent.click(screen.getByRole('button', { name: '创建会话' }))
    expect(await screen.findByRole('heading', { name: '集合学习' })).toBeVisible()
    expect(creations).toEqual([
      {
        title: '集合学习',
        scope: {
          type: 'selected_documents',
          documents: [
            {
              doc_id: 'doc-1',
              section_catalog_revision: 'parse-1',
              section_ids: ['parse-1:section-1'],
            },
          ],
        },
      },
    ])
  })

  it('restores an active task, disables another question, then publishes the polled answer', async () => {
    let completed = false
    let taskReads = 0
    renderApp(
      '/qa/session-1',
      api((path) => {
        if (path.endsWith('/qa/sessions/session-1'))
          return json({ ...qaSession, active_task_id: completed ? null : 'task-1' })
        if (path.includes('/messages'))
          return json({
            items: completed ? qaMessages : [qaMessages[0]],
            has_more: false,
            next_before: null,
          })
        if (path.endsWith('/qa/tasks/task-1')) {
          taskReads++
          return json(
            completed
              ? { ...qaTask, status: 'completed', stage: 'completed', answer: qaAnswer }
              : qaTask,
          )
        }
      }),
    )
    expect(await screen.findByText('正在排队')).toBeVisible()
    expect(screen.getByRole('button', { name: '发送问题' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '更改范围' })).toBeDisabled()
    completed = true
    await waitFor(() => expect(screen.getByText(qaAnswer.blocks[0].text)).toBeVisible(), {
      timeout: 4500,
    })
    expect(taskReads).toBeGreaterThan(1)
    await waitFor(() => expect(screen.getByLabelText('你的问题')).toBeEnabled())
  })

  it('renders answer text safely, reads the exact cited source, copies it, and records opt-in feedback', async () => {
    const copied = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText: copied },
      configurable: true,
    })
    const unsafe = '<img src=x onerror=alert(1)> 是资料中的字面内容。'
    const feedback: unknown[] = []
    renderApp(
      '/qa/session-1',
      api((path, init) => {
        if (path.includes('/messages'))
          return json({
            items: [
              qaMessages[0],
              {
                ...qaMessages[1],
                answer: { ...qaAnswer, blocks: [{ ...qaAnswer.blocks[0], text: unsafe }] },
              },
            ],
            has_more: false,
          })
        if (path.endsWith('/evidence/evidence-1')) return json(qaEvidence)
        if (path.endsWith('/feedback')) {
          feedback.push(JSON.parse(init.body as string))
          return json({ feedback_id: 'feedback-1' })
        }
      }),
    )
    expect(await screen.findByText(unsafe)).toBeVisible()
    expect(document.querySelector('img[src="x"]')).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: /查看引用 1/ }))
    const drawer = await screen.findByRole('dialog', { name: '引用原文' })
    expect(await within(drawer).findByText(qaEvidence.excerpt)).toBeVisible()
    expect(within(drawer).getByText(/第一章.*第一节 集合基础/)).toBeVisible()
    expect(within(drawer).getByText(/第 2 页/)).toBeVisible()
    await userEvent.click(within(drawer).getByRole('button', { name: '关闭引用原文' }))
    await userEvent.click(screen.getByRole('button', { name: '复制回答' }))
    expect(copied).toHaveBeenCalledWith(unsafe)
    await userEvent.click(screen.getByRole('button', { name: '有帮助' }))
    const form = screen.getByRole('dialog', { name: '回答反馈' })
    const consent = within(form).getByRole('checkbox', { name: /允许将本轮问答用于评测改进/ })
    expect(consent).not.toBeChecked()
    await userEvent.click(consent)
    await userEvent.click(within(form).getByRole('button', { name: '提交反馈' }))
    expect(await screen.findByText('反馈已保存')).toBeVisible()
    expect(feedback).toEqual([{ rating: 'helpful', comment: '', evaluation_consent: true }])
  })

  it('reuses an idempotency key after an unknown network result and uses a new key for terminal failure', async () => {
    const attempts: Array<{ key: string | null; body: unknown }> = []
    renderApp(
      '/qa/session-1',
      api((path, init) => {
        if (path.includes('/messages') && init.method === 'POST') {
          attempts.push({
            key: new Headers(init.headers).get('Idempotency-Key'),
            body: JSON.parse(init.body as string),
          })
          if (attempts.length === 1)
            return Promise.reject(new TypeError('Connection lost after commit'))
          return json(
            {
              ...qaTask,
              task_id: `task-${attempts.length}`,
              status: 'failed',
              stage: 'generation',
              error_code: 'PROVIDER_UNAVAILABLE',
              error_message: '回答服务暂不可用',
            },
            202,
          )
        }
      }),
    )
    const input = await screen.findByLabelText('你的问题')
    await userEvent.type(input, '重复元素如何处理？{Enter}')
    expect(await screen.findByText(/提交结果尚未确认/)).toBeVisible()
    expect(input).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: '重试确认提交' }))
    expect(await screen.findByText('模型服务暂时不可达，请稍后重试。')).toBeVisible()
    await userEvent.click(screen.getByRole('button', { name: '重试这个问题' }))
    await waitFor(() => expect(attempts).toHaveLength(3))
    expect(attempts[0].key).toBeTruthy()
    expect(attempts[1]).toEqual(attempts[0])
    expect(attempts[2].key).not.toBe(attempts[0].key)
    expect(attempts[2].body).toEqual(attempts[0].body)
  })

  it('cancels an active follow-up and preserves completed history', async () => {
    let cancelled = false
    renderApp(
      '/qa/session-1',
      api((path) => {
        if (path.endsWith('/qa/sessions/session-1'))
          return json({ ...qaSession, active_task_id: cancelled ? null : 'task-2' })
        if (path.endsWith('/qa/tasks/task-2/cancel')) {
          cancelled = true
          return json({ ...qaTask, task_id: 'task-2', status: 'cancelled' })
        }
        if (path.endsWith('/qa/tasks/task-2'))
          return json({
            ...qaTask,
            task_id: 'task-2',
            status: cancelled ? 'cancelled' : 'running',
            stage: 'retrieving',
          })
      }),
    )
    expect(await screen.findByText('正在检索资料')).toBeVisible()
    await userEvent.click(screen.getByRole('button', { name: '取消回答' }))
    expect(await screen.findByText('已取消本次回答')).toBeVisible()
    expect(screen.getByText(qaAnswer.blocks[0].text)).toBeVisible()
    expect(screen.getByLabelText('你的问题')).toBeEnabled()
  })

  it('paginates sessions and prepends older history without dropping the current answer', async () => {
    renderApp(
      '/qa/session-1',
      api((path) => {
        if (path.includes('/qa/sessions?')) {
          const second = new URL(path, 'http://test').searchParams.get('page') === '2'
          return json({
            items: second
              ? [{ ...qaSession, session_id: 'session-21', title: '更早的会话' }]
              : [qaSession],
            total: 21,
            page: second ? 2 : 1,
            page_size: 20,
          })
        }
        if (path.includes('/messages')) {
          const older = new URL(path, 'http://test').searchParams.has('before_sequence')
          return json(
            older
              ? {
                  items: [
                    { ...qaMessages[0], message_id: 'old-1', sequence: 1, content: '较早的问题' },
                  ],
                  has_more: false,
                  next_before: null,
                }
              : {
                  items: qaMessages.map((m) => ({ ...m, sequence: m.sequence + 10 })),
                  has_more: true,
                  next_before: 11,
                },
          )
        }
      }),
    )
    await userEvent.click(await screen.findByRole('button', { name: '加载更早消息' }))
    expect(await screen.findByText('较早的问题')).toBeVisible()
    expect(screen.getByText(qaAnswer.blocks[0].text)).toBeVisible()
    await userEvent.click(screen.getByRole('button', { name: '下一页会话' }))
    expect(await screen.findByRole('link', { name: /更早的会话/ })).toBeVisible()
  })

  it('sends the expected scope revision and refreshes after a concurrent range update', async () => {
    const updates: unknown[] = []
    let currentRevision = 1
    renderApp(
      '/qa/session-1',
      api((path, init) => {
        if (path.endsWith('/qa/sessions/session-1'))
          return json({ ...qaSession, scope_revision: currentRevision })
        if (path.endsWith('/scope')) {
          updates.push(JSON.parse(init.body as string))
          if (updates.length === 1) {
            currentRevision = 2
            return apiFailure(409, '范围已由另一页面更新，请重新确认')
          }
          currentRevision = 3
          return json({ ...qaSession, scope_revision: 3 })
        }
      }),
    )
    await userEvent.click(await screen.findByRole('button', { name: '更改范围' }))
    await userEvent.click(screen.getByRole('button', { name: '保存范围' }))
    expect(await screen.findByText('范围已由另一页面更新，请重新确认')).toBeVisible()
    await waitFor(() => expect(screen.getAllByText(/范围版本 2/).length).toBeGreaterThan(0))
    await userEvent.click(screen.getByRole('button', { name: '保存范围' }))
    await waitFor(() =>
      expect(screen.queryByRole('dialog', { name: '更改问答范围' })).not.toBeInTheDocument(),
    )
    expect(screen.getByText(/范围版本 3/)).toBeVisible()
    expect(updates).toEqual([
      {
        expected_revision: 1,
        scope: { type: 'selected_documents', documents: [{ doc_id: 'doc-1' }] },
      },
      {
        expected_revision: 2,
        scope: { type: 'selected_documents', documents: [{ doc_id: 'doc-1' }] },
      },
    ])
  })

  it.each([
    ['insufficient_evidence', '资料不足'],
    ['conflicting_sources', '资料存在冲突'],
    ['needs_clarification', '需要澄清'],
    ['partial', '部分回答'],
  ])(
    'distinguishes the grounded outcome %s from a technical failure',
    async (answerStatus, label) => {
      renderApp(
        '/qa/session-1',
        api((path) =>
          path.includes('/messages')
            ? json({
                items: [{ ...qaMessages[1], answer: { ...qaAnswer, answer_status: answerStatus } }],
                has_more: false,
              })
            : undefined,
        ),
      )
      expect(await screen.findByText(label)).toBeVisible()
      expect(screen.queryByRole('button', { name: '重试这个问题' })).not.toBeInTheDocument()
    },
  )

  it('clears loaded messages, citations and source text as soon as scope access is revoked', async () => {
    let revoked = false
    const { client } = renderApp(
      '/qa/session-1',
      api((path) => {
        if (path.endsWith('/qa/sessions/session-1'))
          return json(
            revoked
              ? { ...qaSession, title: '资料已不可用', source_status: 'revoked', scope: null }
              : qaSession,
          )
        if (path.includes('/messages') && revoked)
          return json({
            items: qaMessages.map((m) => ({
              ...m,
              status: 'revoked',
              content: '资料已不可用',
              answer: null,
            })),
            has_more: false,
          })
        if (path.endsWith('/evidence/evidence-1'))
          return revoked ? apiFailure(410, '来源已撤权') : json(qaEvidence)
      }),
    )
    await userEvent.click(await screen.findByRole('button', { name: /查看引用 1/ }))
    expect(await screen.findByText(qaEvidence.excerpt)).toBeVisible()
    revoked = true
    await act(async () => {
      await client.invalidateQueries()
    })
    await waitFor(() => expect(screen.queryByText(qaAnswer.blocks[0].text)).not.toBeInTheDocument())
    expect(screen.queryByText(qaMessages[0].content)).not.toBeInTheDocument()
    expect(screen.queryByText(qaEvidence.excerpt)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /查看引用/ })).not.toBeInTheDocument()
    expect(screen.getByLabelText('你的问题')).toBeDisabled()
  })

  it('keeps Shift+Enter as a newline and sends Enter only once while the request is pending', async () => {
    let writes = 0
    const { unmount } = renderApp(
      '/qa/session-1',
      api((path, init) => {
        if (path.includes('/messages') && init.method === 'POST') {
          writes++
          return new Promise<Response>((_resolve, reject) =>
            init.signal?.addEventListener('abort', () =>
              reject(new DOMException('Aborted', 'AbortError')),
            ),
          )
        }
      }),
    )
    const input = await screen.findByLabelText('你的问题')
    await userEvent.type(input, '问题{Shift>}{Enter}{/Shift}第二行')
    expect(input).toHaveValue('问题\n第二行')
    fireEvent.keyDown(input, { key: 'Enter' })
    fireEvent.keyDown(input, { key: 'Enter' })
    await waitFor(() => expect(writes).toBe(1))
    unmount()
  })

  it('purges cached answers on a task 404 and leaves range recovery available', async () => {
    let denied = false
    const { client } = renderApp(
      '/qa/session-1',
      api((path) => {
        if (path.endsWith('/qa/sessions/session-1'))
          return json({ ...qaSession, active_task_id: 'task-2' })
        if (path.endsWith('/qa/tasks/task-2'))
          return denied
            ? apiFailure(404, '来源已撤权')
            : json({ ...qaTask, task_id: 'task-2', status: 'running', stage: 'generating' })
        if (path.endsWith('/evidence/evidence-1')) return json(qaEvidence)
      }),
    )
    await screen.findByText('正在生成回答')
    await userEvent.click(screen.getByRole('button', { name: /查看引用 1/ }))
    await screen.findByText(qaEvidence.excerpt)
    denied = true
    await act(async () => {
      await client.invalidateQueries({ queryKey: [7, 'qa', 'session-1', 'task'] })
    })
    await waitFor(() => expect(screen.queryByText(qaAnswer.blocks[0].text)).not.toBeInTheDocument())
    expect(screen.queryByText(qaEvidence.excerpt)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '更改范围' })).toBeEnabled()
    const cached = client.getQueriesData({ queryKey: [7, 'qa', 'session-1'] })
    expect(JSON.stringify(cached)).not.toContain(qaAnswer.blocks[0].text)
    expect(JSON.stringify(cached)).not.toContain(qaEvidence.excerpt)
  })

  it('closes a source when its historical turn is revoked while the current scope remains usable', async () => {
    let completed = false
    let revoked = false
    const { client } = renderApp(
      '/qa/session-1',
      api((path) => {
        if (path.endsWith('/qa/sessions/session-1'))
          return json({
            ...qaSession,
            scope_revision: completed ? 2 : 1,
            active_task_id: completed ? null : 'task-1',
          })
        if (path.endsWith('/qa/tasks/task-1')) {
          completed = true
          return json({ ...qaTask, status: 'completed', stage: 'completed', answer: qaAnswer })
        }
        if (path.includes('/messages'))
          return json({
            items: revoked
              ? qaMessages.map((message) => ({
                  ...message,
                  status: 'revoked',
                  content: '资料不可用',
                  answer: null,
                }))
              : qaMessages,
            has_more: false,
          })
        if (path.endsWith('/evidence/evidence-1')) return json(qaEvidence)
      }),
    )
    await waitFor(() => expect(screen.getByLabelText('你的问题')).toBeEnabled())
    await userEvent.click(screen.getByRole('button', { name: /查看引用 1/ }))
    await screen.findByText(qaEvidence.excerpt)
    revoked = true
    await act(async () => {
      await client.invalidateQueries({ queryKey: [7, 'qa', 'session-1', 'messages'] })
    })
    await waitFor(() =>
      expect(screen.queryByRole('dialog', { name: '引用原文' })).not.toBeInTheDocument(),
    )
    expect(screen.queryByText(qaAnswer.blocks[0].text)).not.toBeInTheDocument()
    expect(screen.getByLabelText('你的问题')).toBeEnabled()
    expect(
      JSON.stringify(client.getQueriesData({ queryKey: [7, 'qa', 'session-1', 'task'] })),
    ).not.toContain(qaAnswer.blocks[0].text)
  })

  it('requires a fresh chapter choice if the catalog changes while the scope form is open', async () => {
    let updated = false
    const { client } = renderApp(
      '/qa?doc_id=doc-1',
      api((path) => {
        if (path.endsWith('/knowledge/documents'))
          return json({
            items: [
              updated
                ? {
                    ...qaDocument,
                    section_catalog_revision: 'parse-2',
                    sections: [{ section_id: 'parse-2:section-1', title: '新版集合基础' }],
                  }
                : qaDocument,
            ],
            total: 1,
          })
      }),
    )
    await userEvent.click(await screen.findByRole('checkbox', { name: '第一节 集合基础' }))
    updated = true
    await act(async () => {
      await client.invalidateQueries({ queryKey: [7, 'documents'] })
    })
    await screen.findByRole('checkbox', { name: '新版集合基础' })
    expect(screen.getByRole('button', { name: '创建会话' })).toBeDisabled()
    await userEvent.click(screen.getByRole('checkbox', { name: qaDocument.file_name }))
    await userEvent.click(screen.getByRole('checkbox', { name: qaDocument.file_name }))
    await userEvent.click(screen.getByRole('checkbox', { name: '新版集合基础' }))
    expect(screen.getByRole('button', { name: '创建会话' })).toBeEnabled()
  })
})
