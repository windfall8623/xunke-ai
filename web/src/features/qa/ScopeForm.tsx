import { useQuery } from '@tanstack/react-query'
import { FileText } from 'lucide-react'
import { useId, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { useIdentityKey } from '../../app/AuthProvider'
import { ErrorNotice, Loading } from '../../components/ui'
import { api } from '../../services/api'
import type { DocumentItem, SelectedDocument, SourceScope } from '../../types/api'
import type { QaScope } from '../../types/qa'

type Props = {
  initialScope?: QaScope | null
  initialDocId?: string | null
  revision?: number
  busy: boolean
  error: unknown
  onSubmit: (scope: SourceScope, title?: string) => void
}

export function ScopeForm(props: Props) {
  const identity = useIdentityKey()
  const catalog = useQuery({
    queryKey: [identity, 'documents'],
    queryFn: ({ signal }) => api.documents(signal),
    staleTime: 0,
    refetchOnMount: 'always',
  })
  if (catalog.isPending) return <Loading>正在读取可用资料…</Loading>
  if (catalog.error)
    return (
      <ErrorNotice
        error={catalog.error}
        onRetry={() => {
          void catalog.refetch()
        }}
      />
    )
  const ready = (catalog.data?.items || []).filter((doc) => doc.status === 'ready')
  return <ScopeFields {...props} documents={ready} />
}

function ScopeFields({
  documents,
  initialScope,
  initialDocId,
  revision,
  busy,
  error,
  onSubmit,
}: Props & { documents: DocumentItem[] }) {
  const titleId = useId()
  const [title, setTitle] = useState('')
  const [selected, setSelected] = useState<Record<string, SelectedDocument>>(() => {
    const result: Record<string, SelectedDocument> = {}
    for (const doc of documents) {
      const existing = initialScope?.documents?.find((item) => item.doc_id === doc.doc_id)
      if (!existing && doc.doc_id !== initialDocId) continue
      const sections =
        existing && existing.section_catalog_revision === doc.section_catalog_revision
          ? existing.section_ids?.filter((id) =>
              doc.sections?.some((section) => section.section_id === id),
            ) || []
          : []
      result[doc.doc_id] = {
        doc_id: doc.doc_id,
        ...(sections.length
          ? { section_ids: sections, section_catalog_revision: doc.section_catalog_revision }
          : {}),
      }
    }
    return result
  })
  const availableSelected = Object.values(selected).filter((item) =>
    documents.some((doc) => doc.doc_id === item.doc_id),
  )
  const count = availableSelected.length
  const staleSelection = availableSelected.some((selection) => {
    if (!selection.section_ids?.length) return false
    const document = documents.find((item) => item.doc_id === selection.doc_id)
    return (
      document?.section_catalog_revision !== selection.section_catalog_revision ||
      selection.section_ids.some(
        (id) => !document?.sections?.some((section) => section.section_id === id),
      )
    )
  })
  function submit(event: FormEvent) {
    event.preventDefault()
    if (!count || count > 5 || busy || staleSelection) return
    onSubmit(
      { type: 'selected_documents', documents: availableSelected },
      title.trim() || undefined,
    )
  }
  return (
    <form className="qa-scope-form" onSubmit={submit}>
      {revision !== undefined && (
        <p className="muted tiny">范围版本 {revision} · 保存后仅在新范围中继续追问。</p>
      )}
      <div className="section-line">
        <strong>
          选择资料 <span className="muted">{count} / 5</span>
        </strong>
        <Link to="/knowledge" className="text-link">
          管理资料
        </Link>
      </div>
      {initialDocId && !documents.some((doc) => doc.doc_id === initialDocId) && (
        <p className="notice">这份资料还未就绪或已不可用，请选择其他资料。</p>
      )}
      {initialScope?.documents?.some((old) => {
        const current = documents.find((doc) => doc.doc_id === old.doc_id)
        return (
          !current ||
          current.active_version_id !== old.document_version_id ||
          (old.section_ids?.length &&
            current.section_catalog_revision !== old.section_catalog_revision)
        )
      }) && (
        <p className="notice">部分资料的版本或章节已变化，请重新确认；保存后会采用当前可用版本。</p>
      )}
      {!documents.length ? (
        <p className="muted">还没有可用资料。上传并处理完成后即可提问。</p>
      ) : (
        <div className="document-options">
          {documents.map((doc) => (
            <div key={doc.doc_id} className="qa-document-option">
              <label className="checkbox-row">
                <input
                  type="checkbox"
                  checked={!!selected[doc.doc_id]}
                  disabled={busy || (!selected[doc.doc_id] && count >= 5)}
                  onChange={(event) => {
                    const checked = event.target.checked
                    setSelected((current) => {
                      const next = { ...current }
                      if (checked) next[doc.doc_id] = { doc_id: doc.doc_id }
                      else delete next[doc.doc_id]
                      return next
                    })
                  }}
                />
                <FileText size={16} />
                <span>{doc.file_name}</span>
              </label>
              {selected[doc.doc_id] && !!doc.sections?.length && doc.section_catalog_revision && (
                <fieldset className="section-options" disabled={busy}>
                  <legend>限定章节（不选时使用全文）</legend>
                  {doc.sections.map((section) => (
                    <label className="checkbox-row" key={section.section_id}>
                      <input
                        type="checkbox"
                        checked={
                          selected[doc.doc_id].section_ids?.includes(section.section_id) || false
                        }
                        onChange={(event) => {
                          const checked = event.target.checked
                          setSelected((current) => {
                            const sections = new Set(current[doc.doc_id]?.section_ids || [])
                            if (checked) sections.add(section.section_id)
                            else sections.delete(section.section_id)
                            return {
                              ...current,
                              [doc.doc_id]: {
                                doc_id: doc.doc_id,
                                ...(sections.size
                                  ? {
                                      section_catalog_revision: doc.section_catalog_revision,
                                      section_ids: [...sections],
                                    }
                                  : {}),
                              },
                            }
                          })
                        }}
                      />
                      {section.title}
                    </label>
                  ))}
                </fieldset>
              )}
            </div>
          ))}
        </div>
      )}
      <p className="muted tiny">
        回答仅依据所选资料。资料不足时会提示补充，点击回答中的引用可阅读原文。
      </p>
      {staleSelection && (
        <p className="notice" role="alert">
          所选章节目录已更新，请取消勾选这份资料后重新选择章节。
        </p>
      )}
      {revision === undefined && (
        <label htmlFor={titleId}>
          会话标题（选填）
          <input
            id={titleId}
            value={title}
            maxLength={80}
            placeholder="新的资料问答"
            disabled={busy}
            onChange={(event) => setTitle(event.target.value)}
          />
        </label>
      )}
      <ErrorNotice error={error} />
      <button
        type="submit"
        className="button primary"
        disabled={busy || staleSelection || count < 1 || count > 5}
      >
        {busy ? '正在保存…' : revision === undefined ? '创建会话' : '保存范围'}
      </button>
    </form>
  )
}
