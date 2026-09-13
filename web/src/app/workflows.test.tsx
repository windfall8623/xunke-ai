import { act, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiFailure, documentFixture, json, learner, quiz, session } from '../test/fixtures'
import { renderApp } from '../test/renderApp'
import type { SourceExcerpt } from '../types/api'

afterEach(() => vi.unstubAllGlobals())

describe('source lifecycle and private feedback', () => {
  it('rejects an oversized browser upload before transmission', async () => {
    const uploads: unknown[] = []
    renderApp('/knowledge', (path, init) => {
      if (path.endsWith('/auth/session')) return json(session)
      if (init.method === 'POST') uploads.push(init.body)
      return json({ items: [], total: 0 })
    })
    await screen.findByRole('heading', { name: '我的资料' })
    const file = new File(['x'], '大文件.pdf', { type: 'application/pdf' })
    Object.defineProperty(file, 'size', { value: 10 * 1024 * 1024 + 1 })
    await userEvent.upload(screen.getByLabelText('选择资料文件'), file)
    expect(await screen.findByRole('alert')).toHaveTextContent('10 MB')
    expect(uploads).toEqual([])
  })

  it('uploads a real browser File and renders its persisted processing state', async () => {
    let uploaded = false
    let receivedName = ''
    renderApp('/knowledge', (path, init) => {
      if (path.endsWith('/auth/session')) return json(session)
      if (init.method === 'POST') {
        receivedName = ((init.body as FormData).get('file') as File).name
        uploaded = true
        return json({ ...documentFixture, file_name: '笔记.txt', status: 'processing' }, 202)
      }
      return json({
        items: uploaded
          ? [{ ...documentFixture, file_name: '笔记.txt', status: 'processing' }]
          : [],
        total: uploaded ? 1 : 0,
      })
    })
    await screen.findByRole('heading', { name: '我的资料' })
    await userEvent.upload(
      screen.getByLabelText('选择资料文件'),
      new File(['集合基础'], '笔记.txt', { type: 'text/plain' }),
    )
    expect(await screen.findByRole('heading', { name: '笔记.txt' })).toBeVisible()
    expect(receivedName).toBe('笔记.txt')
    expect(screen.getByText('正在处理')).toBeVisible()
  })

  it('reads an authorized excerpt and renders source text as text', async () => {
    renderApp('/quizzes/quiz-1', (path) => {
      if (path.endsWith('/auth/session')) return json(session)
      if (path.endsWith('/user/quizzes/quiz-1')) return json(quiz)
      if (path.endsWith('/evidence/e1'))
        return json({
          evidence_id: 'e1',
          title: '离散数学',
          status: 'available',
          source_type: 'document',
          excerpt: '集合的元素具有互异性。<script>alert(1)</script>',
          locator: { page: 2, block_id: 'block-1', start_char: 0, end_char: 11 },
        })
      return apiFailure(404)
    })
    await screen.findByRole('heading', { name: '集合基础练习' })
    await userEvent.click(screen.getByRole('button', { name: '查看来源 1' }))
    const panel = await screen.findByRole('dialog', { name: '题目依据' })
    expect(
      await within(panel).findByText('集合的元素具有互异性。<script>alert(1)</script>'),
    ).toBeVisible()
    expect(within(panel).getByText('第 2 页')).toBeVisible()
    expect(panel.querySelector('script')).toBeNull()
  })

  it('shows the saved Markdown heading and exact line range from the server locator', async () => {
    renderApp('/quizzes/quiz-1', (path) => {
      if (path.endsWith('/auth/session')) return json(session)
      if (path.endsWith('/user/quizzes/quiz-1')) return json(quiz)
      if (path.endsWith('/evidence/e1'))
        return json({
          evidence_id: 'e1',
          title: '集合笔记.md',
          source_type: 'document',
          excerpt: '空集是任意集合的子集。',
          locator: {
            heading_path: ['第一章', '空集'],
            paragraph: 3,
            line_start: 12,
            line_end: 14,
          },
        })
      return apiFailure(404)
    })
    await screen.findByRole('heading', { name: '集合基础练习' })
    await userEvent.click(screen.getByRole('button', { name: '查看来源 1' }))
    const panel = await screen.findByRole('dialog', { name: '题目依据' })
    expect(await within(panel).findByText('第一章 / 空集 · 第 3 段 · 第 12–14 行')).toBeVisible()
  })

  it('keeps evaluation sharing off unless explicitly selected in feedback', async () => {
    let payload: Record<string, unknown> | undefined
    renderApp('/quizzes/quiz-1', (path, init) => {
      if (path.endsWith('/auth/session')) return json(session)
      if (path.endsWith('/user/quizzes/quiz-1')) return json(quiz)
      if (path.endsWith('/feedback')) {
        payload = JSON.parse(init.body as string)
        return json({ feedback_id: 'feedback-1' })
      }
      return apiFailure(404)
    })
    await screen.findByRole('heading', { name: '集合基础练习' })
    await userEvent.click(screen.getByRole('button', { name: '反馈题目问题' }))
    expect(screen.getByRole('checkbox', { name: /允许用于后续评测/ })).not.toBeChecked()
    await userEvent.selectOptions(screen.getByLabelText('问题类型'), 'incorrect_answer')
    await userEvent.type(screen.getByLabelText('补充说明'), '此处答案与第二页定义不符。')
    await userEvent.click(screen.getByRole('button', { name: '提交反馈' }))
    expect(await screen.findByText('反馈已收到，感谢帮助我们改进。')).toBeVisible()
    expect(payload).toMatchObject({
      question_id: 'q1',
      reason: 'incorrect_answer',
      allow_evaluation_use: false,
    })
  })
})

const previewDocument = {
  ...documentFixture,
  sections: [...documentFixture.sections, { section_id: 'section-child', title: '空集' }],
}
const previewBlocks: SourceExcerpt['blocks'] = [
  { block_id: 'cover', start_char: 0, end_char: 10, section_id: 'cover', kind: 'page', page: 1 },
  { block_id: 'selected', start_char: 20, end_char: 50, section_id: 'section-1', kind: 'page', page: 2 },
  { block_id: 'child', start_char: 70, end_char: 100, section_id: 'section-child', kind: 'page', page: 4 },
]
function previewSource(blockId = 'cover'): SourceExcerpt {
  const block = previewBlocks.find((item) => item.block_id === blockId)!
  return {
    doc_id: 'doc-1', version_id: 'version-1', parse_artifact_id: 'parse-1',
    source_sha256: 'source-hash', canonical_text_hash: 'canonical-hash',
    block_id: block.block_id,
    excerpt: { cover: '范围外的封面片段', selected: '集合的元素具有互异性。', child: '空集是任意集合的子集。' }[blockId]!,
    locator: { ...block, quote_hash: 'quote-hash' },
    blocks: previewBlocks,
    sections: [
      { section_id: 'section-1', title: '第一节 集合基础', level: 1, start_char: 20, end_char: 200 },
      { section_id: 'section-child', title: '空集', heading_path: ['第一节 集合基础', '空集'], level: 2, start_char: 60, end_char: 140 },
    ],
  }
}

async function selectCourseDocument() {
  await userEvent.click(await screen.findByRole('radio', { name: /根据我的资料/ }))
  await userEvent.click(await screen.findByRole('checkbox', { name: documentFixture.file_name }))
}

describe('course source previews and upload context', () => {
  it('previews only a selected parent range and its children using immutable source identities', async () => {
    const reads: URL[] = []
    renderApp('/study/courses/new', (path) => {
      if (path.endsWith('/auth/session')) return json(session)
      if (path.endsWith('/courses/capabilities')) return json({ teaching_modes: ['fast', 'guided'] })
      if (path.endsWith('/knowledge/documents')) return json({ items: [previewDocument], total: 1 })
      if (path.includes('/source?')) {
        const url = new URL(path, 'http://localhost')
        reads.push(url)
        return json(previewSource(url.searchParams.get('block_id') || undefined))
      }
      return json({})
    })
    await selectCourseDocument()
    await userEvent.click(screen.getByRole('checkbox', { name: '第一节 集合基础' }))
    expect(reads).toHaveLength(0)
    await userEvent.click(screen.getByRole('button', { name: /预览已识别内容/ }))
    expect(await screen.findByText('集合的元素具有互异性。')).toBeVisible()
    expect(screen.queryByText('范围外的封面片段')).not.toBeInTheDocument()
    expect(screen.getByText('已识别出文字的页码：2、4')).toBeVisible()
    await userEvent.click(screen.getByRole('button', { name: '查看 第一节 集合基础 / 空集' }))
    expect(await screen.findByText('空集是任意集合的子集。')).toBeVisible()
    expect(screen.queryByText('集合的元素具有互异性。')).not.toBeInTheDocument()
    expect(reads.map((url) => url.searchParams.get('block_id'))).toEqual([null, 'selected', 'child'])
    expect(reads.every((url) => url.searchParams.get('version_id') === 'version-1' && url.searchParams.get('parse_artifact_id') === 'parse-1')).toBe(true)
  })

  it('hides a formerly readable excerpt after a source 404 without dropping the draft', async () => {
    let missing = false
    renderApp('/study/courses/new', (path) => {
      if (path.endsWith('/auth/session')) return json(session)
      if (path.endsWith('/courses/capabilities')) return json({ teaching_modes: ['fast', 'guided'] })
      if (path.endsWith('/knowledge/documents')) return json({ items: [previewDocument], total: 1 })
      if (path.includes('/source?')) return missing ? apiFailure(404) : json(previewSource())
      return json({})
    })
    await userEvent.type(await screen.findByLabelText(/学习主题/), '保留课程主题')
    await selectCourseDocument()
    await userEvent.click(screen.getByRole('button', { name: /预览已识别内容/ }))
    await screen.findByText('范围外的封面片段')
    missing = true
    await userEvent.click(screen.getByRole('button', { name: '重新读取片段' }))
    expect(await screen.findByText('这份资料的当前版本暂不可用，请刷新资料列表后重新选择。')).toBeVisible()
    expect(screen.queryByText('范围外的封面片段')).not.toBeInTheDocument()
    expect(screen.getByLabelText(/学习主题/)).toHaveValue('保留课程主题')
  })

  it('closes a preview, removes its private cache and clears selection when the catalog version changes', async () => {
    let currentDocument = previewDocument
    const { client } = renderApp('/study/courses/new', (path) => {
      if (path.endsWith('/auth/session')) return json(session)
      if (path.endsWith('/courses/capabilities')) return json({ teaching_modes: ['fast', 'guided'] })
      if (path.endsWith('/knowledge/documents')) return json({ items: [currentDocument], total: 1 })
      if (path.includes('/source?')) return json(previewSource())
      return json({})
    })
    await selectCourseDocument()
    await userEvent.click(screen.getByRole('button', { name: /预览已识别内容/ }))
    await screen.findByText('范围外的封面片段')
    currentDocument = { ...previewDocument, active_version_id: 'version-2', section_catalog_revision: 'parse-2', document_revision: 2 }
    await act(async () => { await client.invalidateQueries({ queryKey: [learner.id, 'documents'] }) })
    expect(await screen.findByText('资料版本已变化，已清除旧选择，请重新确认资料。')).toBeVisible()
    expect(screen.queryByText('范围外的封面片段')).not.toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: documentFixture.file_name })).not.toBeChecked()
    await waitFor(() => expect(client.getQueryCache().findAll({ queryKey: [learner.id, 'course-source-preview'] })).toHaveLength(0))
  })

  it('rejects a source response for a different version before displaying its text', async () => {
    renderApp('/study/courses/new', (path) => {
      if (path.endsWith('/auth/session')) return json(session)
      if (path.endsWith('/courses/capabilities')) return json({ teaching_modes: ['fast', 'guided'] })
      if (path.endsWith('/knowledge/documents')) return json({ items: [previewDocument], total: 1 })
      if (path.includes('/source?')) return json({ ...previewSource(), version_id: 'unexpected-version' })
      return json({})
    })
    await selectCourseDocument()
    await userEvent.click(screen.getByRole('button', { name: /预览已识别内容/ }))
    expect(await screen.findByText('资料版本与当前选择不一致，请刷新资料列表后重新选择。')).toBeVisible()
    expect(screen.queryByText('范围外的封面片段')).not.toBeInTheDocument()
  })

  it('retains the creation draft after upload but requires the processing document to become ready and be selected', async () => {
    let received = false
    let uploads = 0
    const creations: unknown[] = []
    const document = { ...documentFixture, file_name: '新课程笔记.txt', status: 'processing' }
    renderApp('/study/courses/new', (path, init) => {
      if (path.endsWith('/auth/session')) return json(session)
      if (path.endsWith('/courses/capabilities')) return json({ teaching_modes: ['fast', 'guided'] })
      if (path.endsWith('/knowledge/documents')) {
        if (init.method === 'POST') { received = true; uploads++; return json(document, 202) }
        return json({ items: received ? [document] : [], total: received ? 1 : 0 })
      }
      if (path === '/api/v1/courses' && init.method === 'POST') creations.push(init.body)
      return json({})
    })
    await userEvent.type(await screen.findByLabelText(/学习主题/), '结合笔记学习集合')
    await userEvent.click(screen.getByRole('radio', { name: /快速生成/ }))
    await userEvent.click(screen.getByRole('radio', { name: /根据我的资料/ }))
    await userEvent.click(await screen.findByRole('button', { name: '上传资料' }))
    await userEvent.upload(screen.getByLabelText('选择资料文件'), new File(['学习笔记'], '新课程笔记.txt', { type: 'text/plain' }))
    await screen.findByText(/上传已收到/)
    await userEvent.click(screen.getByRole('button', { name: '返回课程草稿' }))
    expect(screen.getByLabelText(/学习主题/)).toHaveValue('结合笔记学习集合')
    expect(screen.getByRole('radio', { name: /快速生成/ })).toBeChecked()
    expect(await screen.findByText(/已收到：新课程笔记.txt/)).toHaveTextContent('正在处理')
    expect(screen.getByRole('button', { name: '生成课程纲要' })).toBeDisabled()
    expect(screen.queryByRole('checkbox', { name: '新课程笔记.txt' })).not.toBeInTheDocument()
    expect(uploads).toBe(1)
    expect(creations).toEqual([])
  })
})

describe('profile and preset experience', () => {
  it('does not let a late unauthenticated bootstrap overwrite a successful login', async () => {
    let resolveBootstrap!: (response: Response) => void
    renderApp('/login', (path) => {
      if (path.endsWith('/auth/session'))
        return new Promise((resolve) => {
          resolveBootstrap = resolve
        })
      if (path.endsWith('/auth/login')) return json(session)
      return json({ items: [], total: 0 })
    })
    await screen.findByRole('heading', { name: '欢迎回来' })
    await userEvent.type(screen.getByLabelText('账号或邮箱'), 'xiaoyu')
    await userEvent.type(screen.getByLabelText('密码', { exact: true }), 'a-strong-password')
    await userEvent.click(screen.getByRole('button', { name: '登录' }))
    await screen.findByRole('button', { name: '生成练习' })
    await act(async () => {
      resolveBootstrap(apiFailure())
      await Promise.resolve()
    })
    expect(screen.getByRole('button', { name: '生成练习' })).toBeVisible()
  })

  it('changes a password then clears the old session and returns to login', async () => {
    let changed = false
    renderApp('/me', (path, init) => {
      if (path.endsWith('/auth/session')) return changed ? apiFailure() : json(session)
      if (path.endsWith('/auth/change-password')) {
        expect(JSON.parse(init.body as string)).toEqual({
          current_password: 'old-password',
          new_password: 'new-password-long',
        })
        changed = true
        return json(null)
      }
      if (path.endsWith('/user/profile'))
        return json({ ...learner, quiz_count: 0, correct_count: 0, average_accuracy: 0 })
      return json({ items: [], total: 0 })
    })
    await screen.findByRole('heading', { name: '学习记录' })
    await userEvent.click(screen.getByRole('button', { name: '修改密码' }))
    await userEvent.type(screen.getByLabelText('当前密码'), 'old-password')
    await userEvent.type(screen.getByLabelText('新密码'), 'new-password-long')
    await userEvent.click(screen.getByRole('button', { name: '保存新密码' }))
    expect(await screen.findByRole('heading', { name: '欢迎回来' })).toBeVisible()
    expect(changed).toBe(true)
  })
  it('provides a local preset exercise without a generation request', async () => {
    const writes: string[] = []
    renderApp('/demo', (path, init) => {
      if (init.method !== 'GET') writes.push(path)
      return apiFailure()
    })
    expect(await screen.findByRole('heading', { name: '高效学习，从理解开始' })).toBeVisible()
    expect(screen.getByText(/预置体验 · 不调用 AI/)).toBeVisible()
    await userEvent.click(screen.getByRole('radio', { name: /尝试不看笔记回忆要点/ }))
    await userEvent.click(screen.getByRole('button', { name: '提交答案' }))
    expect(await screen.findByText('回答正确')).toBeVisible()
    expect(writes).toEqual([])
  })

  it('shows unfinished study and saves a profile nickname', async () => {
    let name = learner.nickname
    renderApp('/me', (path, init) => {
      if (path.endsWith('/auth/session'))
        return json({ ...session, user: { ...learner, nickname: name } })
      if (path.endsWith('/user/profile')) {
        if (init.method === 'PUT') name = JSON.parse(init.body as string).nickname
        return json({
          ...learner,
          nickname: name,
          quiz_count: 3,
          correct_count: 12,
          average_accuracy: 80,
        })
      }
      if (path.includes('/user/quizzes?'))
        return json({
          items: [
            {
              quiz_id: 'quiz-1',
              title: '集合基础练习',
              question_count: 3,
              answered_count: 1,
              status: 'in_progress',
              report_status: 'not_started',
              created_at: '2026-09-07T00:00:00Z',
            },
          ],
          total: 1,
          page: 1,
          page_size: 10,
        })
      return apiFailure(404)
    })
    expect(await screen.findByRole('link', { name: /继续学习/ })).toHaveAttribute(
      'href',
      '/quizzes/quiz-1',
    )
    await userEvent.click(screen.getByRole('button', { name: '编辑资料' }))
    await userEvent.clear(screen.getByLabelText('昵称'))
    await userEvent.type(screen.getByLabelText('昵称'), '新的小鱼')
    await userEvent.click(screen.getByRole('button', { name: '保存资料' }))
    await waitFor(() => expect(name).toBe('新的小鱼'))
    expect(await screen.findByText('资料已保存')).toBeVisible()
  })
})
