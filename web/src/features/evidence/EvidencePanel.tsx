import { useQuery } from '@tanstack/react-query'
import { ExternalLink, FileText, Quote } from 'lucide-react'
import { useIdentityKey } from '../../app/AuthProvider'
import { Dialog } from '../../components/Dialog'
import { ErrorNotice, Loading, StatusBadge } from '../../components/ui'
import { api } from '../../services/api'
import { ApiError } from '../../services/http'
import type { EvidenceLocator } from '../../types/api'

export function locatorLabel(locator?: EvidenceLocator) {
  if (!locator) return '已保存的原文片段'
  const page = locator.page ?? locator.page_number
  if (page != null) return `第 ${page} 页`
  const headingPath = locator.heading_path?.length ? locator.heading_path : locator.title_path
  const heading = Array.isArray(headingPath)
    ? headingPath.join(' / ')
    : headingPath || locator.section_title
  const lineStart = locator.line_start ?? locator.line
  const lineEnd = locator.line_end
  const line =
    lineStart == null
      ? ''
      : lineEnd != null && lineEnd > lineStart
        ? `第 ${lineStart}–${lineEnd} 行`
        : `第 ${lineStart} 行`
  return (
    [heading, locator.paragraph != null ? `第 ${locator.paragraph} 段` : '', line]
      .filter(Boolean)
      .join(' · ') || '已保存的原文片段'
  )
}
export function EvidencePanel({
  quizId,
  evidenceId,
  onClose,
}: {
  quizId: string
  evidenceId: string
  onClose: () => void
}) {
  const identity = useIdentityKey()
  const query = useQuery({
    queryKey: [identity, 'evidence', quizId, evidenceId],
    queryFn: ({ signal }) => api.evidence(quizId, evidenceId, signal),
    staleTime: 0,
  })
  const evidence = query.data
  const legacyStatus = evidence && 'status' in evidence ? evidence.status : undefined
  const unavailable =
    legacyStatus === 'unavailable' ||
    legacyStatus === 'source_revoked' ||
    (query.error instanceof ApiError && [403, 404, 410].includes(query.error.status))
  return (
    <Dialog title="题目依据" onClose={onClose} className="evidence-panel">
      {query.isPending ? (
        <Loading>正在读取已保存的出处…</Loading>
      ) : unavailable ? (
        <div className="source-unavailable">
          <FileText size={32} />
          <h3>来源暂不可用</h3>
          <p>该资料可能已删除或授权已变化。我们无法展示它的原文，也不会重新生成一个出处。</p>
          <StatusBadge status="unavailable" />
        </div>
      ) : query.error ? (
        <ErrorNotice
          error={query.error}
          onRetry={() => {
            void query.refetch()
          }}
        />
      ) : (
        evidence && (
          <>
            <div className="evidence-heading">
              <span className="icon-tile mint">
                <FileText size={20} />
              </span>
              <div>
                <h3>{evidence.title}</h3>
                <span>{locatorLabel(evidence.locator)}</span>
              </div>
            </div>
            <div className="evidence-quote">
              <Quote size={23} />
              <p>{evidence.excerpt || '此来源没有可展示的片段。'}</p>
            </div>
            <div className="evidence-footnote">此处展示服务端保存并授权读取的原文片段。</div>
            {evidence.source_type === 'web' &&
              evidence.url &&
              /^https?:\/\//.test(evidence.url) && (
                <a
                  href={evidence.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-link"
                >
                  打开网页来源
                  <ExternalLink size={14} />
                </a>
              )}
            {evidence.source_type === 'web' && evidence.fetched_at && (
              <p className="tiny muted">
                抓取时间：{new Date(evidence.fetched_at).toLocaleString('zh-CN')}
              </p>
            )}
          </>
        )
      )}
    </Dialog>
  )
}
