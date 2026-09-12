import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, request, requestDownload, setCsrfToken } from './http'

afterEach(() => {
  vi.unstubAllGlobals()
  setCsrfToken(null)
})

describe('same-origin API boundary', () => {
  it('sends the cookie, CSRF token and idempotency key without storing credentials', async () => {
    let sent: RequestInit | undefined
    let url = ''
    vi.stubGlobal('fetch', async (input: string, options: RequestInit) => {
      url = input
      sent = options
      return new Response(JSON.stringify({ code: 0, message: 'ok', data: { task_id: 'task-1' } }), {
        status: 202,
      })
    })
    setCsrfToken('csrf-test')
    const result = await request('/quiz/generate/async', {
      method: 'POST',
      data: { user_input: '集合' },
      idempotencyKey: 'request-1',
    })
    expect(result).toEqual({ task_id: 'task-1' })
    expect(url).toBe('/api/v1/quiz/generate/async')
    expect(sent?.credentials).toBe('include')
    expect(new Headers(sent?.headers).get('X-CSRF-Token')).toBe('csrf-test')
    expect(new Headers(sent?.headers).get('Idempotency-Key')).toBe('request-1')
    expect(localStorage.length).toBe(0)
  })

  it('rejects a business error even when HTTP succeeds', async () => {
    vi.stubGlobal(
      'fetch',
      async () =>
        new Response(
          JSON.stringify({
            code: 4091,
            message: '资料版本已更新',
            error_code: 'STALE_CATALOG',
            data: null,
          }),
        ),
    )
    await expect(request('/knowledge/documents')).rejects.toMatchObject({
      status: 200,
      code: 'STALE_CATALOG',
      message: '资料版本已更新',
    })
  })

  it('rejects an HTTP error even when its body claims success', async () => {
    vi.stubGlobal(
      'fetch',
      async () => new Response(JSON.stringify({ code: 0, data: null }), { status: 503 }),
    )
    await expect(request('/user/profile')).rejects.toBeInstanceOf(ApiError)
  })

  it('does not set a multipart boundary for browser File uploads', async () => {
    let sent: RequestInit | undefined
    vi.stubGlobal('fetch', async (_input: string, options: RequestInit) => {
      sent = options
      return new Response(JSON.stringify({ code: 0, data: { doc_id: 'doc-1' } }))
    })
    const form = new FormData()
    form.append('file', new File(['text'], '课程.txt'))
    await request('/knowledge/documents', { method: 'POST', data: form })
    expect(new Headers(sent?.headers).has('Content-Type')).toBe(false)
    expect(sent?.body).toBe(form)
  })

  it('refuses an absolute URL so private cookies never go to an arbitrary host', async () => {
    await expect(request('https://invalid.example/api')).rejects.toThrow('同源')
  })

  it('announces session expiration on a protected request', async () => {
    let expired = false
    const listener = () => {
      expired = true
    }
    window.addEventListener('session-expired', listener)
    vi.stubGlobal(
      'fetch',
      async () =>
        new Response(JSON.stringify({ code: 4010, message: '登录已失效', data: null }), {
          status: 401,
        }),
    )
    await expect(request('/user/profile')).rejects.toMatchObject({ status: 401 })
    expect(expired).toBe(true)
    window.removeEventListener('session-expired', listener)
  })

  it('treats a rejected migration code as an authentication attempt, not session expiry', async () => {
    const expired = vi.fn()
    window.addEventListener('session-expired', expired)
    vi.stubGlobal(
      'fetch',
      async () =>
        new Response(JSON.stringify({ code: 4010, message: '账号或凭证无效', data: null }), {
          status: 401,
        }),
    )
    try {
      await expect(
        request('/auth/bind', { method: 'POST', data: { code: 'expired-code' } }),
      ).rejects.toMatchObject({ status: 401 })
      expect(expired).not.toHaveBeenCalled()
    } finally {
      window.removeEventListener('session-expired', expired)
    }
  })

  it('does not expire a newer login when an old request returns an unauthorized response', async () => {
    let resolveOld!: (response: Response) => void
    const expired = vi.fn()
    window.addEventListener('session-expired', expired)
    vi.stubGlobal(
      'fetch',
      () =>
        new Promise<Response>((resolve) => {
          resolveOld = resolve
        }),
    )
    setCsrfToken('old-session')
    const pending = request('/user/profile')
    setCsrfToken('new-session')
    resolveOld(
      new Response(JSON.stringify({ code: 4010, message: '旧会话已撤销', data: null }), {
        status: 401,
      }),
    )
    await expect(pending).rejects.toMatchObject({ status: 401 })
    expect(expired).not.toHaveBeenCalled()
    window.removeEventListener('session-expired', expired)
  })

  it('checks export authorization before returning a downloadable file', async () => {
    vi.stubGlobal(
      'fetch',
      async () =>
        new Response(
          JSON.stringify({
            code: 4040,
            error_code: 'source_revoked',
            message: '来源授权已撤销',
            data: null,
          }),
          { status: 404, headers: { 'Content-Type': 'application/json' } },
        ),
    )
    await expect(
      requestDownload('/eval/runs/run-1/export?format=jsonl', 'evaluation.jsonl'),
    ).rejects.toMatchObject({ status: 404, code: 'source_revoked', message: '来源授权已撤销' })
  })

  it('downloads only same-origin exports and retains the server file name', async () => {
    const fetch = vi.fn(
      async () =>
        new Response('{"sample_id":"sample-1"}\n', {
          headers: {
            'Content-Type': 'application/x-ndjson',
            'Content-Disposition': 'attachment; filename="evaluation.jsonl"',
          },
        }),
    )
    vi.stubGlobal('fetch', fetch)
    const download = await requestDownload('/eval/runs/run-1/export?format=jsonl', 'fallback.jsonl')
    expect(download.filename).toBe('evaluation.jsonl')
    const content = download.blob.size
    expect(content).toBe(25)
    expect(fetch).toHaveBeenCalledWith(
      '/api/v1/eval/runs/run-1/export?format=jsonl',
      expect.objectContaining({ credentials: 'include' }),
    )
    await expect(
      requestDownload('https://invalid.example/export', 'evaluation.jsonl'),
    ).rejects.toThrow('同源')
    expect(fetch).toHaveBeenCalledTimes(1)
  })
})
