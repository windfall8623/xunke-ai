import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { useIdentityKey } from '../../app/AuthProvider'
import { ErrorNotice, Loading } from '../../components/ui'
import { api } from '../../services/api'
import { ApiError } from '../../services/http'
import type { DocumentItem, SelectedDocument } from '../../types/api'
import { locatorLabel } from '../evidence/EvidencePanel'
import { identifiedPreviewPages, selectedPreviewBlocks, selectedPreviewSections, sourceMatchesDocument } from './courseSourceFacts'

/** Mounted only after an explicit preview click; cached private excerpts die with this view. */
export function CourseSourcePreview({
  document,
  selection,
  onClose,
  onReloadCatalog,
}: {
  document: DocumentItem
  selection: SelectedDocument
  onClose: () => void
  onReloadCatalog: () => void
}) {
  const identity = useIdentityKey()
  const client = useQueryClient()
  const [blockId, setBlockId] = useState<string | null>(null)
  const version = document.active_version_id || ''
  const parse = document.section_catalog_revision || ''
  const prefix = useMemo(() => [identity, 'course-source-preview', document.doc_id, version, parse] as const,
    [identity, document.doc_id, version, parse])
  const available = document.status === 'ready' && !!version && !!parse
  const directory = useQuery({
    queryKey: [...prefix, null],
    queryFn: ({ signal }) => api.documentSource(document.doc_id, { version_id: version, parse_artifact_id: parse }, signal),
    enabled: available,
    retry: false,
    staleTime: 0,
    gcTime: 0,
    refetchOnMount: 'always',
    refetchOnWindowFocus: false,
  })
  const source = directory.data && !directory.error && sourceMatchesDocument(directory.data, document)
    ? directory.data : null
  const blocks = source ? selectedPreviewBlocks(source, selection) : []
  const requestedBlock = blockId || blocks[0]?.block_id
  const needsExcerpt = !!source && !!requestedBlock && source.block_id !== requestedBlock
  const excerpt = useQuery({
    queryKey: [...prefix, requestedBlock],
    queryFn: ({ signal }) => api.documentSource(document.doc_id, {
      version_id: version, parse_artifact_id: parse, block_id: requestedBlock,
    }, signal),
    enabled: available && needsExcerpt,
    retry: false,
    staleTime: 0,
    gcTime: 0,
    refetchOnWindowFocus: false,
  })
  useEffect(() => () => {
    void client.cancelQueries({ queryKey: prefix })
    client.removeQueries({ queryKey: prefix })
  }, [client, prefix])
  const current = needsExcerpt ? excerpt : directory
  const response = current.error ? null : current.data
  const mismatch = (directory.data && !sourceMatchesDocument(directory.data, document)) ||
    (response && (!sourceMatchesDocument(response, document) || (!!requestedBlock && response.block_id !== requestedBlock)))
  const readable = !mismatch && response && blocks.some((block) => block.block_id === response.block_id)
  const sections = source ? selectedPreviewSections(source, selection) : []
  const pages = source ? identifiedPreviewPages(source, selection) : []
  const error = directory.error || current.error
  const unavailable = error instanceof ApiError && [403, 404, 410].includes(error.status)

  return (
    <section className="course-source-preview" aria-label={`资料预览 · ${document.file_name}`}>
      <div className="course-source-preview-heading">
        <h3>{document.file_name}</h3>
        <button type="button" className="text-button" onClick={onClose}>关闭预览</button>
      </div>
      <p className="tiny muted">
        当前选择范围：{selection.section_ids?.length ? `已选 ${selection.section_ids.length} 个章节（含下级章节）` : '全文'}
      </p>
      {!available || mismatch ? (
        <ErrorNotice error="资料版本与当前选择不一致，请刷新资料列表后重新选择。" onRetry={onReloadCatalog} />
      ) : unavailable ? (
        <ErrorNotice error="这份资料的当前版本暂不可用，请刷新资料列表后重新选择。" onRetry={onReloadCatalog} />
      ) : error ? (
        <ErrorNotice error="暂时无法读取原文片段，课程草稿和资料选择已保留。" onRetry={() => { void current.refetch() }} />
      ) : directory.isPending ? (
        <Loading>正在读取已识别的目录与片段…</Loading>
      ) : source ? (
        <>
          <h4>已识别章节</h4>
          {sections.length ? (
            <ul className="course-source-directory">
              {sections.map((section) => {
                const first = blocks.find((block) => section.start_char <= block.start_char && block.end_char <= section.end_char)
                return <li key={section.section_id}>
                  <button type="button" className="text-button" disabled={!first}
                    aria-pressed={!!first && first.block_id === requestedBlock}
                    onClick={() => setBlockId(first?.block_id || null)}>
                    查看 {section.heading_path?.join(' / ') || section.title}
                  </button>
                </li>
              })}
            </ul>
          ) : <p className="muted">未识别出章节目录，可核对正文片段。</p>}
          {document.file_type.toLowerCase() === 'pdf' && (
            <p className="tiny muted">已识别出文字的页码：{pages.length ? pages.join('、') : '当前范围暂无页码记录'}</p>
          )}
          {needsExcerpt && excerpt.isPending ? <Loading>正在读取所选章节的片段…</Loading> : readable ? (
            <div className="course-source-excerpt">
              <p className="tiny muted">{locatorLabel(response.locator)}</p>
              <blockquote>{response.excerpt || '此位置没有可展示的正文片段。'}</blockquote>
            </div>
          ) : <p className="notice">当前选择范围没有可展示的片段，请核对所选章节或重新选择资料。</p>}
          <button type="button" className="text-button" onClick={() => { void current.refetch() }}>重新读取片段</button>
        </>
      ) : null}
    </section>
  )
}
