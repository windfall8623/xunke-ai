import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AppRoutes } from './router'
import { apiFailure, json, session } from '../test/fixtures'

function mount(handler: (path: string, init: RequestInit) => Response) {
  vi.stubGlobal('fetch', async (path: string, init: RequestInit = {}) => handler(path, init))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const view = render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/knowledge']}>
        <AppRoutes />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return { ...view, client }
}

afterEach(() => vi.unstubAllGlobals())

describe('conditional legacy account migration', () => {
  it.each([false, null])('hides migration when capability is %s', async (capability) => {
    let requested = false
    mount((path) => {
      if (path.endsWith('/auth/capabilities')) {
        requested = true
        return capability === null ? apiFailure(503) : json({ legacy_link_enabled: capability })
      }
      return apiFailure()
    })
    await screen.findByRole('heading', { name: '欢迎回来' })
    await waitFor(() => expect(requested).toBe(true))
    expect(screen.queryByRole('button', { name: '迁移旧账号' })).not.toBeInTheDocument()
  })

  it('hides a previously enabled entry when refreshing the capability fails', async () => {
    let unavailable = false
    const { client } = mount((path) => {
      if (path.endsWith('/auth/capabilities'))
        return unavailable ? apiFailure(503) : json({ legacy_link_enabled: true })
      return apiFailure()
    })
    expect(await screen.findByRole('button', { name: '迁移旧账号' })).toBeVisible()
    unavailable = true
    await client.invalidateQueries({ queryKey: ['auth-capabilities'] })
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: '迁移旧账号' })).not.toBeInTheDocument(),
    )
  })

  it('redeems the existing code, retains the returned identity and acknowledges recovery once', async () => {
    const writes: { path: string; data: unknown }[] = []
    const migrated = {
      ...session,
      user: { ...session.user, id: 73, nickname: '原微信学习者', total_xp: 246 },
    }
    let signedIn = false
    mount((path, init) => {
      if (path.endsWith('/auth/capabilities')) return json({ legacy_link_enabled: true })
      if (path.endsWith('/auth/session')) return signedIn ? json(migrated) : apiFailure()
      if (init.method === 'POST') writes.push({ path, data: JSON.parse(init.body as string) })
      if (path.endsWith('/auth/bind')) {
        signedIn = true
        return json({ ...migrated, recovery_code: 'MIGRATION-RECOVERY-ONLY-ONCE' })
      }
      if (path.endsWith('/knowledge/documents')) return json({ items: [], total: 0 })
      return apiFailure(404)
    })
    await userEvent.click(await screen.findByRole('button', { name: '迁移旧账号' }))
    await userEvent.type(screen.getByLabelText('原账号', { exact: true }), 'existing-learner')
    await userEvent.type(screen.getByLabelText('一次性迁移码'), 'LEGACY-CODE-FOR-TEST-ONLY')
    await userEvent.type(screen.getByLabelText('密码', { exact: true }), 'Strong-secret-357!')
    await userEvent.click(screen.getByRole('button', { name: '关联并设置网页账号' }))
    expect(await screen.findByRole('heading', { name: '保存你的恢复码' })).toBeVisible()
    expect(writes).toEqual([
      {
        path: '/api/v1/auth/bind',
        data: {
          account: 'existing-learner',
          password: 'Strong-secret-357!',
          code: 'LEGACY-CODE-FOR-TEST-ONLY',
          verification_code: '',
        },
      },
    ])
    await userEvent.click(screen.getByRole('button', { name: '我已保存，开始学习' }))
    expect(await screen.findByRole('heading', { name: '我的资料' })).toBeVisible()
    expect(screen.getByText('原微信学习者')).toBeVisible()
    expect(screen.queryByText('MIGRATION-RECOVERY-ONLY-ONCE')).not.toBeInTheDocument()
    expect(localStorage.length).toBe(0)
    expect(sessionStorage.length).toBe(0)
  })

  it('keeps a rejected migration on the form instead of falling back to account registration', async () => {
    const writes: string[] = []
    mount((path, init) => {
      if (path.endsWith('/auth/capabilities')) return json({ legacy_link_enabled: true })
      if (init.method === 'POST') writes.push(path)
      if (path.endsWith('/auth/bind')) return apiFailure(401, '账号或凭证无效')
      return apiFailure()
    })
    await userEvent.click(await screen.findByRole('button', { name: '迁移旧账号' }))
    await userEvent.type(screen.getByLabelText('原账号', { exact: true }), 'existing-learner')
    await userEvent.type(screen.getByLabelText('一次性迁移码'), 'EXPIRED-CODE-FOR-TEST')
    await userEvent.type(screen.getByLabelText('密码', { exact: true }), 'Strong-secret-357!')
    await userEvent.click(screen.getByRole('button', { name: '关联并设置网页账号' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('账号或凭证无效')
    expect(screen.getByRole('button', { name: '关联并设置网页账号' })).toBeEnabled()
    expect(writes).toEqual(['/api/v1/auth/bind'])
  })
})
