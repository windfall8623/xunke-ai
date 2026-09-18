import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiFailure, documentFixture, json, session } from '../test/fixtures'
import { renderApp } from '../test/renderApp'

const evaluatorSession = { ...session, user: { ...session.user, role: 'evaluator' } }
const adminSession = { ...session, user: { ...session.user, role: 'admin' } }
const frozen = {
  dataset_id: 'data-1',
  version: 1,
  name: '集合 smoke',
  status: 'frozen',
  revision: 3,
  checksum: 'hash-1',
  manifest: { authorization: 'synthetic', split_counts: { dev: 1 }, annotation_version: 1 },
  samples: [
    {
      sample_id: 'sample-1',
      case_type: 'retrieval',
      split: 'dev',
      query: '空集是什么？',
      family_id: 'family-1',
      source_refs: [],
      gold_evidence_groups: [],
    },
  ],
}
const run = {
  run_id: 'run-1',
  status: 'completed',
  stop_reason: null,
  progress: { total: 1, completed: 1, failed: 0, pending: 0, scoring: 0 },
  comparison_eligible: false,
  manifest: {
    dataset_id: 'data-1',
    dataset_version: 1,
    pipeline_id: 'dense-v1',
    max_cost_cny: 10,
    repeat_count: 1,
  },
  created_at: '2026-09-07T00:00:00Z',
}
const result = {
  result_id: 'result-1',
  sample_id: 'sample-1',
  repeat_index: 0,
  case_type: 'retrieval',
  status: 'completed',
  sample: frozen.samples[0],
  artifact: { evidence: [] },
  metrics: {
    faithfulness: {
      status: 'error',
      value: null,
      unknown_count: 1,
      reason: 'judge_error',
      unit: 'ratio',
    },
  },
  review: null,
  review_revision: 0,
  error_code: null,
}
afterEach(() => vi.unstubAllGlobals())

describe('evaluation workbench', () => {
  it('keeps evaluator history available without allowing system execution', async () => {
    renderApp('/evaluations/runs', (path) => {
      if (path.endsWith('/auth/session')) return json(evaluatorSession)
      if (path.endsWith('/eval/runs')) return json({ items: [run], total: 1 })
      return json({ items: [], total: 0 })
    })
    expect(await screen.findByText(/创建或恢复使用系统模型的评测运行需要管理员权限/)).toBeVisible()
    expect(await screen.findByRole('button', { name: '创建运行' })).toBeDisabled()
    expect(screen.getByRole('heading', { name: '运行记录' })).toBeVisible()
  })

  it.each(['evaluator', 'admin'])('limits resume actions for %s', async (role) => {
    renderApp('/evaluations/runs/run-1', (path) => {
      if (path.endsWith('/auth/session')) return json({ ...session, user: { ...session.user, role } })
      if (path.endsWith('/results')) return json({ items: [], total: 0 })
      return json({ ...run, status: 'cancelled', can_resume: true })
    })
    await screen.findByRole('heading', { name: '运行详情' })
    await waitFor(() => expect(screen.getByTestId('release-status')).toBeVisible())
    expect(!!screen.queryByRole('button', { name: '恢复运行' })).toBe(role === 'admin')
  })

  it('does not offer feedback promotion without explicit source-use authorization', async () => {
    renderApp('/evaluations/feedback', (path) => {
      if (path.endsWith('/auth/session')) return json(evaluatorSession)
      if (path.endsWith('/eval/feedback'))
        return json({
          items: [
            {
              feedback_id: 'f1',
              quiz_id: 'q1',
              question_id: 'q1-1',
              reason: 'incorrect_answer',
              comment: '请核对答案。',
              allow_evaluation_use: false,
              status: 'approved',
              revision: 1,
              review: null,
              promotion: null,
            },
          ],
          total: 1,
        })
      if (path.endsWith('/eval/datasets')) return json({ items: [], total: 0 })
      return apiFailure(404)
    })
    await screen.findByRole('heading', { name: '反馈与回归候选' })
    expect(await screen.findByText('未获准用于评测')).toBeVisible()
    expect(screen.queryByRole('button', { name: '建立评测候选' })).not.toBeInTheDocument()
  })

  it('preserves the redacted feedback request while a source copy prepares before promotion', async () => {
    const submitted: Record<string, unknown>[] = []
    let item: Record<string, unknown> = {
      feedback_id: 'f1',
      quiz_id: 'q1',
      question_id: 'q1-1',
      reason: 'citation_mismatch',
      comment: '引用不符。',
      allow_evaluation_use: true,
      status: 'approved',
      revision: 1,
      review: null,
      promotion: null,
    }
    renderApp('/evaluations/feedback', (path, init) => {
      if (path.endsWith('/auth/session')) return json(adminSession)
      if (path.endsWith('/eval/datasets')) return json({ items: [], total: 0 })
      if (path.endsWith('/promote')) {
        const request = JSON.parse(init.body as string)
        submitted.push(request)
        const { expected_revision: _, ...parameters } = request
        item = {
          ...item,
          status: submitted.length === 1 ? 'preparing' : 'promoted',
          promotion: {
            state: submitted.length === 1 ? 'preparing' : 'promoted',
            request: parameters,
            ...(submitted.length === 2 ? { dataset_id: 'candidate-1', dataset_version: 1 } : {}),
          },
        }
        return json({ status: item.status, feedback: item, documents: [] }, 202)
      }
      if (path.endsWith('/eval/feedback')) return json({ items: [item], total: 1 })
      return apiFailure(404)
    })
    await userEvent.type(await screen.findByLabelText('脱敏后的学习目标'), '核对集合的定义及出处')
    await userEvent.click(screen.getByRole('button', { name: '建立评测候选' }))
    await userEvent.click(await screen.findByRole('button', { name: '继续建立候选' }))
    await waitFor(() => expect(submitted).toHaveLength(2))
    expect(submitted[1]).toEqual(submitted[0])
    expect(await screen.findByRole('link', { name: '打开候选数据集' })).toHaveAttribute(
      'href',
      '/evaluations/datasets/candidate-1/versions/1',
    )
  })
  it('manages evaluation sources independently and reads authoritative source identities', async () => {
    const calls: string[] = []
    renderApp('/evaluations/sources', (path) => {
      calls.push(path)
      if (path.endsWith('/auth/session')) return json(evaluatorSession)
      if (path.endsWith('/eval/documents')) return json({ items: [documentFixture], total: 1 })
      if (path.includes('/eval/documents/doc-1/source?'))
        return json({
          doc_id: 'doc-1',
          version_id: 'version-1',
          parse_artifact_id: 'parse-1',
          canonical_text_hash: 'canonical-hash',
          source_sha256: 'original-hash',
          block_id: 'block-1',
          excerpt: '集合中的元素具有互异性。',
          locator: { start_char: 0, end_char: 12, quote_hash: 'quote-hash' },
          blocks: [{ block_id: 'block-1', start_char: 0, end_char: 12 }],
        })
      return apiFailure(404)
    })
    await screen.findByRole('heading', { name: '评测资料' })
    await userEvent.click(await screen.findByRole('button', { name: '查看原文与来源标识' }))
    expect(await screen.findByText('集合中的元素具有互异性。')).toBeVisible()
    expect((screen.getByLabelText('可登记的来源 JSON') as HTMLTextAreaElement).value).toContain(
      'original-hash',
    )
    expect(calls.some((path) => path.includes('/knowledge/'))).toBe(false)
  })

  it('keeps unreviewed question rubric fields unknown when recording a human result review', async () => {
    let review: Record<string, unknown> | undefined
    const quizResult = {
      ...result,
      case_type: 'quiz',
      artifact: { questions: [{ id: 'q1', stem: '空集是什么？' }] },
    }
    renderApp('/evaluations/runs/run-1', (path, init) => {
      if (path.endsWith('/auth/session')) return json(evaluatorSession)
      if (path.endsWith('/review')) {
        review = JSON.parse(init.body as string)
        return json({})
      }
      if (path.endsWith('/results')) return json({ items: [quizResult], total: 1 })
      if (path.endsWith('/runs/run-1')) return json(run)
      return apiFailure(404)
    })
    await userEvent.selectOptions(await screen.findByLabelText('第 1 题 · 答案正确'), 'true')
    await userEvent.type(screen.getByLabelText('复核理由'), '仅核对了答案，其余语义项待复核。')
    await userEvent.click(screen.getByRole('button', { name: '保存复核' }))
    await waitFor(() =>
      expect(review).toMatchObject({
        question_reviews: [
          {
            question_id: 'q1',
            decisions: { answer_correctness: true, source_support: null, solvability: null },
          },
        ],
      }),
    )
  })
  it('requires explicit source, span, split, answerability and review acknowledgement before freeze', async () => {
    let payload: Record<string, unknown> | undefined
    renderApp('/evaluations/datasets/data-1/versions/1', (path, init) => {
      if (path.endsWith('/auth/session')) return json(evaluatorSession)
      if (path.endsWith('/freeze')) {
        payload = JSON.parse(init.body as string)
        return json(frozen)
      }
      return json({ ...frozen, status: 'draft' })
    })
    await screen.findByRole('heading', { name: '集合 smoke' })
    const freeze = screen.getByRole('button', { name: '验证并冻结' })
    expect(freeze).toBeDisabled()
    for (const name of [
      '来源授权与许可已核对',
      '原文范围与 hash 已核对',
      '文档家族与 split 已核对',
      '可回答性与请求题量已核对',
      '独立复核覆盖与限制已核对',
    ])
      await userEvent.click(screen.getByRole('checkbox', { name }))
    await userEvent.click(freeze)
    await waitFor(() =>
      expect(payload).toMatchObject({
        expected_revision: 3,
        checklist: {
          source_rights: true,
          spans: true,
          family_split: true,
          answerability: true,
          second_review: true,
        },
      }),
    )
  })
  it('records dataset review through the authenticated endpoint rather than a client-written review log', async () => {
    let payload: Record<string, unknown> | undefined
    let draft = { ...frozen, status: 'draft', revision: 1 }
    renderApp('/evaluations/datasets/data-1/versions/1', (path, init) => {
      if (path.endsWith('/auth/session')) return json(evaluatorSession)
      if (path.endsWith('/samples/sample-1/review')) {
        payload = JSON.parse(init.body as string)
        draft = { ...draft, revision: 2 }
        return json(draft)
      }
      if (path.endsWith('/versions/1')) return json(draft)
      return apiFailure(404)
    })
    await screen.findByRole('heading', { name: '集合 smoke' })
    await userEvent.type(screen.getByLabelText('标注复核理由'), '已核对原文、必要证据与预期答案。')
    await userEvent.click(screen.getByRole('button', { name: '记录人工确认' }))
    await waitFor(() =>
      expect(payload).toEqual({
        expected_revision: 1,
        verdict: 'approved',
        comment: '已核对原文、必要证据与预期答案。',
      }),
    )
  })
  it('creates a bounded run with a server-listed pipeline and scoring profile', async () => {
    let created: Record<string, unknown> | undefined
    let key: string | null = null
    renderApp('/evaluations/runs', (path, init) => {
      if (path.endsWith('/auth/session')) return json(adminSession)
      if (path.endsWith('/eval/datasets')) return json({ items: [frozen], total: 1 })
      if (path.endsWith('/eval/pipelines'))
        return json({
          items: [
            { pipeline_id: 'dense-v1', name: '纯检索基线', description: '固定配置', config: {} },
          ],
          total: 1,
        })
      if (path.endsWith('/eval/judges'))
        return json({
          items: [
            {
              judge_profile_id: 'deterministic-v1',
              name: '确定性指标',
              description: '不调用模型',
              calibrated: false,
            },
            {
              judge_profile_id: 'ragas-faithfulness-v1',
              name: 'Ragas 事实支持度',
              description: '由管理员配置，按实际调用计费',
              calibrated: false,
            },
          ],
          total: 2,
        })
      if (path.endsWith('/eval/runs') && init.method === 'POST') {
        created = JSON.parse(init.body as string)
        key = new Headers(init.headers).get('Idempotency-Key')
        return json(run, 202)
      }
      if (path.endsWith('/eval/runs')) return json({ items: [], total: 0 })
      if (path.endsWith('/results')) return json({ items: [result], total: 1 })
      if (path.endsWith('/runs/run-1')) return json(run)
      return apiFailure(404)
    })
    await screen.findByRole('heading', { name: '评测运行' })
    await userEvent.selectOptions(await screen.findByLabelText('数据集版本'), 'data-1:1')
    await userEvent.selectOptions(screen.getByLabelText('评测方案'), 'dense-v1')
    await userEvent.selectOptions(screen.getByLabelText('评分方案'), 'ragas-faithfulness-v1')
    await userEvent.click(screen.getByRole('button', { name: '创建运行' }))
    await waitFor(() =>
      expect(created).toEqual({
        dataset_id: 'data-1',
        dataset_version: 1,
        pipeline_id: 'dense-v1',
        judge_profile_id: 'ragas-faithfulness-v1',
        repeat_count: 1,
        max_cost_cny: 10,
      }),
    )
    expect(key).toBeTruthy()
    expect(await screen.findByRole('heading', { name: '运行详情' })).toBeVisible()
  })
  it('does not turn a completed run with an unknown judge score into an improvement claim', async () => {
    renderApp('/evaluations/runs/run-1', (path) => {
      if (path.endsWith('/auth/session')) return json(evaluatorSession)
      if (path.endsWith('/runs/run-1/results')) return json({ items: [result], total: 1 })
      if (path.endsWith('/runs/run-1')) return json(run)
      return apiFailure(404)
    })
    expect(await screen.findByTestId('faithfulness-value')).toHaveTextContent('—')
    expect(screen.getAllByText('评分待裁决').length).toBeGreaterThan(0)
    expect(screen.getByTestId('release-status')).not.toHaveTextContent('已证实改善')
  })

  it('removes cached private artifacts when a refresh reports revoked source authorization', async () => {
    let revoked = false
    renderApp('/evaluations/runs/run-1', (path) => {
      if (path.endsWith('/auth/session')) return json(evaluatorSession)
      if (path.endsWith('/results'))
        return revoked
          ? apiFailure(404)
          : json({
              items: [{ ...result, artifact: { evidence: [{ text: '仅供本人阅览的测试原文' }] } }],
              total: 1,
            })
      if (path.endsWith('/runs/run-1')) return json(run)
      return apiFailure(404)
    })
    await screen.findAllByText(/仅供本人阅览的测试原文/)
    revoked = true
    await userEvent.click(screen.getByRole('button', { name: '刷新' }))
    await screen.findByRole('alert')
    expect(screen.queryAllByText(/仅供本人阅览的测试原文/)).toHaveLength(0)
  })

  it('makes frozen versions read-only and creates a new version for edits', async () => {
    let created: Record<string, unknown> | undefined
    renderApp('/evaluations/datasets/data-1/versions/1', (path, init) => {
      if (path.endsWith('/auth/session')) return json(evaluatorSession)
      if (path.endsWith('/datasets') && init.method === 'POST') {
        created = JSON.parse(init.body as string)
        return json({ ...frozen, version: 2, status: 'draft' }, 201)
      }
      if (path.endsWith('/versions/2')) return json({ ...frozen, version: 2, status: 'draft' })
      if (path.endsWith('/versions/1')) return json(frozen)
      return apiFailure(404)
    })
    await screen.findByRole('heading', { name: '集合 smoke' })
    expect(screen.queryByRole('button', { name: '保存草稿' })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '创建新版本' }))
    await waitFor(() =>
      expect(created).toMatchObject({
        dataset_id: 'data-1',
        name: '集合 smoke',
        samples: frozen.samples,
      }),
    )
    expect(await screen.findByRole('button', { name: '保存草稿' })).toBeVisible()
  })

  it('persists a human review with its expected revision', async () => {
    let review: Record<string, unknown> | undefined
    renderApp('/evaluations/runs/run-1', (path, init) => {
      if (path.endsWith('/auth/session')) return json(evaluatorSession)
      if (path.endsWith('/review')) {
        review = JSON.parse(init.body as string)
        return json({ ...result, review, review_revision: 1 })
      }
      if (path.endsWith('/results'))
        return json({ items: [{ ...result, review, review_revision: review ? 1 : 0 }], total: 1 })
      if (path.endsWith('/runs/run-1')) return json(run)
      return apiFailure(404)
    })
    await screen.findByRole('heading', { name: '运行详情' })
    await userEvent.selectOptions(await screen.findByLabelText('人工判定'), 'uncertain')
    await userEvent.type(screen.getByLabelText('复核理由'), '评分器异常，需要补充证据后裁决。')
    await userEvent.click(screen.getByRole('button', { name: '保存复核' }))
    await waitFor(() =>
      expect(review).toEqual({
        expected_revision: 0,
        verdict: 'uncertain',
        comment: '评分器异常，需要补充证据后裁决。',
      }),
    )
    expect(await screen.findByText('人工复核已保存')).toBeVisible()
  })
})
