import {
  BookOpen,
  ChevronRight,
  FlaskConical,
  GraduationCap,
  Library,
  LogIn,
  Menu,
  MessageCircle,
  Sparkles,
  UserRound,
  X,
} from 'lucide-react'
import { useState } from 'react'
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from '../app/AuthProvider'
import { Brand } from './Brand'
import { TaskNotifications } from './TaskNotifications'
import { ErrorNotice, safeImageUrl } from './ui'

export function AppShell() {
  const { user, error, refresh } = useAuth()
  const location = useLocation()
  const [menuOpen, setMenuOpen] = useState(false)
  const evaluator = user?.role === 'evaluator'
  const navigation = [
    { to: '/', icon: BookOpen, label: '开始学习', end: true },
    { to: '/knowledge', icon: Library, label: '我的资料', end: false },
    { to: '/qa', icon: MessageCircle, label: '知识库问答', end: false },
    { to: '/study', icon: GraduationCap, label: '我的课程', end: false },
    { to: '/me', icon: UserRound, label: '学习记录', end: false },
    ...(evaluator
      ? [{ to: '/evaluations', icon: FlaskConical, label: '评测工作台', end: false }]
      : []),
  ]
  return (
    <div className="app-layout">
      <a className="skip-link" href="#main-content">
        跳到主要内容
      </a>
      <aside className={`sidebar ${menuOpen ? 'is-open' : ''}`}>
        <Link to="/" className="brand" aria-label="循课首页" onClick={() => setMenuOpen(false)}>
          <Brand />
        </Link>
        <div className="sidebar-label">我的学习空间</div>
        <nav aria-label="主要导航">
          {navigation.map(({ to, icon: Icon, label, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              onClick={() => setMenuOpen(false)}
              className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}
            >
              <Icon size={20} />
              <span>{label}</span>
              {to === '/' && <ChevronRight size={15} className="nav-arrow" />}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-note">
          <Sparkles size={23} />
          <strong>每一步，都算数。</strong>
          <p>
            把好奇变成知识，
            <br />
            把练习变成理解。
          </p>
          <span>每天留一点时间给自己</span>
        </div>
        <div className="sidebar-footer">
          <GraduationCap size={17} /> 有依据的个性化学习
        </div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <button
            type="button"
            className="icon-button mobile-menu"
            aria-label={menuOpen ? '关闭导航' : '打开导航'}
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen(!menuOpen)}
          >
            {menuOpen ? <X /> : <Menu />}
          </button>
          <Link to="/" className="mobile-brand" aria-label="循课首页">
            <img src="/brand/xunke-logo.svg" width={28} height={28} alt="" />
            <span>循课</span>
          </Link>
          <div className="breadcrumb">
            <span>学习空间</span>
            <ChevronRight size={14} />
            <strong>
              {location.pathname.startsWith('/evaluations')
                ? '评测工作台'
                : location.pathname.startsWith('/knowledge')
                  ? '资料管理'
                  : location.pathname.startsWith('/qa')
                    ? '知识库问答'
                    : location.pathname.startsWith('/study')
                      ? '学习空间'
                      : location.pathname.startsWith('/me')
                        ? '学习记录'
                        : '探索与练习'}
            </strong>
          </div>
          <div className="topbar-right">
            {user ? (
              <Link to="/me" className="account-link">
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
        {navigation.map(({ to, icon: Icon, label, end }) => (
          <NavLink key={to} to={to} end={end}>
            <Icon size={20} />
            <span>{label}</span>
          </NavLink>
        ))}
      </nav>
      <TaskNotifications />
    </div>
  )
}
