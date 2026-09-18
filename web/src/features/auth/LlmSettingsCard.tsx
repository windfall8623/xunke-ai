import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useLocation } from 'react-router-dom'
import { useIdentityKey } from '../../app/AuthProvider'
import { Dialog } from '../../components/Dialog'
import { ErrorNotice, Loading } from '../../components/ui'
import { api, type LlmProvider, type LlmSettings } from '../../services/api'
import { ApiError } from '../../services/http'

const providers: Record<LlmProvider, { name: string; url: string }> = {
  deepseek: { name: 'DeepSeek', url: 'https://api.deepseek.com' },
  anthropic: { name: 'Anthropic', url: 'https://api.anthropic.com' },
  openai_compatible: { name: 'OpenAI 兼容', url: 'https://api.openai.com/v1' },
}

function initialFields(data: LlmSettings) {
  return data.configured
    ? { provider: data.provider || 'deepseek', model: data.model || '', url: data.base_url || '' }
    : { provider: 'deepseek', model: '', url: providers.deepseek.url }
}

export function LlmSettingsCard() {
  const identity = useIdentityKey()
  const { hash } = useLocation()
  const anchor = useRef<HTMLElement>(null)
  const settings = useQuery({
    queryKey: [identity, 'llm-settings'],
    queryFn: ({ signal }) => api.llmSettings(signal),
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  })
  useEffect(() => {
    if (hash === '#llm-settings') {
      anchor.current?.scrollIntoView?.({ block: 'start' })
      anchor.current?.focus({ preventScroll: true })
    }
  }, [hash])
  return (
    <section
      ref={anchor}
      id="llm-settings"
      tabIndex={-1}
      className="card llm-settings-card"
      aria-labelledby="llm-settings-title"
    >
      <div className="section-line">
        <h2 id="llm-settings-title">模型设置</h2>
        {settings.data && (
          <span className="badge">
            {settings.data.configured
              ? '使用个人模型'
              : settings.data.source === 'system'
                ? '使用系统模型'
                : '待配置'}
          </span>
        )}
      </div>
      <p className="muted">
        普通用户与评测人员的学习任务使用个人模型；管理员账户统一使用平台配置的系统模型。
      </p>
      <p className="tiny muted">
        个人模型调用平台不计费，费用由对应服务商收取。保存时的连接验证也会调用服务商。向量嵌入（Embedding）与重排序（Reranking）仍使用系统服务。
      </p>
      {settings.isPending ? (
        <Loading>正在读取模型设置…</Loading>
      ) : settings.isError ? (
        <ErrorNotice
          error="无法读取模型设置，请重新加载后再修改。"
          onRetry={() => void settings.refetch()}
        />
      ) : settings.data.can_use_system ? (
        <div className="notice llm-system-notice">
          <p>管理员模型由平台统一管理，个人中心不保存或切换 API 密钥。</p>
          <p className="tiny muted">
            当前服务商：{settings.data.provider || '未配置'}；模型：{settings.data.model || '未配置'}。
            系统调用按平台预算执行，个人模型不会替代评测模型。
          </p>
        </div>
      ) : (
        <SettingsForm key={identity} initial={settings.data} />
      )}
    </section>
  )
}

function SettingsForm({ initial }: { initial: LlmSettings }) {
  const identity = useIdentityKey()
  const client = useQueryClient()
  const [saved, setSaved] = useState(initial)
  const [fields, setFields] = useState(() => initialFields(initial))
  const [key, setKey] = useState('')
  const [pending, setPending] = useState<'save' | 'delete' | null>(null)
  const [confirming, setConfirming] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const controller = useRef<AbortController | null>(null)
  // Keep credentials out of React Query mutation variables, caches, and browser storage.
  useEffect(() => () => controller.current?.abort(), [])

  function changeProvider(provider: string) {
    setFields((current) => ({
      provider,
      model: provider === saved.provider && saved.configured ? saved.model || '' : '',
      url:
        provider === saved.provider && saved.configured
          ? saved.base_url || ''
          : provider === current.provider
            ? current.url
            : providers[provider as LlmProvider].url,
    }))
    setKey('')
    setError('')
    setNotice('')
  }

  async function perform(action: 'save' | 'delete') {
    if (controller.current) return
    const request = new AbortController()
    controller.current = request
    setPending(action)
    setError('')
    setNotice('')
    const apiKey = key.trim()
    setKey('')
    try {
      const result =
        action === 'delete'
          ? await api.deleteLlmSettings(request.signal)
          : await api.saveLlmSettings(
              {
                provider: fields.provider as LlmProvider,
                model: fields.model.trim(),
                base_url: fields.url.trim(),
                ...(apiKey ? { api_key: apiKey } : {}),
              },
              request.signal,
            )
      if (request.signal.aborted) return
      client.setQueryData([identity, 'llm-settings'], result)
      setSaved(result)
      setFields(initialFields(result))
      setConfirming(false)
      setNotice(action === 'save' ? '连接验证通过，模型设置已保存。' : '个人模型配置已移除。')
    } catch (cause) {
      if (request.signal.aborted) return
      // Never render upstream messages here: providers may echo credentials or request details.
      const rejected =
        cause instanceof ApiError && cause.code.toString().toLowerCase() === 'user_llm_failed'
      setError(
        rejected
          ? '连接验证未通过，未保存本次修改。请检查模型、服务地址和密钥后重试；如需更换密钥，请重新输入。'
          : action === 'save'
            ? '无法确认保存结果。请检查网络、模型、服务地址及密钥，重新加载设置确认；如需更换密钥，请重新输入。'
            : '移除失败，请检查网络后重试。',
      )
    } finally {
      if (!request.signal.aborted) {
        controller.current = null
        setPending(null)
      }
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    if (supported && fields.model.trim() && fields.url.trim() && (!keyRequired || key.trim()))
      void perform('save')
  }

  const supported = Object.hasOwn(providers, fields.provider)
  const configurationChanged = !saved.configured || fields.provider !== saved.provider ||
    fields.model.trim() !== saved.model || fields.url.trim().replace(/\/+$/, '') !== saved.base_url
  const keyRequired = configurationChanged || !saved.api_key_hint
  return (
    <>
      <form className="stack-form" onSubmit={submit} autoComplete="off" aria-busy={!!pending}>
        <fieldset className="llm-settings-fields" disabled={!!pending}>
          <div className="llm-settings-grid">
            <label>
              服务商
              <select
                value={fields.provider}
                onChange={(event) => changeProvider(event.target.value)}
              >
                {!supported && (
                  <option value={fields.provider}>{fields.provider}（请选择受支持的服务商）</option>
                )}
                {Object.entries(providers).map(([value, provider]) => (
                  <option key={value} value={value}>
                    {provider.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              模型名称
              <input
                value={fields.model}
                onChange={(event) => setFields({ ...fields, model: event.target.value })}
                placeholder="输入服务商提供的模型名称"
                required
                maxLength={128}
                spellCheck={false}
              />
            </label>
          </div>
          <label>
            服务地址（Base URL）
            <input
              type="url"
              value={fields.url}
              onChange={(event) => setFields({ ...fields, url: event.target.value })}
              required
              maxLength={512}
              spellCheck={false}
              aria-describedby="llm-endpoint-help"
            />
          </label>
          <p id="llm-endpoint-help" className="tiny muted">
            填写可信服务商的 API 基础地址，不要在地址中包含密钥。仅在选择新服务商时预填默认地址。
          </p>
          <label>
            API 密钥
            <input
              type="password"
              value={key}
              onChange={(event) => setKey(event.target.value)}
              autoComplete="new-password"
              spellCheck={false}
              minLength={8}
              maxLength={512}
              required={keyRequired}
              aria-describedby="llm-key-help"
              placeholder={keyRequired ? '输入你的 API 密钥' : '留空保留已保存的密钥'}
            />
          </label>
          <p id="llm-key-help" className="tiny muted">
            {saved.configured
              ? `已保存密钥${saved.api_key_hint ? `，末四位 ${saved.api_key_hint.replace(/^\*+/, '')}` : '，需要重新填写'}。${keyRequired ? '更换配置或密钥不可用时，请重新输入密钥。' : '留空保留原密钥。'}`
              : '首次配置需要密钥。'}
            密钥不会回填，提交后清空输入，也不会写入浏览器存储。保存会进行限时连接验证，验证失败不会覆盖原配置。
          </p>
        </fieldset>
        {pending === 'save' && <Loading>正在验证模型连接，通过后保存…</Loading>}
        {notice && (
          <div className="notice success" role="status">
            {notice}
          </div>
        )}
        {!confirming && (
          <ErrorNotice
            error={error}
            onRetry={error ? async () => {
              const result = await client.fetchQuery({
                queryKey: [identity, 'llm-settings'],
                queryFn: ({ signal }) => api.llmSettings(signal),
                staleTime: 0,
              }).catch(() => null)
              if (result && !controller.current) {
                setSaved(result)
                setFields(initialFields(result))
                setKey('')
                setError('')
              }
            } : undefined}
          />
        )}
        <div className="button-row">
          <button
            className="button primary"
            disabled={
              !!pending ||
              !supported ||
              !fields.model.trim() ||
              !fields.url.trim() ||
              (keyRequired && !key.trim())
            }
          >
            {pending === 'save' ? '正在验证并保存…' : '验证并保存'}
          </button>
          {saved.configured && (
            <button
              type="button"
              className="button secondary"
              disabled={!!pending}
              onClick={() => {
                setError('')
                setConfirming(true)
              }}
            >
              移除个人配置
            </button>
          )}
        </div>
      </form>
      {confirming && (
        <Dialog
          title="移除个人模型配置？"
          onClose={() => {
            if (!pending) setConfirming(false)
          }}
        >
          <p>移除后将无法使用 AI 生成功能，直到重新配置个人模型。</p>
          <p className="muted">已保存的个人密钥也会移除，此操作不会删除学习记录。</p>
          <ErrorNotice error={error} />
          <div className="button-row">
            <button
              type="button"
              className="button secondary"
              disabled={!!pending}
              onClick={() => setConfirming(false)}
            >
              取消
            </button>
            <button
              type="button"
              className="button danger"
              disabled={!!pending}
              onClick={() => void perform('delete')}
            >
              {pending === 'delete' ? '正在移除…' : '确认移除'}
            </button>
          </div>
        </Dialog>
      )}
    </>
  )
}
