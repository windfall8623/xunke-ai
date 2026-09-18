import './styles/tokens.scss'
import './styles/base.scss'
import './styles/layouts/app-shell.scss'
import './styles/pages/home.scss'
import './styles/knowledge.scss'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter } from 'react-router-dom'
import { AppRoutes } from './app/router'
import { ApiError } from './services/http'
import './styles/course-print.scss'

const client = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15_000,
      retry: (count, error) => count < 1 && error instanceof ApiError && error.status >= 500,
    },
    mutations: { retry: false },
  },
})
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={client}>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
)
