import { useMutation, useQuery } from '@tanstack/react-query'
import {
  ArrowLeft,
  ArrowRight,
  Award,
  BookOpen,
  Camera,
  CheckCircle2,
  KeyRound,
  LogOut,
  Pencil,
} from 'lucide-react'
import { useRef, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth, useIdentityKey } from '../app/AuthProvider'
import { Dialog } from '../components/Dialog'
import {
  EmptyState,
  ErrorNotice,
  Loading,
  PageHeading,
  StatusBadge,
  formatDate,
  safeImageUrl,
} from '../components/ui'
import { api } from '../services/api'
import { ChangePasswordDialog } from '../features/auth/ChangePasswordDialog'

export function ProfilePage() {
  const auth = useAuth()
  const identity = useIdentityKey()
  const navigate = useNavigate()
  const [page, setPage] = useState(1)
  const [editing, setEditing] = useState(false)
  const [changingPassword, setChangingPassword] = useState(false)
  const [nickname, setNickname] = useState('')
  const [notice, setNotice] = useState('')
  const [fileError, setFileError] = useState('')
  const file = useRef<HTMLInputElement>(null)
  const profile = useQuery({
    queryKey: [identity, 'profile'],
    queryFn: ({ signal }) => api.profile(signal),
  })
  const history = useQuery({
    queryKey: [identity, 'history', page],
    queryFn: ({ signal }) => api.history(page, signal),
  })
  const save = useMutation({
    mutationFn: () => api.updateProfile(nickname.trim()),
    onSuccess: async () => {
      await profile.refetch()
      await auth.refresh()
      setEditing(false)
      setNotice('资料已保存')
    },
  })
  const avatar = useMutation({
    mutationFn: (selected: File) => api.avatar(selected),
    onSuccess: async () => {
      await profile.refetch()
      await auth.refresh()
      setNotice('头像已更新')
    },
  })
  const logout = useMutation({
    mutationFn: auth.logout,
    onSuccess: () => navigate('/', { replace: true }),
  })
  function submit(event: FormEvent) {
    event.preventDefault()
    if (nickname.trim()) save.mutate()
  }
  const user = profile.data || auth.user
  return (
    <div className="profile-page">
      <PageHeading
        title="个人中心"
        description="管理账户资料，查看练习记录与学习历史。"
        action={
          <Link className="button secondary" to="/study/history">
            查看学习历史
            <ArrowRight size={16} />
          </Link>
        }
      />
      <ErrorNotice
        error={profile.error}
        onRetry={() => {
          void profile.refetch()
        }}
      />
      <ErrorNotice error={logout.error} />
      {notice && (
        <div className="notice success" role="status">
          <CheckCircle2 size={18} />
          {notice}
        </div>
      )}
      <section className="card profile-card">
        <div className="profile-identity">
          <div className="large-avatar">
            {safeImageUrl(user?.avatar_url) ? (
              <img src={safeImageUrl(user?.avatar_url)} alt="我的头像" />
            ) : (
              user?.nickname.slice(0, 1)
            )}
          </div>
          <div>
            <h2>{user?.nickname || '学习者'}</h2>
            <p>保持好奇，每一天都有新收获。</p>
          </div>
          <button
            className="button secondary button-small"
            onClick={() => {
              setNickname(user?.nickname || '')
              save.reset()
              setEditing(true)
            }}
          >
            <Pencil size={14} />
            编辑资料
          </button>
        </div>
        <div className="button-row profile-account-actions">
          <button
            className="button secondary button-small"
            onClick={() => setChangingPassword(true)}
          >
            <KeyRound size={15} />
            修改密码
          </button>
          <button
            className="button secondary button-small"
            disabled={logout.isPending}
            onClick={() => logout.mutate()}
          >
            <LogOut size={15} />
            退出登录
          </button>
        </div>
        <div className="profile-stats">
          <div>
            <span>
              <Award size={17} />
              累计经验
            </span>
            <strong>{user?.total_xp ?? '—'}</strong>
          </div>
          <div>
            <span>
              <BookOpen size={17} />
              完成练习
            </span>
            <strong>
              {profile.data?.quiz_count ?? '—'}
              <small> 组</small>
            </strong>
          </div>
          <div>
            <span>
              <CheckCircle2 size={17} />
              平均正确率
            </span>
            <strong>
              {profile.data && profile.data.quiz_count > 0
                ? `${profile.data.average_accuracy}%`
                : '—'}
            </strong>
          </div>
        </div>
      </section>
      <section className="card history-card">
        <p className="muted">
          这里展示题目练习记录；课程与学习空间活动请查看
          <Link to="/study/history" className="text-link">
            学习历史
          </Link>
          。
        </p>
        <div className="section-line">
          <h2>练习记录</h2>
          <Link to="/" className="text-link">
            开始新练习
            <ArrowRight size={14} />
          </Link>
        </div>
        <ErrorNotice
          error={history.error}
          onRetry={() => {
            void history.refetch()
          }}
        />
        {history.isPending ? (
          <Loading />
        ) : !history.data?.items.length ? (
          <EmptyState title="还没有学习记录">完成第一组练习，就能在这里看到你的进步。</EmptyState>
        ) : (
          <div className="history-list">
            {history.data.items.map((item) => {
              const complete =
                ['settled', 'completed'].includes(item.status || '') ||
                item.report_status === 'completed'
              return (
                <article key={item.quiz_id} className="history-item">
                  <span className="icon-tile indigo">
                    <BookOpen size={21} />
                  </span>
                  <div>
                    <h3>{item.title}</h3>
                    <p>
                      {formatDate(item.created_at)}
                      <span>·</span>
                      {item.question_count} 题<span>·</span>
                      {complete && item.accuracy != null
                        ? `${item.accuracy}% 正确率`
                        : `已作答 ${item.answered_count ?? 0} 题`}
                    </p>
                    {item.source_status === 'legacy_unverified' && (
                      <StatusBadge status="legacy_unverified" />
                    )}
                  </div>
                  <StatusBadge status={complete ? 'completed' : 'in_progress'} />
                  <Link
                    className="button secondary button-small"
                    to={`/quizzes/${encodeURIComponent(item.quiz_id)}${complete ? '/report' : ''}`}
                  >
                    {complete ? '查看报告' : '继续学习'}
                    <ArrowRight size={15} />
                  </Link>
                </article>
              )
            })}
          </div>
        )}
        {history.data && history.data.total > 10 && (
          <div className="pagination">
            <button
              className="button secondary button-small"
              disabled={page <= 1}
              onClick={() => setPage(page - 1)}
            >
              <ArrowLeft size={14} />
              上一页
            </button>
            <span>
              第 {page} / {Math.ceil(history.data.total / 10)} 页
            </span>
            <button
              className="button secondary button-small"
              disabled={page * 10 >= history.data.total}
              onClick={() => setPage(page + 1)}
            >
              下一页
              <ArrowRight size={14} />
            </button>
          </div>
        )}
      </section>
      {editing && (
        <Dialog title="编辑个人资料" onClose={() => setEditing(false)}>
          <form className="stack-form" onSubmit={submit}>
            <label>
              昵称
              <input
                value={nickname}
                onChange={(event) => setNickname(event.target.value)}
                maxLength={100}
                required
              />
            </label>
            <div>
              <input
                type="file"
                ref={file}
                className="sr-only"
                aria-label="选择头像文件"
                accept="image/png,image/jpeg,image/webp"
                onChange={(event) => {
                  const selected = event.target.files?.[0]
                  setFileError('')
                  if (selected) {
                    if (
                      !['image/png', 'image/jpeg', 'image/webp'].includes(selected.type) ||
                      selected.size > 2 * 1024 * 1024
                    )
                      setFileError('头像支持 PNG、JPEG、WebP，大小不超过 2 MB。')
                    else avatar.mutate(selected)
                  }
                  event.target.value = ''
                }}
              />
              <button
                type="button"
                className="button secondary"
                disabled={avatar.isPending}
                onClick={() => file.current?.click()}
              >
                <Camera size={16} />
                {avatar.isPending ? '正在上传…' : '上传新头像'}
              </button>
              <p className="tiny muted">PNG / JPEG / WebP · 2 MB 以内</p>
            </div>
            <ErrorNotice error={fileError || avatar.error || save.error} />
            <button className="button primary" disabled={save.isPending || !nickname.trim()}>
              {save.isPending ? '正在保存…' : '保存资料'}
            </button>
          </form>
        </Dialog>
      )}
      {changingPassword && <ChangePasswordDialog onClose={() => setChangingPassword(false)} />}
    </div>
  )
}
