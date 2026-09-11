import { useMutation } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../../app/AuthProvider'
import { Dialog } from '../../components/Dialog'
import { ErrorNotice } from '../../components/ui'
import { api } from '../../services/api'

export function ChangePasswordDialog({ onClose }: { onClose: () => void }) {
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const auth = useAuth()
  const navigate = useNavigate()
  const change = useMutation({
    mutationFn: () => api.changePassword({ current_password: current, new_password: next }),
    onSuccess: () => {
      auth.forget()
      navigate('/login', {
        replace: true,
        state: { notice: '密码已更新，旧会话已撤销。请使用新密码登录。' },
      })
    },
  })
  function submit(event: FormEvent) {
    event.preventDefault()
    if (!change.isPending) change.mutate()
  }
  return (
    <Dialog title="修改密码" onClose={onClose}>
      <form className="stack-form" onSubmit={submit}>
        <p className="tiny muted">修改成功后，所有设备上的旧会话都会退出。</p>
        <label>
          当前密码
          <input
            type="password"
            value={current}
            onChange={(event) => setCurrent(event.target.value)}
            autoComplete="current-password"
            required
          />
        </label>
        <label>
          新密码
          <input
            type="password"
            value={next}
            onChange={(event) => setNext(event.target.value)}
            autoComplete="new-password"
            minLength={10}
            maxLength={128}
            required
          />
        </label>
        <ErrorNotice error={change.error} />
        <button className="button primary" disabled={change.isPending}>
          {change.isPending ? '正在更新…' : '保存新密码'}
        </button>
      </form>
    </Dialog>
  )
}
