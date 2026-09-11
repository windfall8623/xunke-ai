import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api } from '../services/api'
import { ApiError, setCsrfToken } from '../services/http'
import { clearQaSubmissions } from '../services/qaDrafts'
import type { AuthSession, User } from '../types/api'

type AuthState = 'initializing' | 'authenticated' | 'guest' | 'expired'
type AuthContextValue = {
  status: AuthState
  user: User | null
  error: string | null
  acceptSession: (session: AuthSession) => Promise<void>
  logout: () => Promise<void>
  refresh: () => Promise<void>
  forget: () => void
}
const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const client = useQueryClient()
  const [status, setStatus] = useState<AuthState>('initializing')
  const [user, setUser] = useState<User | null>(null)
  const [error, setError] = useState<string | null>(null)
  const identity = useRef<number | null>(null)
  const generation = useRef(0)
  const acceptSession = useCallback(
    async (session: AuthSession) => {
      const currentGeneration = ++generation.current
      if (identity.current !== session.user.id) {
        await client.cancelQueries()
        client.clear()
      }
      if (currentGeneration !== generation.current) return
      clearQaSubmissions(session.user.id)
      identity.current = session.user.id
      setCsrfToken(session.csrf_token)
      setUser(session.user)
      setStatus('authenticated')
      setError(null)
    },
    [client],
  )
  const clear = useCallback(
    (next: AuthState) => {
      generation.current++
      clearQaSubmissions()
      identity.current = null
      setCsrfToken(null)
      setUser(null)
      setStatus(next)
      void client.cancelQueries()
      client.clear()
    },
    [client],
  )
  const refresh = useCallback(async () => {
    const currentGeneration = ++generation.current
    try {
      const session = await api.session()
      if (currentGeneration === generation.current) await acceptSession(session)
    } catch (cause) {
      if (currentGeneration !== generation.current) return
      if (cause instanceof ApiError && cause.status === 401) {
        clear('guest')
        setError(null)
      } else {
        clear('guest')
        setError(cause instanceof Error ? cause.message : '暂时无法连接服务')
      }
    }
  }, [acceptSession, clear])
  useEffect(() => {
    void refresh()
    const expired = () => clear('expired')
    window.addEventListener('session-expired', expired)
    return () => {
      generation.current++
      window.removeEventListener('session-expired', expired)
    }
  }, [clear, refresh])
  const logout = useCallback(async () => {
    await api.logout()
    clear('guest')
  }, [clear])
  const forget = useCallback(() => clear('guest'), [clear])
  return (
    <AuthContext.Provider value={{ status, user, error, acceptSession, logout, refresh, forget }}>
      {children}
    </AuthContext.Provider>
  )
}
export function useAuth() {
  const value = useContext(AuthContext)
  if (!value) throw new Error('AuthProvider is required')
  return value
}
export function useIdentityKey() {
  return useAuth().user?.id ?? 'guest'
}
