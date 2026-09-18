export function isLlmSettingsError(code?: string | number | null) {
  return [
    'llm_configuration_required',
    'user_llm_failed',
    'user_llm_key_unreadable',
    'llm_configuration_changed',
    'invalid_llm_endpoint',
    'api_key_required',
  ].includes(String(code || '').toLowerCase())
}

export function providerErrorMessage(code?: string | null) {
  if (code?.toLowerCase() === 'llm_configuration_required')
    return '请先在个人中心配置自己的模型，再使用 AI 功能。'
  if (code?.toLowerCase() === 'user_llm_failed')
    return '个人模型调用失败，请检查模型设置、密钥及服务商状态后重试。'
  if (code?.toLowerCase() === 'user_llm_key_unreadable')
    return '已保存的个人模型密钥无法读取，请在个人中心重新填写并验证。'
  if (code?.toLowerCase() === 'llm_configuration_changed')
    return '模型配置已在其他请求中更新或移除，请重新加载个人中心后再保存。'
  if (code?.toLowerCase() === 'invalid_llm_endpoint')
    return '个人模型地址不可用，请在个人中心填写公开的 HTTP(S) API 根地址。'
  if (code?.toLowerCase() === 'api_key_required')
    return '请在个人中心为当前模型配置填写并验证 API Key。'
  if (code === 'PROVIDER_TIMEOUT') return '模型服务响应超时，请稍后重试。'
  if (code === 'PROVIDER_RATE_LIMITED') return '模型服务暂时限流或繁忙，请稍后重试。'
  if (code === 'PROVIDER_UNAVAILABLE') return '模型服务暂时不可达，请稍后重试。'
  return undefined
}
