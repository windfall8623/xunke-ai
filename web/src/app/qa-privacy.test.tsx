import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { apiFailure, json, session } from '../test/fixtures'
import { renderApp } from '../test/renderApp'

afterEach(() => vi.unstubAllGlobals())

it('preserves this account’s recoverable questions but removes other accounts and clears them at logout', async () => {
  const ownKey = `qa-submission:${session.user.id}:pending-session`
  const alienKey = 'qa-submission:another-account:pending-session'
  sessionStorage.setItem(ownKey, JSON.stringify({ key: 'stable-key', data: { content: '私有资料问题', scope_revision: 1 } }))
  sessionStorage.setItem(alienKey, 'a different account’s private question')
  sessionStorage.setItem('unrelated-ui-preference', 'compact')
  renderApp('/me', (path) => {
    if (path.endsWith('/auth/session')) return json(session)
    if (path.endsWith('/auth/logout')) return json(null)
    if (path.endsWith('/user/profile')) return json(session.user)
    if (path.includes('/user/history')) return json({ items: [], total: 0, page: 1, page_size: 20 })
    return apiFailure(404)
  })
  const logout = await screen.findByRole('button', { name: '退出登录' })
  expect(sessionStorage.getItem(ownKey)).toContain('stable-key')
  expect(sessionStorage.getItem(alienKey)).toBeNull()
  await userEvent.click(logout)
  await waitFor(() => expect(sessionStorage.getItem(ownKey)).toBeNull())
  expect(sessionStorage.getItem('unrelated-ui-preference')).toBe('compact')
})
