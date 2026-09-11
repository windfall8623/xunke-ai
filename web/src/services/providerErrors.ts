export function providerErrorMessage(code?: string | null) {
  if (code === 'PROVIDER_TIMEOUT') return '模型服务响应超时，请稍后重试。'
  if (code === 'PROVIDER_RATE_LIMITED') return '模型服务暂时限流或繁忙，请稍后重试。'
  return undefined
}
