import { useQuery, useQueryClient } from '@tanstack/react-query'
import { FileText, Quote } from 'lucide-react'
import { useEffect } from 'react'
import { useIdentityKey } from '../../app/AuthProvider'
import { Dialog } from '../../components/Dialog'
import { ErrorNotice, Loading } from '../../components/ui'
import { locatorLabel } from '../evidence/EvidencePanel'
import {
  courseErrorMessage,
  courseKeys,
  coursesApi,
  courseSourceRevoked,
} from '../../services/courses'

export function CourseEvidenceDrawer({
  courseId,
  lessonId,
  sourceRef,
  onClose,
  onUnavailable,
}: {
  courseId: string
  lessonId?: string
  sourceRef: string
  onClose: () => void
  onUnavailable: () => void
}) {
  const identity = useIdentityKey()
  const client = useQueryClient()
  const query = useQuery({
    queryKey: courseKeys.evidence(identity, courseId, sourceRef, lessonId),
    queryFn: ({ signal }) => coursesApi.evidence(courseId, sourceRef, lessonId, signal),
    staleTime: 0,
    gcTime: 0,
    retry: false,
    refetchOnMount: 'always',
  })
  useEffect(() => {
    if (courseSourceRevoked(query.error)) {
      onUnavailable()
      void client.invalidateQueries({ queryKey: courseKeys.course(identity, courseId) })
    }
  }, [query.error, onUnavailable, client, identity, courseId])
  return (
    <Dialog title="课程原文依据" className="evidence-panel course-evidence-dialog" onClose={onClose}>
      {query.isPending ? (
        <Loading>正在读取已保存的原文…</Loading>
      ) : query.error ? (
        <ErrorNotice
          error={courseErrorMessage(query.error)}
          onRetry={() => {
            void query.refetch()
          }}
        />
      ) : query.data ? (
        <>
          <div className="evidence-heading">
            <span className="icon-tile mint">
              <FileText size={20} />
            </span>
            <div>
              <h3>{query.data.title}</h3>
              <span>{locatorLabel(query.data.locator)}</span>
            </div>
          </div>
          <div className="evidence-quote">
            <Quote size={23} />
            <p style={{ whiteSpace: 'pre-wrap' }}>
              {query.data.excerpt || '此来源没有可展示的片段。'}
            </p>
          </div>
          <div className="evidence-footnote">课程创建时保存的资料版本 · 已核对当前读取权限</div>
        </>
      ) : null}
    </Dialog>
  )
}
