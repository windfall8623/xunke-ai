import {
  BookOpen,
  ChevronRight,
  FlaskConical,
  GraduationCap,
  Library,
  LogIn,
  Menu,
  MessageCircle,
  MoreHorizontal,
  UserRound,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from '../app/AuthProvider'
import { Brand } from './Brand'
import { Dialog } from './Dialog'
import { TaskNotifications } from './TaskNotifications'
import { ErrorNotice, safeImageUrl } from './ui'

export function AppShell() {
  const { user, error, refresh } = useAuth()
  const location = useLocation()
  const [menuOpen, setMenuOpen] = useState(false)
  const evaluator = ['evaluator', 'admin'].includes(user?.role || '')
  const reading = /^\/study\/courses\/(?!new(?:\/|$))[^/]+/.test(location.pathname)
  const navigation = [
    { to: '/', icon: BookOpen, label: '学习首页', end: true },
    { to: '/study', icon: GraduationCap, label: '我的课程', end: false },
    { to: '/knowledge', icon: Library, label: '我的资料', end: false },
    { to: '/qa', icon: MessageCircle, label: '资料问答', end: false },
    { to: '/me', icon: UserRound, label: '个人中心', end: false },
    ...(evaluator
      ? [{ to: '/evaluations', icon: FlaskConical, label: '评测工作台', end: false }]
      : []),
  ]
  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return
    const media = window.matchMedia('(min-width: 768px)')
    const closeOnDesktop = () => {
      if (media.matches) setMenuOpen(false)
    }
    media.addEventListener?.('change', closeOnDesktop)
    return () => media.removeEventListener?.('change', closeOnDesktop)
  }, [])
  function navigationLinks() {
    return navigation.map(({ to, icon: Icon, label, end }) => (
      <NavLink
        key={to}
        to={to}
        end={end}
        aria-label={label}
        title={label}
        onClick={() => setMenuOpen(false)}
        className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}
      >
        <Icon size={20} />
        <span className="nav-label">{label}</span>
      </NavLink>
    ))
  }
  return (
    <div className={`app-layout${reading ? ' reading-shell' : ''}`}>
      <a className="skip-link" href="#main-content">
        跳到主要内容
      </a>
      <aside className="sidebar">
        <Link to="/" className="brand" aria-label="循课首页">
          <Brand />
        </Link>
        <div className="sidebar-label">学习工作室</div>
        <nav aria-label="主要导航">{navigationLinks()}</nav>
        <div className="sidebar-footer">
          <GraduationCap size={17} /> 有依据的个性化学习
        </div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <button
            type="button"
            className="icon-button mobile-menu"
            aria-label="打开导航"
            aria-expanded={menuOpen}
            aria-haspopup="dialog"
            onClick={() => setMenuOpen(true)}
          >
            <Menu />
          </button>
          <Link to="/" className="mobile-brand" aria-label="循课首页">
            <img src="/brand/xunke-logo.svg" width={28} height={28} alt="" />
            <span>循课</span>
          </Link>
          <div className="breadcrumb">
            <span>学习工作室</span>
            <ChevronRight size={14} />
            <strong>
              {location.pathname.startsWith('/evaluations')
                ? '评测工作台'
                : location.pathname.startsWith('/knowledge')
                  ? '我的资料'
                  : location.pathname.startsWith('/qa')
                    ? '资料问答'
                    : location.pathname.startsWith('/study')
                      ? '我的课程'
                      : location.pathname.startsWith('/me')
                        ? '个人中心'
                        : '学习首页'}
            </strong>
          </div>
          <div className="topbar-right">
            {user ? (
              <Link to="/me" className="account-link" aria-label="我的账户">
                <span className="avatar">
                  {safeImageUrl(user.avatar_url) ? (
                    <img src={safeImageUrl(user.avatar_url)} alt="" />
                  ) : (
                    user.nickname.slice(0, 1)
                  )}
                </span>
                <span>{user.nickname}</span>
              </Link>
            ) : (
              <Link to="/login" className="button button-small secondary">
                <LogIn size={16} />
                登录
              </Link>
            )}
          </div>
        </header>
        <main id="main-content" className="main-content" tabIndex={-1}>
          <ErrorNotice
            error={error}
            onRetry={() => {
              void refresh()
            }}
          />
          <Outlet />
        </main>
        <footer className="workspace-footer">
          <span>循课</span>
          <span>让知识有来处，让进步看得见。</span>
        </footer>
      </div>
      <nav className="mobile-tabs" aria-label="手机导航">
        {navigation.slice(0, 3).map(({ to, icon: Icon, label, end }) => (
          <NavLink key={to} to={to} end={end}>
            <Icon size={20} />
            <span>{label}</span>
          </NavLink>
        ))}
        <button
          type="button"
          aria-label="更多导航"
          aria-haspopup="dialog"
          aria-expanded={menuOpen}
          onClick={() => setMenuOpen(true)}
        >
          <MoreHorizontal size={20} />
          <span>更多</span>
        </button>
      </nav>
      {menuOpen && (
        <Dialog title="导航" onClose={() => setMenuOpen(false)} className="navigation-dialog">
          <nav aria-label="全部导航">{navigationLinks()}</nav>
        </Dialog>
      )}
      <TaskNotifications />
    </div>
  )
}
