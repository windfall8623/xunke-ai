import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ErrorNotice } from '../components/ui'
import { ApiError } from '../services/http'
import type { LlmSettings } from '../services/api'
import { json, learner, session } from '../test/fixtures'
import { renderApp } from '../test/renderApp'

const empty: LlmSettings = {
  configured: false,
  provider: null,
  model: null,
  base_url: null,
  api_key_hint: null,
  can_use_system: false,
  source: null,
}
const configured: LlmSettings = {
  ...empty,
  configured: true,
  provider: 'openai_compatible',
  model: 'custom-model',
  base_url: 'https://models.example.test/v1',
  api_key_hint: '1234',
  source: 'user',
}
const secret = 'sk-private-test-9876'
function failure(code: string, message = 'Service failed') {
  return new Response(JSON.stringify({ code: 4220, error_code: code, message }), {
    status: 422,
    headers: { 'Content-Type': 'application/json' },
  })
}
function mount(handler: (init: RequestInit) => Response | Promise<Response>, role = 'learner') {
  return renderApp('/me#llm-settings', (path, init) => {
    if (path === '/api/v1/me/llm') return handler(init)
    if (path.endsWith('/auth/session')) return json({ ...session, user: { ...session.user, role } })
    if (path.endsWith('/user/profile'))
      return json({ ...learner, quiz_count: 0, average_accuracy: 0 })
    return json({ items: [], total: 0 })
  })
}
afterEach(() => vi.unstubAllGlobals())

describe('personal model settings', () => {
  it('loads custom metadata, focuses the anchor, and never refills a returned key', async () => {
    const view = mount(() => json({ ...configured, api_key: secret }))
    expect(await screen.findByLabelText('模型名称')).toHaveValue('custom-model')
    expect(screen.getByLabelText('服务地址（Base URL）')).toHaveValue(configured.base_url)
    expect(screen.getByLabelText('API 密钥')).toHaveValue('')
    expect(screen.getByLabelText('API 密钥')).toHaveAttribute('type', 'password')
    expect(screen.getByText(/末四位 1234/)).toBeVisible()
    expect(screen.getByRole('region', { name: '模型设置' })).toHaveFocus()
    expect(
      JSON.stringify(
        view.client
          .getQueryCache()
          .getAll()
          .map((q) => q.state.data),
      ),
    ).not.toContain(secret)
    expect(localStorage.length).toBe(0)
    expect(sessionStorage.length).toBe(0)
  })

  it('keeps a blank key unchanged and preserves a saved endpoint until the provider changes', async () => {
    const writes: unknown[] = []
    mount((init) => {
      if (init.method === 'PUT') writes.push(JSON.parse(init.body as string))
      return json(configured)
    })
    await screen.findByLabelText('API 密钥')
    await userEvent.click(screen.getByRole('button', { name: '验证并保存' }))
    expect(await screen.findByText('连接验证通过，模型设置已保存。')).toBeVisible()
    expect(writes).toEqual([
      { provider: configured.provider, model: configured.model, base_url: configured.base_url },
    ])
    await userEvent.selectOptions(screen.getByLabelText('服务商'), 'anthropic')
    expect(screen.getByLabelText('服务地址（Base URL）')).toHaveValue('https://api.anthropic.com')
    await userEvent.selectOptions(screen.getByLabelText('服务商'), 'openai_compatible')
    expect(screen.getByLabelText('服务地址（Base URL）')).toHaveValue(configured.base_url)
  })

  it('requires a first key and waits for the probe without caching or persisting credentials', async () => {
    let resolve!: (response: Response) => void
    const writes: RequestInit[] = []
    const view = mount((init) => {
      if (init.method !== 'PUT') return json(empty)
      writes.push(init)
      return new Promise<Response>((done) => {
        resolve = done
      })
    })
    await screen.findByLabelText('API 密钥')
    await userEvent.type(screen.getByLabelText('模型名称'), 'deepseek-chat')
    expect(screen.getByRole('button', { name: '验证并保存' })).toBeDisabled()
    await userEvent.type(screen.getByLabelText('API 密钥'), secret)
    await userEvent.click(screen.getByRole('button', { name: '验证并保存' }))
    expect(screen.getByRole('button', { name: '正在验证并保存…' })).toBeDisabled()
    expect(screen.getByLabelText('服务商')).toBeDisabled()
    expect(screen.getByText('正在验证模型连接，通过后保存…')).toBeVisible()
    expect(screen.getByLabelText('API 密钥')).toHaveValue('')
    expect(writes).toHaveLength(1)
    expect(JSON.parse(writes[0].body as string)).toEqual({
      provider: 'deepseek',
      model: 'deepseek-chat',
      base_url: 'https://api.deepseek.com',
      api_key: secret,
    })
    expect(new Headers(writes[0].headers).get('X-CSRF-Token')).toBe('csrf-test')
    expect(view.client.getMutationCache().getAll()).toHaveLength(0)
    await act(async () =>
      resolve(
        json({
          ...configured,
          provider: 'deepseek',
          model: 'deepseek-chat',
          base_url: 'https://api.deepseek.com',
          api_key_hint: '9876',
          api_key: secret,
        }),
      ),
    )
    expect(await screen.findByText('连接验证通过，模型设置已保存。')).toBeVisible()
    expect(
      JSON.stringify(
        view.client
          .getQueryCache()
          .getAll()
          .map((q) => q.state.data),
      ),
    ).not.toContain(secret)
    expect(localStorage.length).toBe(0)
    expect(sessionStorage.length).toBe(0)
    view.unmount()
    mount(() => json(configured))
    expect(await screen.findByLabelText('API 密钥')).toHaveValue('')
  })

  it('rejects a failed probe, leaves saved metadata intact and suppresses echoed secrets', async () => {
    const view = mount((init) =>
      init.method === 'PUT' ? failure('user_llm_failed', secret) : json(configured),
    )
    await screen.findByLabelText('API 密钥')
    await userEvent.type(screen.getByLabelText('API 密钥'), secret)
    await userEvent.click(screen.getByRole('button', { name: '验证并保存' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('连接验证未通过，未保存本次修改')
    expect(screen.queryByText(secret)).not.toBeInTheDocument()
    expect(screen.getByLabelText('API 密钥')).toHaveValue('')
    expect(view.client.getQueryData([learner.id, 'llm-settings'])).toEqual(configured)
    expect(view.client.getMutationCache().getAll()).toHaveLength(0)
  })

  it('allows retry after an initial GET failure and does not present editable defaults on failure', async () => {
    let calls = 0
    mount(() => (++calls === 1 ? failure('unavailable') : json(configured)))
    expect(await screen.findByRole('alert')).toHaveTextContent('无法读取模型设置')
    expect(screen.queryByLabelText('API 密钥')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '重新加载' }))
    expect(await screen.findByLabelText('模型名称')).toHaveValue(configured.model)
    expect(calls).toBe(2)
  })

  it.each(['learner', 'evaluator'])(
    'requires explicit removal confirmation for %s',
    async (role) => {
      let deletes = 0
      mount((init) => {
        if (init.method === 'DELETE') {
          deletes++
          return json(empty)
        }
        return json(configured)
      }, role)
      await userEvent.click(await screen.findByRole('button', { name: '移除个人配置' }))
      expect(deletes).toBe(0)
      const dialog = screen.getByRole('dialog')
      expect(dialog).toHaveTextContent('将无法使用 AI 生成功能')
      await userEvent.click(within(dialog).getByRole('button', { name: '取消' }))
      expect(deletes).toBe(0)
      await userEvent.click(screen.getByRole('button', { name: '移除个人配置' }))
      await userEvent.click(screen.getByRole('button', { name: '确认移除' }))
      expect(await screen.findByText('个人模型配置已移除。')).toBeVisible()
      expect(deletes).toBe(1)
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
      expect(screen.queryByRole('button', { name: '移除个人配置' })).not.toBeInTheDocument()
      expect(screen.getByLabelText('API 密钥')).toBeRequired()
      expect(screen.getByText('待配置')).toBeVisible()
    },
  )

  it('keeps a failed deletion in the confirmation dialog and supports retry', async () => {
    let deletes = 0
    mount((init) =>
      init.method === 'DELETE'
        ? ++deletes === 1
          ? failure('unavailable', secret)
          : json(empty)
        : json(configured),
    )
    await userEvent.click(await screen.findByRole('button', { name: '移除个人配置' }))
    await userEvent.click(screen.getByRole('button', { name: '确认移除' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('移除失败')
    expect(screen.getByRole('dialog')).toBeVisible()
    expect(screen.queryByText(secret)).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '确认移除' }))
    expect(await screen.findByText('个人模型配置已移除。')).toBeVisible()
  })

  it('shows administrator system configuration without personal editing controls', async () => {
    mount(() =>
      json({
        ...configured,
        configured: false,
        can_use_system: true,
        source: 'system',
        api_key_hint: null,
      }), 'admin',
    )
    expect(await screen.findByText('使用系统模型')).toBeVisible()
    expect(screen.queryByLabelText('API 密钥')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('模型名称')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '验证并保存' })).not.toBeInTheDocument()
    expect(screen.getByText(/管理员模型由平台统一管理/)).toBeVisible()
  })

  it('requires a new key for changed configuration and follows server length limits', async () => {
    mount(() => json(configured))
    const name = await screen.findByLabelText('模型名称')
    expect(name).toHaveAttribute('maxlength', '128')
    expect(screen.getByLabelText('服务地址（Base URL）')).toHaveAttribute('maxlength', '512')
    await userEvent.type(name, '-new')
    expect(screen.getByLabelText('API 密钥')).toBeRequired()
    expect(screen.getByRole('button', { name: '验证并保存' })).toBeDisabled()
    await userEvent.type(screen.getByLabelText('API 密钥'), secret)
    expect(screen.getByRole('button', { name: '验证并保存' })).toBeEnabled()
  })

  it('aborts an in-flight save on unmount and does not accept its late result', async () => {
    let signal: AbortSignal | undefined | null
    let resolve!: (value: Response) => void
    const view = mount((init) => {
      if (init.method !== 'PUT') return json(configured)
      signal = init.signal
      return new Promise<Response>((done) => {
        resolve = done
      })
    })
    await userEvent.click(await screen.findByRole('button', { name: '验证并保存' }))
    await waitFor(() => expect(signal).toBeDefined())
    view.unmount()
    expect(signal?.aborted).toBe(true)
    await act(async () => resolve(json({ ...configured, model: 'late-model' })))
    expect(view.client.getQueryData([learner.id, 'llm-settings'])).toEqual(configured)
  })
})

it.each(['llm_configuration_required', 'user_llm_failed', 'USER_LLM_FAILED'])(
  'links shared %s errors to anchored settings with safe guidance',
  (code) => {
    render(<ErrorNotice error={new ApiError(secret, 422, code)} />)
    expect(screen.getByRole('link', { name: '检查模型设置' })).toHaveAttribute(
      'href',
      '/me#llm-settings',
    )
    expect(screen.queryByText(secret)).not.toBeInTheDocument()
  },
)
