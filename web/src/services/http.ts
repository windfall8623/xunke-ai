export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public code: string | number,
  ) {
    super(message)
  }
}

let csrfToken: string | null = null
let sessionRevision = 0
export function setCsrfToken(token: string | null) {
  if (csrfToken !== token) sessionRevision++
  csrfToken = token
}

export type RequestOptions = {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  data?: unknown
  signal?: AbortSignal
  idempotencyKey?: string
  timeoutMs?: number
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  if (!/^\/(?!\/)/.test(path) || path.includes('\\'))
    throw new ApiError('API 请求必须使用同源相对路径', 0, 'INVALID_URL')
  const { method = 'GET', data, signal, idempotencyKey, timeoutMs = 30_000 } = options
  const requestSession = sessionRevision
  const headers = new Headers({ Accept: 'application/json' })
  const isForm = data instanceof FormData
  if (data !== undefined && !isForm) headers.set('Content-Type', 'application/json')
  if (method !== 'GET' && csrfToken) headers.set('X-CSRF-Token', csrfToken)
  if (idempotencyKey) headers.set('Idempotency-Key', idempotencyKey)
  const controller = new AbortController()
  const abort = () => controller.abort(signal?.reason)
  signal?.addEventListener('abort', abort, { once: true })
  if (signal?.aborted) abort()
  const timer = setTimeout(
    () => controller.abort(new DOMException('请求超时，请重试', 'TimeoutError')),
    timeoutMs,
  )
  try {
    const response = await fetch(`/api/v1${path}`, {
      method,
      headers,
      credentials: 'include',
      signal: controller.signal,
      body: data === undefined ? undefined : isForm ? data : JSON.stringify(data),
    })
    let body: { code?: number; error_code?: string; message?: string; data?: T }
    try {
      body = await response.json()
    } catch {
      throw new ApiError('服务暂时无法响应，请稍后重试', response.status, 'INVALID_RESPONSE')
    }
    if (!response.ok || body.code !== 0) {
      if (
        (response.status === 401 || body.code === 4010) &&
        requestSession === sessionRevision &&
        !/^\/auth\/(session|login|register|recover|bind|capabilities)$/.test(path)
      ) {
        setCsrfToken(null)
        window.dispatchEvent(new Event('session-expired'))
      }
      throw new ApiError(
        body.message || '请求失败，请稍后重试',
        response.status,
        body.error_code || body.code || 'REQUEST_FAILED',
      )
    }
    return body.data as T
  } catch (error) {
    if (error instanceof ApiError || signal?.aborted) throw error
    if (controller.signal.aborted)
      throw new ApiError('请求超时，刷新可恢复已保存的进度', 0, 'TIMEOUT')
    throw new ApiError('网络连接中断，请检查网络后重试', 0, 'NETWORK_ERROR')
  } finally {
    clearTimeout(timer)
    signal?.removeEventListener('abort', abort)
  }
}

export async function requestDownload(path: string, fallbackFilename: string) {
  if (!/^\/(?!\/)/.test(path) || path.includes('\\'))
    throw new ApiError('API 请求必须使用同源相对路径', 0, 'INVALID_URL')
  const controller = new AbortController()
  const requestSession = sessionRevision
  const timer = setTimeout(() => controller.abort(), 60_000)
  try {
    const response = await fetch(`/api/v1${path}`, {
      credentials: 'include',
      signal: controller.signal,
      headers: { Accept: 'application/x-ndjson,text/csv,text/markdown,text/plain' },
    })
    if (
      !response.ok ||
      /^application\/json(?:;|$)/i.test(response.headers.get('Content-Type') || '')
    ) {
      const body = (await response.json().catch(() => ({}))) as {
        code?: number
        error_code?: string
        message?: string
      }
      if (response.status === 401 && requestSession === sessionRevision) {
        setCsrfToken(null)
        window.dispatchEvent(new Event('session-expired'))
      }
      throw new ApiError(
        body.message || '导出失败，请刷新后重试',
        response.status,
        body.error_code || body.code || 'EXPORT_FAILED',
      )
    }
    const filename =
      /filename="([A-Za-z0-9_.-]+)"/i.exec(
        response.headers.get('Content-Disposition') || '',
      )?.[1] || fallbackFilename
    return { blob: await response.blob(), filename }
  } catch (error) {
    if (error instanceof ApiError) throw error
    if (controller.signal.aborted) throw new ApiError('导出请求超时，请稍后重试', 0, 'TIMEOUT')
    throw new ApiError('网络连接中断，请检查网络后重试', 0, 'NETWORK_ERROR')
  } finally {
    clearTimeout(timer)
  }
}

export function saveDownload({ blob, filename }: { blob: Blob; filename: string }) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.append(anchor)
  anchor.click()
  anchor.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
