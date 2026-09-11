import { ArrowLeft, ArrowRight, KeyRound, LockKeyhole, ShieldCheck } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../app/AuthProvider'
import { api } from '../services/api'
import { ErrorNotice } from '../components/ui'
import { Brand } from '../components/Brand'
import type { AuthSession } from '../types/api'

export function LoginPage() {
  const [mode, setMode] = useState<'login' | 'register' | 'recover' | 'bind'>('login')
  const [account, setAccount] = useState('')
  const [password, setPassword] = useState('')
  const [nickname, setNickname] = useState('')
  const [recovery, setRecovery] = useState('')
  const [migrationCode, setMigrationCode] = useState('')
  const [receipt, setReceipt] = useState<AuthSession | null>(null)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState<unknown>(null)
  const [pending, setPending] = useState(false)
  const capabilities = useQuery({
    queryKey: ['auth-capabilities'],
    queryFn: ({ signal }) => api.authCapabilities(signal),
    retry: false,
  })
  const legacyLinkEnabled =
    capabilities.isSuccess && capabilities.data?.legacy_link_enabled === true
  const auth = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const locationNotice = (location.state as { notice?: string } | null)?.notice
  const requestedPath = (location.state as { from?: string } | null)?.from
  const destination =
    requestedPath && /^\/(?!\/)/.test(requestedPath) && !requestedPath.includes('\\')
      ? requestedPath
      : '/'
  const switchMode = (next: typeof mode) => {
    setMode(next)
    setError(null)
    setNotice('')
    setPassword('')
    setRecovery('')
    setMigrationCode('')
  }
  async function submit(event: FormEvent) {
    event.preventDefault()
    if (pending) return
    if (mode === 'bind' && !legacyLinkEnabled) {
      setError(new Error('旧账号关联当前未启用，请返回登录。'))
      return
    }
    setPending(true)
    setError(null)
    setNotice('')
    try {
      if (mode === 'recover') {
        const result = await api.recover({
          account: account.trim(),
          recovery_code: recovery.trim(),
          new_password: password,
        })
        setMode('login')
        setPassword('')
        setRecovery('')
        setNotice(
          result.recovery_code
            ? `密码已更新，请保存新的恢复码：${result.recovery_code}`
            : '密码已更新，旧会话已撤销。请使用新密码登录。',
        )
      } else {
        const result =
          mode === 'login'
            ? await api.login({ account: account.trim(), password })
            : mode === 'bind'
              ? await api.bindLegacy({
                  account: account.trim(),
                  password,
                  code: migrationCode.trim(),
                })
              : await api.register({ account: account.trim(), password, nickname: nickname.trim() })
        setPassword('')
        setMigrationCode('')
        if ((mode === 'register' || mode === 'bind') && result.recovery_code) setReceipt(result)
        else {
          await auth.acceptSession(result)
          navigate(destination, { replace: true })
        }
      }
    } catch (cause) {
      setError(cause)
    } finally {
      setPending(false)
    }
  }
  return (
    <div className="auth-page">
      <div className="auth-intro">
        <Link to="/" className="brand" aria-label="知学 AI 首页">
          <Brand />
        </Link>
        <div>
          <span className="eyebrow">A LITTLE CURIOSITY, EVERY DAY</span>
          <h2>
            所有进步，
            <br />
            都从一个问题开始。
          </h2>
          <p>
            带上你的好奇心。
            <br />
            从资料到练习，从理解到掌握。
          </p>
          <div className="auth-art" aria-hidden="true">
            <div className="orbit orbit-one" />
            <div className="orbit orbit-two" />
            <span>学</span>
            <span>思</span>
            <span>知</span>
          </div>
        </div>
        <span className="auth-caption">
          <ShieldCheck size={17} /> 进度自动保存，换个设备继续学习
        </span>
      </div>
      <section className="auth-panel">
        <Link to="/" className="brand auth-mobile-brand" aria-label="知学 AI 首页">
          <Brand />
        </Link>
        <Link to="/" className="back-link">
          <ArrowLeft size={16} />
          返回学习首页
        </Link>
        <div className="auth-form-wrap">
          {receipt ? (
            <div className="recovery-card">
              <KeyRound size={32} />
              <h1>保存你的恢复码</h1>
              <p>忘记密码时，用账号和此恢复码找回。恢复码只在此展示一次，请保存在安全的位置。</p>
              <code className="recovery-code">{receipt.recovery_code}</code>
              <button
                className="button primary full-width"
                onClick={async () => {
                  await auth.acceptSession(receipt)
                  setReceipt(null)
                  navigate(destination, { replace: true })
                }}
              >
                我已保存，开始学习
                <ArrowRight size={18} />
              </button>
            </div>
          ) : (
            <>
              <span className="form-icon">
                <LockKeyhole size={24} />
              </span>
              <h1>
                {mode === 'login'
                  ? '欢迎回来'
                  : mode === 'register'
                    ? '开启你的学习旅程'
                    : mode === 'bind'
                      ? '迁移旧账号'
                      : '找回账号'}
              </h1>
              <p className="muted">
                {mode === 'login'
                  ? '登录后，继续积累属于你的知识。'
                  : mode === 'register'
                    ? '创建账号，保存每一次练习与进步。'
                    : mode === 'bind'
                      ? '用原微信账号的一次性迁移码设置网页账号与密码，保留已有学习记录和积分。'
                      : '使用注册时保存的恢复码设置新密码。'}
              </p>
              {auth.status === 'expired' && (
                <div className="notice warning">
                  登录已失效，请重新登录。你的学习进度已经保存在账号中。
                </div>
              )}
              <ErrorNotice error={error} />
              {(notice || locationNotice) && (
                <div className="notice success" role="status">
                  {notice || locationNotice}
                </div>
              )}
              <form onSubmit={submit} className="stack-form">
                <label>
                  账号
                  <input
                    name="account"
                    autoComplete="username"
                    value={account}
                    onChange={(event) => setAccount(event.target.value)}
                    required
                    minLength={3}
                    maxLength={64}
                    placeholder="输入你的账号"
                  />
                </label>
                {mode === 'register' && (
                  <label>
                    昵称
                    <input
                      autoComplete="nickname"
                      value={nickname}
                      onChange={(event) => setNickname(event.target.value)}
                      required
                      maxLength={100}
                      placeholder="想让我们怎么称呼你"
                    />
                  </label>
                )}
                {mode === 'recover' && (
                  <label>
                    恢复码
                    <input
                      autoComplete="off"
                      value={recovery}
                      onChange={(event) => setRecovery(event.target.value)}
                      required
                      placeholder="输入保存的恢复码"
                    />
                  </label>
                )}
                {mode === 'bind' && (
                  <label>
                    一次性迁移码
                    <input
                      autoComplete="off"
                      spellCheck={false}
                      value={migrationCode}
                      onChange={(event) => setMigrationCode(event.target.value)}
                      required
                      minLength={16}
                      maxLength={128}
                      placeholder="迁移码有效期为 5 分钟，仅可使用一次"
                    />
                  </label>
                )}
                <label>
                  {mode === 'recover' ? '新密码' : '密码'}
                  <input
                    name="password"
                    type="password"
                    autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    required
                    minLength={mode === 'login' ? 1 : 10}
                    maxLength={128}
                    placeholder={mode === 'login' ? '输入密码' : '至少 10 个字符'}
                  />
                </label>
                {mode === 'login' && (
                  <button
                    type="button"
                    className="text-button align-right"
                    onClick={() => switchMode('recover')}
                  >
                    忘记密码？
                  </button>
                )}
                <button
                  type="submit"
                  className="button primary full-width"
                  disabled={pending || (mode === 'bind' && !legacyLinkEnabled)}
                >
                  {pending
                    ? '正在处理…'
                    : mode === 'login'
                      ? '登录'
                      : mode === 'register'
                        ? '注册账号'
                        : mode === 'bind'
                          ? '关联并设置网页账号'
                          : '重设密码'}
                  <ArrowRight size={18} />
                </button>
              </form>
              <p className="auth-switch">
                {mode === 'login' ? '还没有账号？' : '已有账号？'}{' '}
                <button
                  type="button"
                  className="text-button"
                  onClick={() => switchMode(mode === 'login' ? 'register' : 'login')}
                >
                  {mode === 'login' ? '立即注册' : '返回登录'}
                </button>
              </p>
              {legacyLinkEnabled && mode !== 'bind' && (
                <p className="auth-switch">
                  已有小程序学习记录？{' '}
                  <button
                    type="button"
                    className="text-button"
                    disabled={pending}
                    onClick={() => switchMode('bind')}
                  >
                    迁移旧账号
                  </button>
                </p>
              )}
              <div className="auth-divider">
                <span>先了解一下</span>
              </div>
              <Link to="/demo" className="button secondary full-width">
                体验预置练习
              </Link>
              <p className="tiny muted centered">预置体验无需账号，不会调用 AI 或记录学习积分。</p>
            </>
          )}
        </div>
      </section>
    </div>
  )
}
