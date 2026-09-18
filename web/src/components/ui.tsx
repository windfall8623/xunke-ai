import { AlertCircle, LoaderCircle, RefreshCw } from 'lucide-react'
import type { ReactNode } from 'react'
import { ApiError } from '../services/http'
import { isLlmSettingsError, providerErrorMessage } from '../services/providerErrors'

export function LlmSettingsLink({ code }: { code?: string | number | null }) {
  return isLlmSettingsError(code) ? (
    <a className="text-link" href="/me#llm-settings">
      检查模型设置
    </a>
  ) : null
}

export function Loading({ children = '正在加载…' }: { children?: ReactNode }) {
  return (
    <div className="loading-state" role="status">
      <LoaderCircle className="spin" size={22} />
      <span>{children}</span>
    </div>
  )
}
export function ErrorNotice({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  if (!error) return null
  return (
    <div className="notice error" role="alert">
      <AlertCircle size={19} />
      <div>
        {error instanceof ApiError
          ? providerErrorMessage(String(error.code)) || error.message
          : error instanceof Error
            ? error.message
            : String(error)}
        {error instanceof ApiError && isLlmSettingsError(error.code) && (
          <div>
            <LlmSettingsLink code={error.code} />
          </div>
        )}
        {onRetry && (
          <button className="text-button" type="button" onClick={onRetry}>
            <RefreshCw size={14} />
            重新加载
          </button>
        )}
      </div>
    </div>
  )
}
export function EmptyState({
  title,
  children,
  action,
}: {
  title: string
  children?: ReactNode
  action?: ReactNode
}) {
  return (
    <div className="empty-state">
      <div className="empty-glyph" aria-hidden="true">
        ↗
      </div>
      <h3>{title}</h3>
      {children && <p>{children}</p>}
      {action}
    </div>
  )
}
export function PageHeading({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow?: string
  title: string
  description?: string
  action?: ReactNode
}) {
  return (
    <header className="page-heading">
      <div>
        {eyebrow && <p className="eyebrow">{eyebrow}</p>}
        <h1>{title}</h1>
        {description && <p className="muted">{description}</p>}
      </div>
      {action}
    </header>
  )
}
export function StatusBadge({ status, children }: { status: string; children?: ReactNode }) {
  const text: Record<string, string> = {
    ready: '可用于练习',
    processing: '正在处理',
    queued: '等待处理',
    pending: '等待处理',
    running: '进行中',
    completed: '已完成',
    failed: '处理失败',
    cancelled: '已取消',
    unavailable: '来源不可用',
    legacy_unverified: '历史来源未核验',
    model_only: '通用知识练习',
    verified: '依据已保存来源',
    grounded: '依据已保存来源',
    source_revoked: '来源授权已撤销',
    needs_reupload: '需要重新上传',
    strict_docs: '仅使用所选资料',
    doc_plus_web: '资料 + 联网补充',
    topic: '主题练习',
    draft: '草稿',
    reviewed: '已复核',
    approved: '已接受',
    rejected: '未接受',
    needs_changes: '待补充复核',
    preparing: '准备评测资料',
    promoted: '候选已建立',
    frozen: '已冻结',
    revoked: '已撤销',
    scoring: '正在评分',
    pending_scoring: '等待评分',
    partial: '部分完成',
    unknown: '待裁决',
    provisional: '暂定结果',
    incomplete: '未完成',
    settled: '已完成',
    in_progress: '学习中',
  }
  return <span className={`badge status-${status}`}>{children || text[status] || status}</span>
}
export function formatDate(date?: string | null) {
  if (!date) return '—'
  const value = new Date(date)
  return Number.isNaN(value.getTime())
    ? '—'
    : new Intl.DateTimeFormat('zh-CN', { month: 'short', day: 'numeric' }).format(value)
}
export function formatBytes(bytes: number) {
  return bytes >= 1024 * 1024
    ? `${(bytes / 1024 / 1024).toFixed(1)} MB`
    : `${Math.max(1, Math.round(bytes / 1024))} KB`
}
export function safeImageUrl(url?: string | null) {
  if (!url) return undefined
  return /^(https?:\/\/|\/(?!\/))/.test(url) ? url : undefined
}
