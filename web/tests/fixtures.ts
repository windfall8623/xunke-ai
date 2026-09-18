import type { Page } from '@playwright/test'
import { documentFixture, learner, questions, quiz } from '../src/test/fixtures'

type ObjectData = Record<string, unknown>
export async function installTestApi(
  page: Page,
  options: { guest?: boolean; evaluator?: boolean; admin?: boolean; longName?: boolean } = {},
) {
  const baseDataset = {
    dataset_id: 'data-1',
    version: 1,
    name: '集合检索 smoke',
    status: 'frozen',
    revision: 3,
    checksum: 'fixture-sha256',
    manifest: {
      state: 'frozen',
      authorization: 'synthetic',
      sample_count: 1,
      review: { provisional: true },
      sources: [],
    },
    samples: [
      {
        sample_id: 'sample-1',
        case_type: 'retrieval',
        query: '空集是什么？',
        split: 'dev',
        family_ids: ['family-1'],
        source_refs: [] as ObjectData[],
        gold_evidence_groups: [] as ObjectData[],
        annotation: { review_records: [] },
      },
    ],
  }
  const baseRun = {
    run_id: 'run-1',
    status: 'completed',
    stop_reason: null as string | null,
    progress: { total: 1, completed: 1, failed: 0, pending: 0, scoring: 0 },
    comparison_eligible: false,
    manifest: {
      dataset_id: 'data-1',
      dataset_version: 1,
      pipeline_id: 'dense-v1',
      repeat_count: 1,
      max_cost_cny: 10,
      actual_cost_cny: 0.01,
    },
    created_at: '2026-09-07T10:00:00Z',
  }
  const result = {
    result_id: 'result-1',
    sample_id: 'sample-1',
    repeat_index: 0,
    case_type: 'retrieval',
    status: 'completed',
    sample: baseDataset.samples[0],
    artifact: {
      candidates: [{ title: '离散数学', excerpt: '空集是任意集合的子集。' }],
      final_context: [{ excerpt: '空集是任意集合的子集。' }],
      usage: { context_tokens: 20 },
    } as ObjectData,
    metrics: {
      faithfulness: {
        status: 'error',
        value: null,
        unit: 'ratio',
        unknown_count: 1,
        reason: 'judge_unavailable',
      },
      context_tokens: { status: 'ok', value: 20, unit: 'tokens', unknown_count: 0 },
    },
    review: null as ObjectData | null,
    review_revision: 0,
    error_code: null,
  }
  const state = {
    authenticated: !options.guest,
    user: {
      ...learner,
      role: options.admin ? 'admin' : options.evaluator ? 'evaluator' : 'learner',
      nickname: options.longName
        ? '一个保持好奇心并持续学习的很长很长昵称'.repeat(3)
        : learner.nickname,
    },
    answers: [] as ObjectData[],
    revision: 0,
    settled: false,
    completeRequests: 0,
    answerRequests: 0,
    documents: [{ ...documentFixture }],
    evalDocuments: [{ ...documentFixture, doc_id: 'eval-doc-1', file_name: '评测教材.txt' }],
    imagesStatus: 'not_requested',
    quizReads: 0,
    generationRequests: [] as ObjectData[],
    feedback: [] as ObjectData[],
    mutationHeaders: [] as Record<string, string>[],
    taskStatus: 'completed',
    datasets: [baseDataset] as Array<typeof baseDataset>,
    runs: [
      baseRun,
      { ...baseRun, run_id: 'run-2', manifest: { ...baseRun.manifest, pipeline_id: 'hybrid-v1' } },
    ],
    result,
    datasetReviews: [] as ObjectData[],
  }
  await page.route('**/*', async (route) => {
    const url = new URL(route.request().url())
    if (url.hostname !== '127.0.0.1' || url.port !== '4173') return route.abort('blockedbyclient')
    return route.continue()
  })
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname.replace('/api/v1', '')
    const method = request.method()
    const data = request.headers()['content-type']?.includes('application/json')
      ? (request.postDataJSON() as ObjectData)
      : {}
    const respond = (payload: unknown, status = 200) =>
      route.fulfill({
        status,
        contentType: 'application/json',
        body: JSON.stringify({ code: 0, message: 'ok', data: payload }),
      })
    const fail = (status: number, message: string) =>
      route.fulfill({
        status,
        contentType: 'application/json',
        body: JSON.stringify({
          code: status * 10,
          error_code: status === 401 ? 'AUTH_REQUIRED' : 'UNAVAILABLE',
          message,
          data: null,
        }),
      })
    const session = () => ({ user: state.user, csrf_token: 'browser-csrf' })
    if (path === '/auth/capabilities')
      return respond({ legacy_link_enabled: false, email_registration_enabled: true })
    if (path === '/auth/email-code')
      return respond({ message: '验证码已发送', retry_after_seconds: 60, expires_in_seconds: 600 })
    if (path === '/auth/session')
      return state.authenticated ? respond(session()) : fail(401, '登录已失效')
    if (path === '/auth/login') {
      state.authenticated = true
      return respond(session())
    }
    if (path === '/auth/register') {
      state.authenticated = true
      state.user.nickname = String(data.nickname)
      return respond({ ...session(), recovery_code: 'TEST-RECOVERY-ONLY-ONCE' }, 201)
    }
    if (path === '/auth/recover') {
      state.authenticated = false
      return respond({})
    }
    if (!state.authenticated) return fail(401, '登录已失效')
    if (method !== 'GET') state.mutationHeaders.push(request.headers())
    if (path === '/auth/logout' || path === '/auth/change-password') {
      state.authenticated = false
      return respond(null)
    }
    if (path === '/user/profile') {
      if (method === 'PUT') state.user.nickname = String(data.nickname)
      return respond({
        ...state.user,
        quiz_count: state.settled ? 1 : 0,
        correct_count: state.answers.filter((answer) => answer.is_correct).length,
        average_accuracy: state.settled ? 100 : 0,
      })
    }
    if (path === '/user/avatar') return respond({ avatar_url: '' })
    if (path === '/knowledge/documents') {
      if (method === 'POST') {
        const fileName =
          /filename="([^"]+)"/.exec(request.postDataBuffer()?.toString('utf8') || '')?.[1] ||
          '新资料.txt'
        const doc = {
          ...documentFixture,
          doc_id: 'doc-2',
          file_name: fileName,
          status: 'processing',
        }
        state.documents.push(doc)
        return respond(doc, 202)
      }
      return respond({ items: state.documents, total: state.documents.length })
    }
    const docMatch = path.match(/^\/knowledge\/documents\/([^/]+)(?:\/(versions|reindex|source))?$/)
    if (docMatch) {
      const doc = state.documents.find((item) => item.doc_id === decodeURIComponent(docMatch[1]))
      if (!doc) return fail(404, '来源不可用')
      if (method === 'DELETE') {
        state.documents = state.documents.filter((item) => item !== doc)
        return respond(null)
      }
      if (docMatch[2] === 'source')
        return respond({
          doc_id: doc.doc_id,
          version_id: 'version-1',
          parse_artifact_id: 'parse-1',
          canonical_text_hash: 'canon-hash',
          block_id: url.searchParams.get('block_id'),
          excerpt: '集合的元素具有互异性。',
          locator: {
            page: 2,
            start_char: Number(url.searchParams.get('start_char')),
            end_char: Number(url.searchParams.get('end_char')),
            quote_hash: 'quote-hash',
          },
        })
      if (method === 'POST') doc.status = 'processing'
      return respond(doc)
    }
    if (path === '/quiz/generate/async') {
      state.generationRequests.push(data)
      return respond({ task_id: 'task-1' }, 202)
    }
    if (path === '/quiz/task/task-1')
      return respond({
        task_id: 'task-1',
        status: state.taskStatus,
        stage: state.taskStatus === 'completed' ? 'completed' : 'retrieving',
        quiz_id: state.taskStatus === 'completed' ? 'quiz-1' : null,
      })
    if (path === '/user/quizzes')
      return respond({
        items: [
          {
            quiz_id: 'quiz-1',
            title: quiz.title,
            question_count: 3,
            answered_count: state.answers.length,
            status: state.settled ? 'settled' : 'in_progress',
            report_status: state.settled ? 'failed' : 'not_started',
            accuracy: state.settled ? 100 : null,
            created_at: '2026-09-07T10:00:00Z',
          },
        ],
        total: 1,
        page: 1,
        page_size: 10,
      })
    if (path === '/user/quizzes/quiz-1') {
      state.quizReads++
      return respond({
        ...quiz,
        questions,
        answer_records: state.answers,
        answered_count: state.answers.length,
        revision: state.revision,
        status: state.settled ? 'settled' : 'in_progress',
        images_status: state.imagesStatus,
      })
    }
    const answerMatch = path.match(/^\/quiz\/quiz-1\/answers\/(q[123])$/)
    if (answerMatch) {
      state.answerRequests++
      const questionId = answerMatch[1]
      let record = state.answers.find((answer) => answer.question_id === questionId)
      if (!record) {
        const correct = questionId === 'q3' ? ['A', 'B'] : ['A']
        const selected = data.selected_answers as string[]
        record = {
          ...data,
          question_id: questionId,
          is_correct: JSON.stringify(selected) === JSON.stringify(correct),
          correct_answers: correct,
          explanation: '依据原文，集合的定义与运算必须满足这些条件。',
          citation_refs: ['e1'],
        }
        state.answers.push(record)
        state.revision++
      }
      return respond({
        answer_record: record,
        revision: state.revision,
        answered_count: state.answers.length,
        correct_count: state.answers.filter((answer) => answer.is_correct).length,
      })
    }
    if (path === '/quiz/quiz-1/complete') {
      state.completeRequests++
      state.settled = true
      return respond({
        quiz_id: 'quiz-1',
        revision: state.revision,
        xp_awarded: 16,
        total_questions: 3,
        correct_count: 3,
        accuracy: 100,
        report_status: 'failed',
      })
    }
    if (path === '/report/quiz-1' || path === '/report/quiz-1/retry')
      return respond({
        quiz_id: 'quiz-1',
        total_questions: 3,
        correct_count: 3,
        accuracy: 100,
        xp_awarded: 16,
        report_status: 'failed',
        report: null,
      })
    if (path.startsWith('/quiz/quiz-1/evidence/'))
      return state.documents.some((doc) => doc.doc_id === 'doc-1')
        ? respond({
            evidence_id: path.split('/').at(-1),
            title: documentFixture.file_name,
            status: 'available',
            source_type: 'document',
            excerpt: '集合中的元素具有互异性。<script>window.evidenceExecuted=true</script>',
            locator: {
              page: 2,
              start_char: 0,
              end_char: 12,
              block_id: 'block-1',
              quote_hash: 'quote',
            },
          })
        : fail(404, '来源已删除')
    if (path === '/quiz/quiz-1/feedback') {
      state.feedback.push(data)
      return respond({ feedback_id: 'feedback-1' })
    }
    if (path.startsWith('/eval/') && !options.evaluator) return fail(403, '需要评测权限')
    if (path === '/eval/documents') {
      if (method === 'POST') {
        const fileName =
          /filename="([^"]+)"/.exec(request.postDataBuffer()?.toString('utf8') || '')?.[1] ||
          '新评测资料.txt'
        const document = {
          ...documentFixture,
          doc_id: 'eval-doc-2',
          file_name: fileName,
          status: 'processing',
        }
        state.evalDocuments.push(document)
        return respond(document, 202)
      }
      return respond({ items: state.evalDocuments, total: state.evalDocuments.length })
    }
    const evalDocMatch = path.match(/^\/eval\/documents\/([^/]+)(?:\/(reindex|source))?$/)
    if (evalDocMatch) {
      const document = state.evalDocuments.find((item) => item.doc_id === evalDocMatch[1])
      if (!document) return fail(404, '来源不可用')
      if (method === 'DELETE') {
        state.evalDocuments = state.evalDocuments.filter((item) => item !== document)
        return respond({})
      }
      if (evalDocMatch[2] === 'source')
        return respond({
          doc_id: document.doc_id,
          version_id: 'version-1',
          parse_artifact_id: 'parse-1',
          source_sha256: 'original-hash',
          canonical_text_hash: 'canonical-hash',
          block_id: 'block-1',
          excerpt: '集合的元素具有互异性。',
          locator: { start_char: 0, end_char: 12, quote_hash: 'quote-hash' },
          blocks: [{ block_id: 'block-1', start_char: 0, end_char: 12 }],
        })
      if (method === 'POST') document.status = 'processing'
      return respond(document)
    }
    if (path === '/eval/datasets') {
      if (method === 'POST') {
        const dataset = {
          ...baseDataset,
          dataset_id: String(data.dataset_id || 'data-2'),
          version: data.dataset_id ? 2 : 1,
          name: String(data.name),
          status: 'draft',
          revision: 1,
          checksum: '',
          manifest: data.manifest as typeof baseDataset.manifest,
          samples: data.samples as typeof baseDataset.samples,
        }
        state.datasets.push(dataset)
        return respond(dataset, 201)
      }
      return respond({ items: state.datasets, total: state.datasets.length })
    }
    const datasetMatch = path.match(/^\/eval\/datasets\/([^/]+)\/versions\/(\d+)(.*)$/)
    if (datasetMatch) {
      const item = state.datasets.find(
        (item) => item.dataset_id === datasetMatch[1] && item.version === Number(datasetMatch[2]),
      )
      if (!item) return fail(404, '版本不可用')
      if (datasetMatch[3].endsWith('/review')) {
        state.datasetReviews.push(data)
        item.revision++
        return respond(item)
      }
      if (datasetMatch[3] === '/freeze') {
        item.status = 'frozen'
        item.revision++
        item.checksum = 'frozen-checksum'
        return respond(item)
      }
      if (method === 'PATCH') {
        Object.assign(item, data)
        item.revision++
        return respond(item)
      }
      return respond(item)
    }
    if (path === '/eval/judges')
      return respond({
        items: [
          {
            judge_profile_id: 'deterministic-v1',
            name: '确定性指标',
            description: '不调用自动评分模型',
            calibrated: false,
          },
        ],
        total: 1,
      })
    if (path === '/eval/pipelines')
      return respond({
        items: [
          {
            pipeline_id: 'dense-v1',
            name: '纯检索基线',
            description: '固定检索配置',
            index_profile_id: 'legacy-char-v1',
            config: {},
          },
        ],
        total: 1,
      })
    if (path === '/eval/runs/estimate' && method === 'GET') {
      const dataset = state.datasets.find(
        (item) =>
          item.dataset_id === url.searchParams.get('dataset_id') &&
          item.version === Number(url.searchParams.get('dataset_version')),
      )
      if (!dataset) return fail(404, '版本不可用')
      const repeats = Number(url.searchParams.get('repeat_count') ?? 1)
      const planned = dataset.samples.length * repeats
      // Synthetic browser fixture only: no provider calls or real price discovery.
      return respond({
        status: 'estimated',
        method: 'configured_price_scenarios_v1',
        currency: 'CNY',
        not_a_bill: true,
        pricing_version: 'browser-fixture-only',
        sample_count: dataset.samples.length,
        repeat_count: repeats,
        planned_executions: planned,
        first_attempt_cny: 0.001 * planned,
        retry_scenario_cny: 0.002 * planned,
        components: [
          {
            stage: 'retrieval',
            status: 'estimated',
            first_attempt_cny: 0.001 * planned,
            retry_scenario_cny: 0.002 * planned,
            first_attempt_calls: planned,
            retry_scenario_calls: 2 * planned,
            first_attempt_input_tokens: 1000 * planned,
            first_attempt_output_tokens: 0,
            retry_scenario_input_tokens: 2000 * planned,
            retry_scenario_output_tokens: 0,
            prices: { embedding_cny_per_million: 1 },
            missing_prices: [],
            assumptions: ['浏览器测试假设每次向量查询 1000 token，单价 ¥ 1 / 百万 token。'],
          },
          ...(['generation', 'scoring', 'indexing'] as const).map((stage) => ({
            stage,
            status: 'not_applicable',
            first_attempt_cny: null,
            retry_scenario_cny: null,
            prices: {},
            missing_prices: [],
            assumptions: [],
            reason: '此浏览器测试情景不适用。',
          })),
        ],
        assumptions: ['仅供浏览器测试的假价格和用量，不调用模型服务，也不创建运行或预留费用。'],
      })
    }
    if (path === '/eval/runs') {
      if (method === 'POST') {
        const run = {
          ...baseRun,
          run_id: 'run-3',
          status: 'queued',
          progress: { total: 1, completed: 0, failed: 0, pending: 1, scoring: 0 },
          manifest: { ...baseRun.manifest, ...data },
        }
        state.runs.push(run)
        return respond(run, 202)
      }
      return respond({ items: state.runs, total: state.runs.length })
    }
    const runMatch = path.match(/^\/eval\/runs\/([^/]+)(.*)$/)
    if (runMatch) {
      const run = state.runs.find((run) => run.run_id === runMatch[1])
      if (!run) return fail(404, '运行不可用')
      if (runMatch[2] === '/results') return respond({ items: [state.result], total: 1 })
      if (runMatch[2].endsWith('/review')) {
        state.result.review = data
        state.result.review_revision++
        return respond(state.result)
      }
      if (runMatch[2] === '/cancel') {
        run.status = 'cancelled'
        return respond(run)
      }
      if (runMatch[2] === '/resume') {
        run.status = 'queued'
        return respond(run)
      }
      if (runMatch[2] === '/export')
        return route.fulfill({
          status: 200,
          contentType: 'text/plain',
          headers: { 'Content-Disposition': 'attachment; filename="evaluation.jsonl"' },
          body: JSON.stringify(state.result),
        })
      return respond(run)
    }
    if (path === '/eval/compare')
      return respond({
        comparison_eligible: false,
        exploratory: true,
        reason: '样本量较小，且评分尚待人工裁决。',
        baseline_run_id: 'run-1',
        candidate_run_id: 'run-2',
        sample_count: 1,
        cluster_count: 1,
        group: url.searchParams.get('group') || 'all',
        metrics: {
          evidence_group_recall: {
            baseline: { value: 0.8, status: 'ok', unit: 'ratio' },
            candidate: { value: 0.85, status: 'ok', unit: 'ratio' },
            delta: 0.05,
            confidence_interval: [-0.02, 0.12],
            unit: 'ratio',
            sample_count: 1,
            status: 'provisional',
          },
          faithfulness: {
            baseline: { value: null, status: 'error', unit: 'ratio' },
            candidate: { value: null, status: 'error', unit: 'ratio' },
            delta: null,
            confidence_interval: null,
            unit: 'ratio',
            sample_count: 0,
            status: 'unknown',
          },
        },
      })
    return fail(404, `测试 API 未定义：${method} ${path}`)
  })
  return state
}
