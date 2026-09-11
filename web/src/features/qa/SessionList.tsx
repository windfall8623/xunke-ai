import { useQuery } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight, MessageSquarePlus } from 'lucide-react'
import { useState } from 'react'
import { Link, NavLink } from 'react-router-dom'
import { useIdentityKey } from '../../app/AuthProvider'
import { ErrorNotice, Loading, formatDate } from '../../components/ui'
import { qaApi, qaKeys } from '../../services/qa'

export function SessionList({ onChoose }: { onChoose: () => void }) {
  const identity = useIdentityKey()
  const [page, setPage] = useState(1)
  const query = useQuery({
    queryKey: [...qaKeys.sessions(identity), page],
    queryFn: ({ signal }) => qaApi.sessions(page, signal),
    staleTime: 0,
    gcTime: 0,
  })
  const pages = Math.max(1, Math.ceil((query.data?.total || 0) / (query.data?.page_size || 20)))
  return (
    <div className="qa-sessions">
      <div className="qa-sessions-heading">
        <h2>我的会话</h2>
        <Link to="/qa" className="text-button" onClick={onChoose}>
          <MessageSquarePlus size={17} />
          新建
        </Link>
      </div>
      {query.isPending && <Loading>正在读取会话…</Loading>}
      <ErrorNotice
        error={query.error}
        onRetry={() => {
          void query.refetch()
        }}
      />
      {!query.isPending && !query.error && !query.data?.items.length && (
        <p className="muted tiny">选择资料，开始你的第一个问题。</p>
      )}
      <nav aria-label="问答会话" className="qa-session-links">
        {query.data?.items.map((item) => (
          <NavLink
            to={`/qa/${encodeURIComponent(item.session_id)}`}
            key={item.session_id}
            onClick={onChoose}
          >
            <strong>{item.source_status === 'revoked' ? '资料已不可用' : item.title}</strong>
            <span>
              {formatDate(item.updated_at)} ·{' '}
              {item.source_status === 'revoked'
                ? '需要更改范围'
                : item.active_task_id
                  ? '回答进行中'
                  : `范围 ${item.scope_revision}`}
            </span>
          </NavLink>
        ))}
      </nav>
      {(pages > 1 || page > 1) && (
        <div className="qa-pagination">
          <button
            className="icon-button"
            aria-label="上一页会话"
            disabled={page <= 1 || query.isFetching}
            onClick={() => setPage((value) => value - 1)}
          >
            <ChevronLeft size={18} />
          </button>
          <span>
            {page} / {pages}
          </span>
          <button
            className="icon-button"
            aria-label="下一页会话"
            disabled={page >= pages || query.isFetching}
            onClick={() => setPage((value) => value + 1)}
          >
            <ChevronRight size={18} />
          </button>
        </div>
      )}
    </div>
  )
}
