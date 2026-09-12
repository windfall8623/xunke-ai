import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AppRoutes } from './router'
import { apiFailure, json, session } from '../test/fixtures'

function mount(handler: (path: string, init: RequestInit) => Response, initial = '/login') {
  vi.stubGlobal('fetch', async (path: string, init: RequestInit = {}) => handler(path, init))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return {
    ...render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[initial]}>
          <AppRoutes />
        </MemoryRouter>
      </QueryClientProvider>,
    ),
    client,
  }
}

afterEach(() => vi.unstubAllGlobals())

describe('recover with an email verification code', () => {
  it('sends a password_reset code and signs in after resetting', async () => {
    const writes: { path: string; data: unknown }[] = []
    let resetDone = false
    mount((path, init) => {
      if (path.endsWith('/auth/capabilities')) return json({ email_registration_enabled: true })
      if (path.endsWith('/auth/session')) return resetDone ? json(session) : apiFailure()
      if (init.method === 'POST') writes.push({ path, data: JSON.parse(init.body as string) })
      if (path.endsWith('/auth/email-code'))
        return json({
          message: '如该邮箱可用于找回密码，验证码将发送至邮箱，请检查收件箱和垃圾邮件',
          retry_after_seconds: 60,
          expires_in_seconds: 600,
        })
      if (path.endsWith('/auth/password/reset')) {
        resetDone = true
        return json(session)
      }
      return apiFailure(404)
    })
    await screen.findByRole('heading', { name: '欢迎回来' })
    await userEvent.click(screen.getByRole('button', { name: '忘记密码？' }))
    expect(await screen.findByRole('heading', { name: '找回账号' })).toBeVisible()
    await userEvent.click(screen.getByRole('button', { name: '用邮箱验证码找回' }))
    await userEvent.type(screen.getByLabelText('注册邮箱'), 'learner@example.test')
    await userEvent.click(screen.getByRole('button', { name: '发送验证码' }))
    await userEvent.type(screen.getByLabelText('邮箱验证码'), '123456')
    await userEvent.type(screen.getByLabelText('新密码'), 'Reset-secret-357!')
    await userEvent.click(screen.getByRole('button', { name: '重设密码' }))
    await waitFor(() =>
      expect(writes.map((write) => write.path)).toEqual([
        '/api/v1/auth/email-code',
        '/api/v1/auth/password/reset',
      ]),
    )
    expect(writes[0].data).toEqual({ email: 'learner@example.test', purpose: 'password_reset' })
    expect(writes[1].data).toEqual({
      account: 'learner@example.test',
      verification_code: '123456',
      new_password: 'Reset-secret-357!',
    })
    // 重置成功即持新会话离开登录页。
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: '重设密码' })).not.toBeInTheDocument(),
    )
  })

  it('keeps the recovery-code method as the default path', async () => {
    mount((path) => {
      if (path.endsWith('/auth/capabilities')) return json({ email_registration_enabled: true })
      return apiFailure(404)
    })
    await screen.findByRole('heading', { name: '欢迎回来' })
    await userEvent.click(screen.getByRole('button', { name: '忘记密码？' }))
    expect(await screen.findByLabelText('恢复码')).toBeVisible()
    expect(screen.getByRole('button', { name: '用邮箱验证码找回' })).toBeVisible()
  })

  it('mentions the email fallback on the registration recovery card', async () => {
    mount((path) => {
      if (path.endsWith('/auth/capabilities')) return json({ email_registration_enabled: true })
      if (path.endsWith('/auth/session')) return apiFailure()
      if (path.endsWith('/auth/email-code'))
        return json({ message: 'ok', retry_after_seconds: 60, expires_in_seconds: 600 })
      if (path.endsWith('/auth/register')) return json({ ...session, recovery_code: 'REGISTER-RECOVERY-ONCE' })
      return apiFailure(404)
    })
    await screen.findByRole('heading', { name: '欢迎回来' })
    await userEvent.click(screen.getByRole('button', { name: '立即注册' }))
    await userEvent.type(screen.getByLabelText('邮箱'), 'new@example.test')
    await userEvent.type(screen.getByLabelText('昵称'), '新同学')
    await userEvent.type(screen.getByLabelText('密码', { exact: true }), 'Strong-secret-357!')
    await userEvent.type(screen.getByLabelText('邮箱验证码'), '654321')
    await userEvent.click(screen.getByRole('button', { name: '注册账号' }))
    expect(await screen.findByRole('heading', { name: '保存你的恢复码' })).toBeVisible()
    expect(screen.getByText(/邮箱验证码找回密码/)).toBeVisible()
  })
})
