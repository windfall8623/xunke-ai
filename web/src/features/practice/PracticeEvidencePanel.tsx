import { useQuery } from '@tanstack/react-query'
import { useIdentityKey } from '../../app/AuthProvider'
import { Dialog } from '../../components/Dialog'
import { ErrorNotice, Loading } from '../../components/ui'
import { locatorLabel } from '../evidence/EvidencePanel'
import { getPracticeEvidence, practiceErrorMessage } from '../../services/practice'

export function PracticeEvidencePanel({
  practiceId,
  questionId,
  evidenceId,
  onClose,
}: {
  practiceId: string
  questionId: string
  evidenceId: string
  onClose: () => void
}) {
  const identity = useIdentityKey()
  const query = useQuery({
    queryKey: [identity, 'practice-evidence', practiceId, questionId, evidenceId],
    queryFn: ({ signal }) => getPracticeEvidence(practiceId, questionId, evidenceId, signal),
    staleTime: 0,
    gcTime: 0,
    retry: false,
  })
  return (
    <Dialog title="题目依据" onClose={onClose} className="evidence-panel">
      {query.error ? (
        <ErrorNotice
          error={practiceErrorMessage(query.error)}
          onRetry={() => {
            void query.refetch()
          }}
        />
      ) : !query.data ? (
        <Loading>正在读取已保存的原文…</Loading>
      ) : (
        <div className="stack-form">
          <h3>{query.data.title}</h3>
          <p className="tiny muted">{locatorLabel(query.data.locator)}</p>
          <blockquote
            className="evidence-quote"
            style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}
          >
            {query.data.excerpt}
          </blockquote>
        </div>
      )}
    </Dialog>
  )
}
