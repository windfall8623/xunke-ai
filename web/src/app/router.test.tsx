import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AppRoutes } from './router'
import { apiFailure, documentFixture, json, questions, quiz, session } from '../test/fixtures'

function mount(
  path: string,
  handler: (path: string, init: RequestInit) => Response | Promise<Response>,
) {
  vi.stubGlobal('fetch', async (path: string, init: RequestInit = {}) => handler(path, init))
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <AppRoutes />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}
afterEach(() => vi.unstubAllGlobals())

describe('authentication and authorization', () => {
  it('redirects an expired protected page to the login form', async () => {
    mount('/knowledge', () => apiFailure())
    expect(await screen.findByRole('heading', { name: '欢迎回来' })).toBeVisible()
    expect(screen.queryByRole('button', { name: '上传资料' })).not.toBeInTheDocument()
  })

  it('signs in with a cookie session and resumes the requested protected page', async () => {
    let signedIn = false
    const bodies: unknown[] = []
    mount('/knowledge', (path, init) => {
      if (path.endsWith('/auth/login')) {
        bodies.push(JSON.parse(init.body as string))
        signedIn = true
        return json(session)
      }
      if (path.endsWith('/auth/session')) return signedIn ? json(session) : apiFailure()
      if (path.endsWith('/knowledge/documents')) return json({ items: [], total: 0 })
      return apiFailure(404)
    })
    await screen.findByRole('heading', { name: '欢迎回来' })
    await userEvent.type(screen.getByLabelText('账号或邮箱'), 'xiaoyu')
    await userEvent.type(screen.getByLabelText('密码', { exact: true }), 'a-strong-password')
    await userEvent.click(screen.getByRole('button', { name: '登录' }))
    expect(await screen.findByRole('heading', { name: '我的资料' })).toBeVisible()
    expect(bodies).toEqual([{ account: 'xiaoyu', password: 'a-strong-password' }])
    expect(localStorage.length).toBe(0)
  })

  it.each(['learner', 'admin', 'unrecognized'])(
    'hides the workbench without an evaluator grant (%s)',
    async (role) => {
      mount('/evaluations', (path) =>
        path.endsWith('/auth/session')
          ? json({ ...session, user: { ...session.user, role } })
          : apiFailure(403),
      )
      expect(await screen.findByRole('heading', { name: '此页面需要评测权限' })).toBeVisible()
      expect(screen.queryByRole('link', { name: '评测工作台' })).not.toBeInTheDocument()
    },
  )
})

describe('learning state and source consent', () => {
  it('creates strict document scope with the selected catalog revision and an idempotency key', async () => {
    let submitted: Record<string, unknown> | undefined
    let key: string | null = null
    mount('/', (path, init) => {
      if (path.endsWith('/auth/session')) return json(session)
      if (path.endsWith('/knowledge/documents')) return json({ items: [documentFixture], total: 1 })
      if (path.endsWith('/quiz/generate/async')) {
        submitted = JSON.parse(init.body as string)
        key = new Headers(init.headers).get('Idempotency-Key')
        return json({ task_id: 'task-1' }, 202)
      }
      if (path.endsWith('/quiz/task/task-1'))
        return json({ task_id: 'task-1', status: 'running', stage: 'retrieving' })
      return json({ items: [], total: 0 })
    })
    await screen.findByRole('heading', { name: /今天，想学点什么/ })
    await userEvent.type(screen.getByLabelText('学习目标'), '掌握集合基础')
    await userEvent.click(screen.getByRole('radio', { name: /根据我的资料/ }))
    await userEvent.click(await screen.findByRole('checkbox', { name: /离散数学/ }))
    await userEvent.click(screen.getByRole('checkbox', { name: '第一节 集合基础' }))
    await userEvent.click(screen.getByRole('button', { name: '生成练习' }))
    await waitFor(() =>
      expect(submitted).toMatchObject({
        user_input: '掌握集合基础',
        source_policy: 'strict_docs',
        scope: {
          type: 'selected_documents',
          documents: [
            { doc_id: 'doc-1', section_catalog_revision: 'parse-1', section_ids: ['section-1'] },
          ],
        },
      }),
    )
    expect(key).toBeTruthy()
    expect(await screen.findByRole('heading', { name: /正在准备你的练习/ })).toBeVisible()
  })

  it('reads authoritative answer progress on revisit without resubmitting previous answers', async () => {
    const saved: Record<string, unknown>[] = []
    let revision = 0
    const handler = (path: string, init: RequestInit) => {
      if (path.endsWith('/auth/session')) return json(session)
      if (path.endsWith('/user/quizzes/quiz-1'))
        return json({ ...quiz, answer_records: saved, revision })
      if (path.includes('/answers/')) {
        const questionId = path.split('/').at(-1)!
        const record = {
          ...JSON.parse(init.body as string),
          question_id: questionId,
          is_correct: true,
          correct_answers: ['A'],
          explanation: '依据原文，这个选项是正确的。',
          citation_refs: ['e1'],
        }
        saved.push(record)
        revision++
        return json({
          answer_record: record,
          revision,
          answered_count: saved.length,
          correct_count: saved.length,
        })
      }
      return apiFailure(404)
    }
    const view = mount('/quizzes/quiz-1', handler)
    await screen.findByRole('heading', { name: questions[0].stem })
    await userEvent.click(screen.getByRole('radio', { name: /只保留一个/ }))
    await userEvent.click(screen.getByRole('button', { name: '提交答案' }))
    expect(await screen.findByText('回答正确')).toBeVisible()
    await userEvent.click(screen.getByRole('button', { name: '下一题' }))
    await userEvent.click(screen.getByRole('radio', { name: /是任意集合的子集/ }))
    await userEvent.click(screen.getByRole('button', { name: '提交答案' }))
    await waitFor(() => expect(screen.getByTestId('answered-count')).toHaveTextContent('2'))
    await userEvent.click(screen.getByRole('button', { name: '上一题' }))
    expect(screen.getByRole('radio', { name: /只保留一个/ })).toBeDisabled()
    expect(saved).toHaveLength(2)
    view.unmount()
    mount('/quizzes/quiz-1', handler)
    expect(await screen.findByTestId('answered-count')).toHaveTextContent('2')
    expect(saved).toHaveLength(2)
  })

  it('shows settled stats while an AI report fails and never settles on page load', async () => {
    const writes: string[] = []
    mount('/quizzes/quiz-1/report', (path, init) => {
      if (init.method && init.method !== 'GET') writes.push(path)
      if (path.endsWith('/auth/session')) return json(session)
      if (path.endsWith('/report/quiz-1'))
        return json({
          quiz_id: 'quiz-1',
          total_questions: 3,
          correct_count: 2,
          accuracy: 66.7,
          xp_awarded: 14,
          report_status: 'failed',
          report: null,
        })
      if (path.endsWith('/user/quizzes/quiz-1')) return json({ ...quiz, status: 'settled' })
      return apiFailure(404)
    })
    expect(await screen.findByText('66.7%')).toBeVisible()
    expect(screen.getByText('+14')).toBeVisible()
    expect(screen.getByRole('button', { name: '重试生成分析' })).toBeVisible()
    expect(writes).toEqual([])
  })
})
