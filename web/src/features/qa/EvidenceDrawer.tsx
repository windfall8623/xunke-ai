import { useQuery } from '@tanstack/react-query'
import { FileText, Quote } from 'lucide-react'
import { useEffect } from 'react'
import { useIdentityKey } from '../../app/AuthProvider'
import { Dialog } from '../../components/Dialog'
import { ErrorNotice, Loading } from '../../components/ui'
import { qaApi, qaKeys } from '../../services/qa'
import { sourceError } from './useQaSession'

export function EvidenceDrawer({
  sessionId,
  answerId,
  evidenceId,
  onClose,
  onUnavailable,
}: {
  sessionId: string
  answerId: string
  evidenceId: string
  onClose: () => void
  onUnavailable: () => void
}) {
  const identity = useIdentityKey()
  const query = useQuery({
    queryKey: [...qaKeys.evidence(identity, sessionId), answerId, evidenceId],
    queryFn: ({ signal }) => qaApi.evidence(answerId, evidenceId, signal),
    staleTime: 0,
    gcTime: 0,
    refetchOnMount: 'always',
    retry: false,
  })
  useEffect(() => {
    if (sourceError(query.error)) onUnavailable()
  }, [query.error, onUnavailable])
  const evidence = query.data
  return (
    <Dialog title="引用原文" onClose={onClose} className="qa-evidence-drawer">
      {query.isPending || query.isFetching ? (
        <Loading>正在核验并读取原文…</Loading>
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
                <FileText size={21} />
              </span>
              <div>
                <h3>{evidence.title}</h3>
                {!!evidence.locator.heading_path?.length && (
                  <p className="tiny muted">{evidence.locator.heading_path.join(' / ')}</p>
                )}
                <span>
                  {[
                    evidence.locator.page ? `第 ${evidence.locator.page} 页` : '',
                    evidence.locator.paragraph ? `第 ${evidence.locator.paragraph} 段` : '',
                    evidence.locator.line_start
                      ? `第 ${evidence.locator.line_start}${evidence.locator.line_end && evidence.locator.line_end !== evidence.locator.line_start ? `–${evidence.locator.line_end}` : ''} 行`
                      : '',
                  ]
                    .filter(Boolean)
                    .join(' · ') || '已保存的原文片段'}
                </span>
              </div>
            </div>
            <div className="evidence-quote">
              <Quote size={23} />
              <p>{evidence.excerpt}</p>
            </div>
            <p className="evidence-footnote">这段原文已按回答采用的资料版本核验。</p>
          </>
        )
      )}
    </Dialog>
  )
}
