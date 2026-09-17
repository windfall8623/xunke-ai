import { act, fireEvent, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiFailure, json, session } from '../test/fixtures'
import { qaAnswer, qaDocument, qaMessages, qaSession } from '../test/qaFixtures'
import { renderApp } from '../test/renderApp'

function api(messages = qaMessages, revoked = false) {
  return (path: string) => {
    if (path.endsWith('/auth/session')) return json(session)
    if (path.endsWith('/knowledge/documents')) return json({ items: [qaDocument], total: 1 })
    if (path.includes('/qa/sessions?'))
      return json({ items: [qaSession], total: 1, page: 1, page_size: 20 })
    if (path.endsWith('/qa/sessions/session-1'))
      return json(revoked ? { ...qaSession, source_status: 'revoked', scope: null } : qaSession)
    if (path.includes('/messages')) return json({ items: messages, has_more: false })
    return apiFailure(404, '测试接口不存在')
  }
}

const originalScrollIntoView = Object.getOwnPropertyDescriptor(
  HTMLElement.prototype,
  'scrollIntoView',
)

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  if (originalScrollIntoView)
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', originalScrollIntoView)
  else Reflect.deleteProperty(HTMLElement.prototype, 'scrollIntoView')
})

describe('QA reading and setup UX', () => {
  it('puts material and chapter choices before the optional title in DOM and keyboard order', async () => {
    renderApp('/qa?doc_id=doc-1', api())
    expect(await screen.findByRole('heading', { name: '资料问答', level: 1 })).toBeVisible()
    const chapter = await screen.findByRole('checkbox', { name: '第一节 集合基础' })
    const title = screen.getByLabelText('会话标题（选填）')
    expect(chapter.compareDocumentPosition(title) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    const checkboxes = screen.getAllByRole('checkbox')
    checkboxes[checkboxes.length - 1].focus()
    await userEvent.tab()
    expect(title).toHaveFocus()
    expect(screen.queryByRole('button', { name: '返回最新消息' })).not.toBeInTheDocument()
  })

  it.each([false, true])(
    'jumps only on request and respects reduced motion: %s',
    async (reduced) => {
      let latestBottom = 1800
      const scrollIntoView = vi.fn()
      vi.stubGlobal(
        'matchMedia',
        vi.fn(() => ({ matches: reduced })),
      )
      const original = HTMLElement.prototype.getBoundingClientRect
      vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (
        this: HTMLElement,
      ) {
        if (this.classList.contains('qa-composer-dock'))
          return { top: 500, bottom: 750, height: 250 } as DOMRect
        if (this.classList.contains('qa-message'))
          return { top: 100, bottom: latestBottom, height: latestBottom - 100 } as DOMRect
        return original.call(this)
      })
      Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
        configurable: true,
        value: scrollIntoView,
      })
      const { client } = renderApp('/qa/session-1', api())
      await screen.findByText(qaAnswer.blocks[0].text)
      const jump = await screen.findByRole('button', { name: '返回最新消息' })
      expect(scrollIntoView).not.toHaveBeenCalled()
      await act(async () => {
        await client.invalidateQueries()
      })
      fireEvent.scroll(window)
      expect(scrollIntoView).not.toHaveBeenCalled()
      jump.focus()
      await userEvent.keyboard('{Enter}')
      expect(scrollIntoView).toHaveBeenCalledWith({
        block: 'end',
        behavior: reduced ? 'auto' : 'smooth',
      })
      expect(screen.getByRole('log', { name: '会话消息' }).lastElementChild).toHaveFocus()
      latestBottom = 450
      fireEvent.scroll(window)
      await waitFor(() =>
        expect(screen.queryByRole('button', { name: '返回最新消息' })).not.toBeInTheDocument(),
      )
      expect(scrollIntoView).toHaveBeenCalledTimes(1)
    },
  )

  it.each([false, true])(
    'does not offer a jump for empty or revoked conversations: %s',
    async (revoked) => {
      renderApp('/qa/session-1', api([], revoked))
      await screen.findByLabelText('你的问题')
      fireEvent.scroll(window)
      expect(screen.queryByRole('button', { name: '返回最新消息' })).not.toBeInTheDocument()
    },
  )
})
