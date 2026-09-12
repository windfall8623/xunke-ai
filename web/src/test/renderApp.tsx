import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { vi } from 'vitest'
import { AppRoutes } from '../app/router'

export function renderApp(
  path: string,
  handler: (path: string, init: RequestInit) => Response | Promise<Response>,
) {
  vi.stubGlobal('fetch', async (url: string, init: RequestInit = {}) => handler(url, init))
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return {
    ...render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[path]}>
          <AppRoutes />
        </MemoryRouter>
      </QueryClientProvider>,
    ),
    client,
  }
}
