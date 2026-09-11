import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { useAuth, useIdentityKey } from '../../app/AuthProvider'
import { ErrorNotice, Loading } from '../../components/ui'
import { api } from '../../services/api'
import type { DocumentItem, SelectedDocument, SourceScope } from '../../types/api'
import type { StudyScope } from '../../types/study'

/** UX check only: the server authorizes the complete immutable source identities. */
export function scopeCovers(saved: StudyScope, answer: StudyScope) {
  if (!answer.documents?.length) return false
  return answer.documents.every((source) => {
    const allowed = saved.documents?.find((item) => item.doc_id === source.doc_id)
    return (
      !!allowed &&
      allowed.document_version_id === source.document_version_id &&
      allowed.parse_artifact_id === source.parse_artifact_id &&
      allowed.index_build_id === source.index_build_id &&
      allowed.source_sha256 === source.source_sha256 &&
      allowed.canonical_text_hash === source.canonical_text_hash &&
      allowed.authorization_revision === source.authorization_revision &&
      (!allowed.section_ids?.length ||
        (!!source.section_ids?.length &&
          source.section_ids.every((id) => allowed.section_ids?.includes(id))))
    )
  })
}

export function StudyScopeSummary({ scope, revision }: { scope: StudyScope; revision: number }) {
  return (
    <div style={{ minWidth: 0, overflowWrap: 'anywhere' }}>
      <p className="muted tiny">固定范围版本 {revision} · 后续资料更新不会自动替换此范围。</p>
      <ul className="document-options">
        {(scope.documents || []).map((doc) => (
          <li key={doc.doc_id}>
            <span>{doc.title || '已保存资料'}</span>
            <span className="muted tiny">
              {' '}
              · {doc.section_ids?.length ? `已选 ${doc.section_ids.length} 个章节` : '全文'}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}

const catalogVersion = (doc: DocumentItem) =>
  JSON.stringify([
    doc.active_version_id,
    doc.active_build_id,
    doc.section_catalog_revision,
    doc.document_revision,
  ])

export function StudyScopePicker({
  scope,
  scopeRevision,
  value,
  onChange,
  disabled = false,
}: {
  scope?: StudyScope
  scopeRevision?: number
  value: SourceScope | null
  onChange: (value: SourceScope | null) => void
  disabled?: boolean
}) {
  const identity = useIdentityKey()
  const auth = useAuth()
  const catalog = useQuery({
    queryKey: [identity, 'documents'],
    queryFn: ({ signal }) => api.documents(signal),
    enabled: auth.status === 'authenticated',
    staleTime: 0,
    refetchOnMount: 'always',
    retry: false,
  })
  const versions = useRef(new Map<string, string>())
  const [catalogChanged, setCatalogChanged] = useState(false)
  const scopeIdentity = JSON.stringify([scopeRevision, scope?.documents])
  const previousScope = useRef(scopeIdentity)
  const documents = (catalog.data?.items || []).filter((item) => item.status === 'ready')
  const scopeChanged = previousScope.current !== scopeIdentity
  const stale =
    !scope &&
    !!value?.documents.some((selected) => {
      const current = documents.find((item) => item.doc_id === selected.doc_id)
      return !current || versions.current.get(selected.doc_id) !== catalogVersion(current)
    })
  useEffect(() => {
    if (!scopeChanged && !stale) return
    previousScope.current = scopeIdentity
    versions.current.clear()
    onChange(null)
    if (stale) setCatalogChanged(true)
  }, [onChange, scopeChanged, scopeIdentity, stale])

  if (auth.status !== 'authenticated') return <p className="notice">请先登录后选择学习资料。</p>
  if (!scope && catalog.isPending) return <Loading>正在读取可用资料…</Loading>
  if (!scope && catalog.error)
    return (
      <ErrorNotice
        error="资料列表暂时无法读取，请重新加载后选择。"
        onRetry={() => {
          void catalog.refetch()
        }}
      />
    )

  const selected = scopeChanged || stale ? [] : value?.documents || []
  const choices =
    scope?.documents ||
    documents.map((doc) => ({
      doc_id: doc.doc_id,
      title: doc.file_name,
      section_ids: [] as string[],
      section_catalog_revision: doc.section_catalog_revision,
    }))
  function change(next: SelectedDocument[]) {
    onChange(next.length ? { type: 'selected_documents', documents: next } : null)
  }
  function defaultSelection(docId: string): SelectedDocument {
    const fixed = scope?.documents?.find((item) => item.doc_id === docId)
    return fixed?.section_ids?.length
      ? {
          doc_id: docId,
          section_ids: [...fixed.section_ids],
          section_catalog_revision: fixed.section_catalog_revision || fixed.parse_artifact_id,
        }
      : { doc_id: docId }
  }
  return (
    <fieldset className="qa-scope-form" disabled={disabled} style={{ minWidth: 0 }}>
      <legend>选择学习资料</legend>
      <p className="muted tiny">
        {scope
          ? `固定范围版本 ${scopeRevision} · 仅使用已保存的来源。`
          : '保存时固定为当前可用资料版本；更新资料后，已保存范围保持不变。'}
      </p>
      {catalogChanged && (
        <p className="notice" role="status">
          资料版本已变化，已清除旧选择，请重新确认资料。
        </p>
      )}
      {!choices.length && <p className="muted">还没有可用资料，上传并处理完成后即可选择。</p>}
      <div className="document-options">
        {choices.map((source) => {
          const checked = selected.find((item) => item.doc_id === source.doc_id)
          const fixed = scope?.documents?.find((item) => item.doc_id === source.doc_id)
          const current = documents.find((item) => item.doc_id === source.doc_id)
          const matchingCatalog =
            current &&
            (!fixed ||
              (fixed.document_version_id === current.active_version_id &&
                fixed.index_build_id === current.active_build_id &&
                fixed.parse_artifact_id === current.section_catalog_revision))
          const sections = matchingCatalog
            ? (current.sections || []).filter(
                (section) =>
                  !fixed?.section_ids?.length || fixed.section_ids.includes(section.section_id),
              )
            : []
          return (
            <div className="qa-document-option" key={source.doc_id} style={{ minWidth: 0 }}>
              <label className="checkbox-row" style={{ display: 'flex', alignItems: 'flex-start' }}>
                <input
                  type="checkbox"
                  checked={!!checked}
                  disabled={disabled || (!checked && selected.length >= 5)}
                  onChange={(event) => {
                    if (event.target.checked) {
                      if (!fixed && current)
                        versions.current.set(source.doc_id, catalogVersion(current))
                      change([...selected, defaultSelection(source.doc_id)])
                    } else {
                      versions.current.delete(source.doc_id)
                      change(selected.filter((item) => item.doc_id !== source.doc_id))
                    }
                  }}
                />
                <span style={{ overflowWrap: 'anywhere' }}>{source.title || '已保存资料'}</span>
              </label>
              {checked && fixed && !matchingCatalog && (
                <p className="muted tiny">
                  保留已保存的
                  {fixed.section_ids?.length ? `${fixed.section_ids.length} 个章节` : '全文范围'}
                  ；当前目录不替换历史来源。
                </p>
              )}
              {checked && !!sections.length && (
                <fieldset className="section-options" disabled={disabled}>
                  <legend>
                    限定章节（不选时使用{fixed?.section_ids?.length ? '已保存范围' : '全文'}）
                  </legend>
                  {sections.map((section) => (
                    <label
                      className="checkbox-row"
                      key={section.section_id}
                      style={{ display: 'flex', alignItems: 'flex-start' }}
                    >
                      <input
                        type="checkbox"
                        checked={checked.section_ids?.includes(section.section_id) || false}
                        onChange={(event) => {
                          const next = new Set(checked.section_ids || [])
                          if (event.target.checked) next.add(section.section_id)
                          else next.delete(section.section_id)
                          const updated = next.size
                            ? {
                                doc_id: source.doc_id,
                                section_ids: [...next],
                                section_catalog_revision: current?.section_catalog_revision,
                              }
                            : defaultSelection(source.doc_id)
                          change(
                            selected.map((item) =>
                              item.doc_id === source.doc_id ? updated : item,
                            ),
                          )
                        }}
                      />
                      <span style={{ overflowWrap: 'anywhere' }}>{section.title}</span>
                    </label>
                  ))}
                </fieldset>
              )}
            </div>
          )
        })}
      </div>
      <p className="muted tiny">已选择 {selected.length} / 5 份资料</p>
    </fieldset>
  )
}
