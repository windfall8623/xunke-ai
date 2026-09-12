import type { Page } from '@playwright/test'
import type {
  QaAnswer,
  QaFeedback,
  QaMessage,
  QaMessageCreate,
  QaScopeUpdate,
  QaSession,
  QaTask,
} from '../src/types/qa'
import {
  qaAnswer,
  qaDocument,
  qaEvidence,
  qaMessages,
  qaSession,
  qaTask,
} from '../src/test/qaFixtures'
import { installTestApi } from './fixtures'

export async function installQaApi(
  page: Page,
  { existing = true, completed = true, longContent = false } = {},
) {
  const base = await installTestApi(page)
  base.documents = [qaDocument]
  const initialAnswer: QaAnswer = longContent
    ? {
        ...qaAnswer,
        blocks: [
          {
            ...qaAnswer.blocks[0],
            text:
              '这是合成测试资料中的字面文本：<img src=x onerror=alert(1)>。\n' +
              'LongUnbrokenKnowledgeText'.repeat(35),
          },
        ],
        evidence: [{ ...qaEvidence, title: '非常长的合成学习资料名称'.repeat(12) + '.pdf' }],
      }
    : qaAnswer
  const state = {
    base,
    sessions: (existing ? [qaSession] : []).map((item) => ({ ...item })) as QaSession[],
    messages: (existing && completed
      ? [
          qaMessages[0],
          { ...qaMessages[1], content: initialAnswer.blocks[0].text, answer: initialAnswer },
        ]
      : []
    ).map((message) => ({ ...message })) as QaMessage[],
    tasks: new Map<string, QaTask>(),
    submissions: [] as Array<{ key: string; data: QaMessageCreate }>,
    creations: [] as Array<Record<string, unknown>>,
    scopeUpdates: [] as QaScopeUpdate[],
    feedback: [] as QaFeedback[],
    revoked: false,
    abortNextSubmit: false,
    failTasks: false,
    scopeConflicts: 0,
    taskReads: 0,
    pendingTaskId: null as string | null,
    idempotency: new Map<string, { taskId: string; data: QaMessageCreate }>(),
    complete(taskId: string) {
      const task = state.tasks.get(taskId)!
      const answer: QaAnswer = {
        ...qaAnswer,
        answer_id: `answer-${taskId}`,
        message_id: task.message_id,
        scope_revision: state.sessions[0].scope_revision,
      }
      Object.assign(task, { status: 'completed', stage: 'completed', answer })
      state.messages = state.messages.map((message) =>
        message.task_id === taskId
          ? {
              ...message,
              status: 'completed',
              ...(message.role === 'assistant'
                ? { answer, content: answer.blocks.map((block) => block.text).join('\n\n') }
                : {}),
            }
          : message,
      )
      state.sessions[0].active_task_id = null
      state.pendingTaskId = null
      return answer
    },
  }
  await page.route('**/api/v1/qa/**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname.replace('/api/v1', '')
    const method = request.method()
    const respond = (data: unknown, status = 200) =>
      route.fulfill({
        status,
        contentType: 'application/json',
        body: JSON.stringify({ code: 0, message: 'ok', data }),
      })
    const fail = (status: number, message: string) =>
      route.fulfill({
        status,
        contentType: 'application/json',
        body: JSON.stringify({
          code: status * 10,
          error_code: status === 401 ? 'AUTH_REQUIRED' : 'SOURCE_UNAVAILABLE',
          message,
          data: null,
        }),
      })
    if (!base.authenticated) return fail(401, '登录已失效')
    if (method !== 'GET') base.mutationHeaders.push(request.headers())
    const view = (session: QaSession) =>
      state.revoked
        ? {
            ...session,
            scope: null,
            source_status: 'revoked',
            active_task_id: null,
            title: '资料已失效的会话',
          }
        : session
    if (path === '/qa/sessions') {
      if (method === 'POST') {
        const data = request.postDataJSON()
        state.creations.push(data)
        const chosen = data.scope.documents[0]
        const session: QaSession = {
          ...qaSession,
          title: data.title || '新的资料问答',
          scope: {
            ...qaSession.scope,
            documents: [
              {
                ...qaSession.scope.documents[0],
                section_ids: chosen.section_ids || [],
                section_catalog_revision: chosen.section_catalog_revision || null,
              },
            ],
          },
        }
        state.sessions.unshift(session)
        return respond(session, 201)
      }
      const page = Number(url.searchParams.get('page') || '1')
      return respond({
        items: state.sessions.slice((page - 1) * 20, page * 20).map(view),
        total: state.sessions.length,
        page,
        page_size: 20,
      })
    }
    const sessionMatch = path.match(/^\/qa\/sessions\/([^/]+)(?:\/(messages|scope))?$/)
    if (sessionMatch) {
      const session = state.sessions.find(
        (item) => item.session_id === decodeURIComponent(sessionMatch[1]),
      )
      if (!session) return fail(404, '会话不存在')
      if (sessionMatch[2] === 'scope') {
        const data = request.postDataJSON() as QaScopeUpdate
        state.scopeUpdates.push(data)
        if (state.scopeConflicts > 0) {
          state.scopeConflicts--
          session.scope_revision++
          return fail(409, '范围已由另一页面更新，请重新确认')
        }
        if (session.active_task_id || data.expected_revision !== session.scope_revision)
          return fail(409, '范围已变化或任务正在进行')
        session.scope_revision++
        state.revoked = false
        return respond(session)
      }
      if (sessionMatch[2] === 'messages') {
        if (method === 'POST') {
          const data = request.postDataJSON() as QaMessageCreate
          const key = request.headers()['idempotency-key'] || ''
          state.submissions.push({ key, data })
          if (!key) return fail(422, '缺少幂等键')
          const replay = state.idempotency.get(key)
          if (replay)
            return JSON.stringify(replay.data) === JSON.stringify(data)
              ? respond(state.tasks.get(replay.taskId), 202)
              : fail(409, '幂等键冲突')
          if (state.revoked) return fail(404, '资料已撤权')
          if (session.active_task_id || data.scope_revision !== session.scope_revision)
            return fail(409, '会话已变化，请刷新')
          const taskId = `qa-task-${state.tasks.size + 1}`
          const sequence = Math.max(0, ...state.messages.map((message) => message.sequence)) + 1
          const task: QaTask = {
            ...qaTask,
            task_id: taskId,
            message_id: `${taskId}-assistant`,
            status: state.failTasks ? 'failed' : 'pending',
            error_code: state.failTasks ? 'PROVIDER_UNAVAILABLE' : null,
            error_message: state.failTasks ? '回答服务暂不可用' : null,
          }
          state.messages.push(
            {
              ...qaMessages[0],
              message_id: `${taskId}-user`,
              sequence,
              content: data.content,
              scope_revision: data.scope_revision,
              task_id: taskId,
            },
            {
              ...qaMessages[1],
              message_id: task.message_id,
              sequence: sequence + 1,
              content: '',
              scope_revision: data.scope_revision,
              task_id: taskId,
              status: task.status,
              answer: null,
              error_code: task.error_code,
            },
          )
          state.tasks.set(taskId, task)
          state.idempotency.set(key, { taskId, data })
          session.active_task_id = state.failTasks ? null : taskId
          state.pendingTaskId = session.active_task_id
          if (state.abortNextSubmit) {
            state.abortNextSubmit = false
            return route.abort('connectionreset')
          }
          return respond(task, 202)
        }
        const before = Number(url.searchParams.get('before_sequence') || 'Infinity')
        const size = Number(url.searchParams.get('page_size') || '20')
        const available = state.messages.filter((message) => message.sequence < before)
        const selected = available.slice(-size)
        const items = state.revoked
          ? selected.map((message) => ({
              ...message,
              content: '资料已不可用',
              answer: null,
              status: 'revoked',
              error_code: null,
            }))
          : selected
        return respond({
          items,
          has_more: available.length > size,
          next_before: available.length > size ? selected[0].sequence : null,
        })
      }
      return respond(view(session))
    }
    const taskMatch = path.match(/^\/qa\/tasks\/([^/]+)(\/cancel)?$/)
    if (taskMatch) {
      state.taskReads++
      if (state.revoked) return fail(404, '来源已撤权')
      const task = state.tasks.get(decodeURIComponent(taskMatch[1]))
      if (!task) return fail(404, '任务不存在')
      if (taskMatch[2]) {
        Object.assign(task, { status: 'cancelled', stage: 'cancelled' })
        state.sessions[0].active_task_id = null
        state.messages = state.messages.map((message) =>
          message.task_id === task.task_id && message.role === 'assistant'
            ? { ...message, status: 'cancelled' }
            : message,
        )
        state.pendingTaskId = null
      }
      return respond(task)
    }
    if (path.includes('/evidence/'))
      return state.revoked
        ? fail(404, '来源已撤权')
        : respond(
            longContent
              ? {
                  ...qaEvidence,
                  title: initialAnswer.evidence[0].title,
                  excerpt: qaEvidence.excerpt + '\n' + 'CanonicalSourceText'.repeat(70),
                }
              : qaEvidence,
          )
    if (path.endsWith('/feedback')) {
      if (state.revoked) return fail(404, '来源已撤权')
      state.feedback.push(request.postDataJSON())
      return respond({ feedback_id: 'qa-feedback-1' })
    }
    return fail(404, '未配置的问答测试接口')
  })
  return state
}
