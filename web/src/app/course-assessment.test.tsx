import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { renderApp } from '../test/renderApp'
import { apiFailure, json, session } from '../test/fixtures'
import {
  courseApplicationAttemptFixture, courseApplicationFixture, courseAssessmentFixture,
  courseCriteriaFixture, courseFixture, courseLessonFixture, courseOutcomesFixture,
  courseProgressFixture,
} from '../test/courseFixtures'
import type {
  CourseApplicationAttemptView, CourseAssessmentView, CourseOutcomeSummary, CourseView,
} from '../types/course'

const coursePath = '/study/courses/course-1'
const withCriteria: CourseView = { ...courseFixture, course_criteria: courseCriteriaFixture }

type Options = {
  course?: CourseView
  outcomes?: CourseOutcomeSummary
  assessments?: CourseAssessmentView[]
  attempt?: CourseApplicationAttemptView | null
  writes?: string[]
}

function assessmentApi(path: string, init: RequestInit, options: Options = {}) {
  const { course = withCriteria, outcomes = courseOutcomesFixture, assessments = [] } = options
  if (init.method === 'POST' && path !== '/api/v1/experience/events') options.writes?.push(path)
  if (path.endsWith('/auth/session')) return json(session)
  if (path.endsWith('/auth/capabilities')) return json({})
  if (path === '/api/v1/experience/events') return json(null)
  if (path === '/api/v1/courses/course-1') return json(course)
  if (path === '/api/v1/courses/course-1/lessons/lesson-1') return json(courseLessonFixture)
  if (path.endsWith('/course-1/outcomes')) return json(outcomes)
  if (path.endsWith('/course-1/assessments')) return json(assessments)
  if (path.includes('/assessments/assessment-1/attempts/')) return json(options.attempt)
  if (path.includes('/assessments/assessment-1')) return json(assessments[0])
  if (path.endsWith('/course-1/progress')) return json(courseProgressFixture)
  if (path.endsWith('/course-1/reviews') || path.includes('/tutor-turns')) return json([])
  if (path.includes('/self-check-attempts')) return json([])
  return apiFailure(404)
}

afterEach(() => vi.unstubAllGlobals())

describe('course teaching quality notice', () => {
  it('does not claim a review for a fast course without a quality summary', async () => {
    renderApp(coursePath, (path, init) => assessmentApi(path, init))
    const notice = await screen.findByRole('region', { name: '课程纲要教学核对状态' })
    expect(within(notice).getByText('课程纲要尚未完成教学核对')).toBeVisible()
    expect(within(notice).queryByText(/已完成教学核对$/)).not.toBeInTheDocument()
    expect(within(notice).getByText('本次生成未请求教学核对。')).toBeVisible()
  })

  it('does not render a review that is not bound to the published artifact', async () => {
    const course: CourseView = {
      ...withCriteria,
      teaching_mode: 'guided',
      quality_summary: {
        level: 'outline', status: 'reviewed', draft_hash: 'draft-1',
        artifact_hash: null, reason_code: null, warnings: ['部分术语较集中，学习时可结合示例逐步核对。'],
      },
    }
    renderApp(coursePath, (path, init) => assessmentApi(path, init, { course }))
    const notice = await screen.findByRole('region', { name: '课程纲要教学核对状态' })
    expect(within(notice).getByText('课程纲要尚未完成教学核对')).toBeVisible()
    expect(within(notice).getByText(/原核对结果不适用于当前版本/)).toBeVisible()
    expect(within(notice).queryByText(/部分术语较集中/)).not.toBeInTheDocument()
    expect(notice.textContent).not.toContain('draft-1')
  })

  it('shows no role collaboration for a fast outline task that never entered a role stage', async () => {
    const course: CourseView = {
      ...withCriteria,
      status: 'generating',
      active_task: {
        task_id: 'outline-task-1', course_id: 'course-1', kind: 'course_outline',
        status: 'running', stage: 'generating', business_settled: false,
      },
    }
    renderApp(coursePath, (path, init) => assessmentApi(path, init, { course }))
    await screen.findByRole('region', { name: '课程纲要生成状态' })
    expect(screen.queryByRole('region', { name: '教学协作阶段' })).not.toBeInTheDocument()
    expect(screen.queryByText('教学检查')).not.toBeInTheDocument()
  })

  it('shows only the observed stages of a guided task and marks later work as not done', async () => {
    const course: CourseView = {
      ...withCriteria,
      status: 'generating',
      teaching_mode: 'guided',
      active_task: {
        task_id: 'outline-task-1', course_id: 'course-1', kind: 'course_outline',
        status: 'running', stage: 'reviewing', business_settled: false,
      },
    }
    renderApp(coursePath, (path, init) => assessmentApi(path, init, { course }))
    const progress = await screen.findByRole('region', { name: '教学协作阶段' })
    const step = (label: string) =>
      within(progress).getByText(label).closest('.course-agent-step')
    expect(step('课程设计')).toHaveClass('done')
    expect(step('教学检查')).toHaveClass('active')
    expect(step('根据反馈修订')).toHaveClass('conditional')
    expect(within(progress).getByText('如有需要才进行')).toBeVisible()
    expect(progress.textContent).not.toMatch(/\d+%/)
  })

  it('reports a bound review without promising correctness or mastery', async () => {
    const course: CourseView = {
      ...withCriteria,
      teaching_mode: 'guided',
      quality_summary: {
        level: 'outline', status: 'reviewed', draft_hash: 'draft-1',
        artifact_hash: 'artifact-1', reason_code: null, warnings: [],
      },
    }
    renderApp(coursePath, (path, init) => assessmentApi(path, init, { course }))
    const notice = await screen.findByRole('region', { name: '课程纲要教学核对状态' })
    expect(within(notice).getByText('课程纲要已完成教学核对')).toBeVisible()
    expect(within(notice).getByText(/不代表课程完全正确，也不代表你已掌握/)).toBeVisible()
  })
})

describe('course completion check and goal evidence', () => {
  it('keeps uncovered goals visible and never shows a provisional result as verified', async () => {
    renderApp(coursePath, (path, init) =>
      assessmentApi(path, init, { assessments: [courseAssessmentFixture] }))
    const panel = await screen.findByRole('region', { name: '结业检查与课程目标' })
    expect(await within(panel).findByText('已验证 0 / 2')).toBeVisible()
    const uncovered = within(panel).getByRole('region', { name: '本次检查未覆盖的目标' })
    expect(within(uncovered).getByRole('heading', { name: '本次检查未覆盖的目标（1）' })).toBeVisible()
    expect(within(uncovered).getByText(courseCriteriaFixture[1].description)).toBeVisible()
    // 每个目标都只显示服务端投影给出的状态；一次已结算的识别题不升级为已验证。
    const statuses = panel.querySelectorAll('.course-goal-status')
    expect(statuses.length).toBeGreaterThan(0)
    expect([...statuses].every((node) => node.textContent === '待验证')).toBe(true)
    expect(within(panel).getByText(/帮助使用情况未知或存在提示/)).toBeVisible()
    expect(within(panel).getByText('本次检查已覆盖')).toBeVisible()
  })

  it('describes a sealed check as a finished flow, not a verified course', async () => {
    const sealed: CourseAssessmentView = { ...courseAssessmentFixture, status: 'completed' }
    renderApp(coursePath, (path, init) => assessmentApi(path, init, { assessments: [sealed] }))
    const panel = await screen.findByRole('region', { name: '结业检查与课程目标' })
    expect(await within(panel).findByText('流程已封存')).toBeVisible()
    expect(within(panel).getByText(/这只表示这一组检查已封存，不代表全部目标已验证/)).toBeVisible()
    expect(within(panel).queryByRole('button', { name: /封存本次检查/ })).not.toBeInTheDocument()
  })

  it('reads goal results without creating any task', async () => {
    const writes: string[] = []
    renderApp(coursePath, (path, init) =>
      assessmentApi(path, init, { assessments: [courseAssessmentFixture], writes }))
    await screen.findByRole('region', { name: '结业检查与课程目标' })
    await waitFor(() => expect(screen.getByText('已验证 0 / 2')).toBeVisible())
    expect(writes).toEqual([])
  })
})

describe('course text application task', () => {
  const withApplication: CourseAssessmentView = {
    ...courseAssessmentFixture,
    application_task_ids: ['application-1'],
    applications: (courseApplicationFixture || []).map((task) => ({
      ...task, latest_attempt_id: 'application-attempt-1',
    })),
  }

  it('keeps a saved answer and offers a retry after the feedback queue failed', async () => {
    renderApp(coursePath, (path, init) =>
      assessmentApi(path, init, {
        assessments: [withApplication], attempt: courseApplicationAttemptFixture,
      }))
    const panel = await screen.findByRole('region', { name: '结业检查与课程目标' })
    const answer = await within(panel).findByRole('textbox', { name: '你的回答' })
    expect(answer).toHaveValue(courseApplicationAttemptFixture.answer)
    expect(within(panel).getByText(/反馈还没有排队成功，可以重试反馈/)).toBeVisible()
    expect(within(panel).getByRole('button', { name: '重试这次反馈' })).toBeVisible()
    // 没有任何反馈时不得出现评分徽标。
    expect(within(panel).queryByText('已确认评分')).not.toBeInTheDocument()
    expect(within(panel).queryByText('暂定，未正式确认')).not.toBeInTheDocument()
  })

  it('keeps the saved answer after an explicit feedback retry fails', async () => {
    renderApp(coursePath, (path, init) => {
      if (path.includes('/attempts/application-attempt-1/feedback-jobs'))
        return apiFailure(503, '反馈服务暂不可用')
      return assessmentApi(path, init, {
        assessments: [withApplication], attempt: courseApplicationAttemptFixture,
      })
    })
    const panel = await screen.findByRole('region', { name: '结业检查与课程目标' })
    const answer = await within(panel).findByRole('textbox', { name: '你的回答' })
    await userEvent.click(within(panel).getByRole('button', { name: '重试这次反馈' }))
    await waitFor(() =>
      expect(within(panel).getByText(/提交结果尚未确认|反馈服务暂不可用/)).toBeVisible())
    expect(answer).toHaveValue(courseApplicationAttemptFixture.answer)
    expect(within(panel).getByText(/回答已保存于/)).toBeVisible()
  })

  it('separates provisional model feedback from a confirmed grade', async () => {
    const attempt: CourseApplicationAttemptView = {
      ...courseApplicationAttemptFixture,
      feedback: {
        assessment_id: 'grade-1', status: 'graded', confirmation: 'provisional',
        created_at: '2026-09-13T02:20:00Z', feedback: '分组对象说明清楚，可以再说明筛选位置。',
        criterion_results: [{ criterion_id: 'r1', credit: 'half', feedback: '需要补充筛选条件的位置。' }],
      },
    }
    renderApp(coursePath, (path, init) =>
      assessmentApi(path, init, { assessments: [withApplication], attempt }))
    const panel = await screen.findByRole('region', { name: '结业检查与课程目标' })
    expect(await within(panel).findByText('暂定，未正式确认')).toBeVisible()
    expect(within(panel).getByText(/等待人工复核，不作为目标已验证的依据/)).toBeVisible()
    expect(within(panel).getByText('部分符合')).toBeVisible()
    expect(within(panel).queryByText('已确认评分')).not.toBeInTheDocument()
    // 模型暂定反馈不改变任何目标的验证状态。
    expect(
      [...panel.querySelectorAll('.course-goal-status')].every((node) => node.textContent === '待验证'),
    ).toBe(true)
  })

  it('caps the answer length at the contract limit', async () => {
    renderApp(coursePath, (path, init) =>
      assessmentApi(path, init, { assessments: [withApplication], attempt: courseApplicationAttemptFixture }))
    const panel = await screen.findByRole('region', { name: '结业检查与课程目标' })
    const answer = await within(panel).findByRole('textbox', { name: '你的回答' })
    expect(answer).toHaveAttribute('maxLength', '4000')
  })

  it('submits a saved answer with an explicit learner help declaration', async () => {
    const writes: { path: string; body: unknown }[] = []
    const task = (courseApplicationFixture || [])[0]
    const assessment: CourseAssessmentView = {
      ...courseAssessmentFixture, application_task_ids: ['application-1'],
      applications: [{ ...task, latest_attempt_id: null }],
    }
    renderApp(coursePath, (path, init) => {
      if (init.method === 'POST' && path !== '/api/v1/experience/events')
        writes.push({ path, body: init.body ? JSON.parse(String(init.body)) : null })
      if (path.includes('/applications/application-1/attempts'))
        return json({ ...courseApplicationAttemptFixture, answer: '按客户分组后统计已支付订单。' })
      return assessmentApi(path, init, { assessments: [assessment] })
    })
    const panel = await screen.findByRole('region', { name: '结业检查与课程目标' })
    const tasks = await within(panel).findByRole('region', { name: '文本应用任务' })
    const answer = await within(tasks).findByRole('textbox', { name: '你的回答' })
    await userEvent.type(answer, '按客户分组后统计已支付订单。')
    await userEvent.click(within(tasks).getByRole('radio', { name: '没有使用提示或帮助' }))
    await userEvent.click(within(tasks).getByRole('button', { name: '提交回答' }))
    await waitFor(() => expect(writes).toHaveLength(1))
    expect(writes[0].body).toEqual({
      expected_revision: 1, answer: '按客户分组后统计已支付订单。', help_usage: 'none',
    })
  })

  it('recovers a lost answer receipt through the assessment without another POST', async () => {
    const task = courseApplicationFixture![0]
    let assessment: CourseAssessmentView = {
      ...courseAssessmentFixture, applications: [{ ...task, latest_attempt_id: null }],
    }
    let saved: CourseApplicationAttemptView | null = null
    let writes = 0
    const reads: string[] = []
    renderApp(coursePath, (path, init) => {
      if (init.method === 'POST' && path.includes('/applications/application-1/attempts')) {
        writes += 1
        const body = JSON.parse(String(init.body))
        saved = { ...courseApplicationAttemptFixture, answer: body.answer, help_usage: body.help_usage }
        assessment = { ...assessment, applications: [{ ...task, latest_attempt_id: saved.attempt_id }] }
        throw new TypeError('response lost after save')
      }
      if (!init.method || init.method === 'GET') reads.push(path)
      return assessmentApi(path, init, { assessments: [assessment], attempt: saved })
    })
    const panel = await screen.findByRole('region', { name: '结业检查与课程目标' })
    const answer = await within(panel).findByRole('textbox', { name: '你的回答' })
    await userEvent.type(answer, '先过滤已支付订单，再汇总金额。')
    await userEvent.click(within(panel).getByRole('button', { name: '提交回答' }))
    const recover = within(panel).queryByRole('button', { name: '核对已保存的回答' })
    if (recover) await userEvent.click(recover)
    await waitFor(() => expect(within(panel).getByText(/回答已保存于/)).toBeVisible())
    expect(answer).toHaveValue('先过滤已支付订单，再汇总金额。')
    expect(writes).toBe(1)
    expect(reads.some((path) => path.endsWith('/attempts/application-attempt-1'))).toBe(true)
    expect(reads.some((path) => path.endsWith('/attempts/'))).toBe(false)
  })

  it('locks an unconfirmed answer and explicitly replays its original request', async () => {
    const task = courseApplicationFixture![0]
    let assessment: CourseAssessmentView = {
      ...courseAssessmentFixture, applications: [{ ...task, latest_attempt_id: null }],
    }
    let saved: CourseApplicationAttemptView | null = null
    const writes: { key: string | null; body: string }[] = []
    renderApp(coursePath, (path, init) => {
      if (init.method === 'POST' && path.includes('/applications/application-1/attempts')) {
        writes.push({ key: new Headers(init.headers).get('Idempotency-Key'), body: String(init.body) })
        if (writes.length === 1) throw new TypeError('connection lost before receipt')
        const body = JSON.parse(String(init.body))
        saved = { ...courseApplicationAttemptFixture, answer: body.answer, help_usage: body.help_usage }
        assessment = { ...assessment, applications: [{ ...task, latest_attempt_id: saved.attempt_id }] }
        return json(saved)
      }
      return assessmentApi(path, init, { assessments: [assessment], attempt: saved })
    })
    const panel = await screen.findByRole('region', { name: '结业检查与课程目标' })
    const answer = await within(panel).findByRole('textbox', { name: '你的回答' })
    await userEvent.type(answer, '先过滤已支付订单，再汇总金额。')
    await userEvent.click(within(panel).getByRole('button', { name: '提交回答' }))
    await waitFor(() => expect(answer).toBeDisabled())
    await userEvent.click(within(panel).getByRole('button', { name: '核对已保存的回答' }))
    await userEvent.click(await within(panel).findByRole('button', { name: '重试原提交' }))
    await waitFor(() => expect(writes).toHaveLength(2))
    expect(writes[1]).toEqual(writes[0])
    await waitFor(() => expect(within(panel).getByText(/回答已保存于/)).toBeVisible())
  })

  it('hides a previously visible application when its receipt authorization is revoked', async () => {
    let revoked = false
    renderApp(coursePath, (path, init) => {
      if (revoked && path.includes('/attempts/application-attempt-1')) return apiFailure(403)
      return assessmentApi(path, init, {
        assessments: [withApplication], attempt: {
          ...courseApplicationAttemptFixture, feedback_task_id: 'feedback-1',
          feedback_task: { task_id: 'feedback-1', status: 'completed', stage: 'completed', business_settled: true },
        },
      })
    })
    const panel = await screen.findByRole('region', { name: '结业检查与课程目标' })
    await within(panel).findByDisplayValue(courseApplicationAttemptFixture.answer)
    revoked = true
    await userEvent.click(within(panel).getByRole('button', { name: '刷新反馈状态' }))
    await screen.findByRole('heading', { name: '课程资料已失效' })
    expect(screen.queryByText(courseApplicationFixture![0].prompt)).not.toBeInTheDocument()
    expect(screen.queryByDisplayValue(courseApplicationAttemptFixture.answer)).not.toBeInTheDocument()
  })
})

it('uses a new request key for an explicitly started next assessment group', async () => {
  let assessments: CourseAssessmentView[] = []
  const keys: (string | null)[] = []
  renderApp(coursePath, (path, init) => {
    if (init.method === 'POST' && path.endsWith('/assessment-jobs')) {
      keys.push(new Headers(init.headers).get('Idempotency-Key'))
      const created: CourseAssessmentView = {
        ...courseAssessmentFixture, course_assessment_id: `assessment-${keys.length}`,
        status: 'failed', quiz_id: null, quiz_settled: false,
        task: { task_id: `task-${keys.length}`, status: 'failed', stage: 'failed', business_settled: true },
      }
      assessments = [created, ...assessments]
      return json(created)
    }
    if (path.startsWith('/api/v1/courses/course-1/assessments/'))
      return json(assessments.find((item) => path.endsWith(item.course_assessment_id)))
    return assessmentApi(path, init, { assessments })
  })
  const panel = await screen.findByRole('region', { name: '结业检查与课程目标' })
  const start = within(panel).getByRole('button', { name: '开始结业检查' })
  await waitFor(() => expect(start).toBeEnabled())
  await userEvent.click(start)
  await userEvent.click(await within(panel).findByRole('button', { name: '开始下一组检查' }))
  await waitFor(() => expect(keys).toHaveLength(2))
  expect(keys[0]).toBeTruthy()
  expect(keys[1]).not.toBe(keys[0])
})
