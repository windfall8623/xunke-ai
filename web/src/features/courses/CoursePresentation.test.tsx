import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { coursesApi } from '../../services/courses'
import type { CourseLessonSummary, CourseLessonView, CourseView } from '../../types/course'
import { CourseCover, CourseReadingProgress, courseReadingProgress } from './CourseCover'
import { CourseListSection } from './CourseListSection'
import { CourseTodayCard } from './CourseTodayCard'
import { CourseLesson } from './CourseLesson'

vi.mock('../../app/AuthProvider', () => ({
  useAuth: () => ({ status: 'authenticated' }),
  useIdentityKey: () => 'presentation-test',
}))
vi.mock('./useLessonTutor', () => ({
  useLessonTutor: () => ({ query: { isPending: false }, busy: false }),
}))

const lesson: CourseLessonSummary = {
  lesson_id: 'lesson-1',
  title: '理解函数',
  unit_ref: 'unit-1',
  position: 1,
  availability: 'ready',
  status: 'ready',
  content_version: 1,
  revision: 1,
}
const course: CourseView = {
  course_id: 'course-stable',
  title: 'Python 函数入门',
  source_policy: 'topic',
  source_status: 'active',
  status: 'ready',
  outline_editable: false,
  revision: 1,
  created_at: '2026-09-16T10:00:00Z',
  updated_at: '2026-09-16T10:00:00Z',
  resume_lesson_id: 'lesson-1',
  lessons: [lesson],
}
function mount(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{node}</MemoryRouter>
    </QueryClientProvider>,
  )
}
afterEach(() => vi.restoreAllMocks())

describe('bound course presentation', () => {
  it('keeps the binding stable when title or status changes, with a real navigation link', () => {
    const { rerender } = render(
      <MemoryRouter>
        <CourseCover course={course} to="/study/courses/course-stable?lesson=lesson-1" />
      </MemoryRouter>,
    )
    const cover = screen.getByRole('link', { name: /Python 函数入门/ })
    const binding = cover.className
    expect(cover).toHaveAttribute('href', '/study/courses/course-stable?lesson=lesson-1')
    rerender(
      <MemoryRouter>
        <CourseCover
          course={{ ...course, title: '新标题', status: 'partial' }}
          to="/study/courses/course-stable"
        />
      </MemoryRouter>,
    )
    expect(screen.getByRole('link', { name: /新标题/ }).className).toBe(binding)
  })

  it('uses only available, non-revoked lessons for actual reading progress', () => {
    const lessons: CourseLessonSummary[] = [
      { ...lesson, read_at: '2026-09-16' },
      { ...lesson, lesson_id: 'unread' },
      { ...lesson, lesson_id: 'gap', availability: 'material_gap', read_at: '2026-09-16' },
      { ...lesson, lesson_id: 'revoked', status: 'source_revoked', read_at: '2026-09-16' },
    ]
    expect(courseReadingProgress(lessons)).toEqual({ read: 1, total: 2 })
    const { rerender } = render(<CourseReadingProgress lessons={lessons} />)
    expect(screen.getByRole('progressbar')).toHaveAttribute('value', '1')
    expect(screen.getByRole('progressbar')).toHaveAttribute('max', '2')
    expect(screen.getByText('50%')).toBeInTheDocument()
    rerender(<CourseReadingProgress lessons={[lesson]} />)
    expect(screen.getByRole('progressbar')).toHaveAttribute('value', '0')
    rerender(<CourseReadingProgress lessons={[]} />)
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
  })

  it('hides revoked course content and resume links across the entire shelf', async () => {
    vi.spyOn(coursesApi, 'list').mockResolvedValue({
      items: [
        {
          ...course,
          source_status: 'revoked',
          title: '私密标题',
          lessons: [{ ...lesson, read_at: '2026-09-16' }],
        },
      ],
      total: 1,
      page: 1,
      page_size: 6,
    })
    mount(<CourseListSection />)
    expect(await screen.findByRole('heading', { name: '资料已失效的课程' })).toBeInTheDocument()
    expect(screen.queryByText('私密标题')).not.toBeInTheDocument()
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: '查看状态' })).toHaveAttribute(
      'href',
      '/study/courses/course-stable',
    )
  })

  it('shows shelf progress without converting it into a fabricated mastery score', async () => {
    vi.spyOn(coursesApi, 'list').mockResolvedValue({
      items: [course],
      total: 1,
      page: 1,
      page_size: 6,
    })
    mount(<CourseListSection />)
    expect(
      await screen.findByRole('progressbar', { name: 'Python 函数入门阅读进度' }),
    ).toHaveAttribute('value', '0')
    expect(screen.getByRole('link', { name: '查看课程' })).toHaveAttribute(
      'href',
      '/study/courses/course-stable?lesson=lesson-1',
    )
  })

  it('emphasizes only the first suggested activity and retains unavailable-entry handling', async () => {
    vi.spyOn(coursesApi, 'today').mockResolvedValue({
      local_date: '2026-09-16',
      timezone: 'Asia/Shanghai',
      minutes_budget: 20,
      items: [
        {
          kind: 'learn_lesson',
          title: '继续函数',
          reason: '接上上次的阅读',
          estimated_minutes: 10,
          course_id: 'course-stable',
          lesson_id: 'lesson-1',
        },
        { kind: 'learn_lesson', title: '等待入口', reason: '尚无课时入口', estimated_minutes: 5 },
      ],
    })
    mount(<CourseTodayCard />)
    const items = await screen.findAllByRole('listitem')
    expect(items[0]).toHaveClass('is-current')
    expect(items[1]).not.toHaveClass('is-current')
    expect(within(items[0]).getByRole('link', { name: '开始' })).toHaveAttribute(
      'href',
      '/study/courses/course-stable?lesson=lesson-1',
    )
    expect(within(items[1]).getByText('请刷新后查看入口')).toBeInTheDocument()
    await userEvent.selectOptions(screen.getByLabelText('今天可用时间'), '30')
    expect(coursesApi.today).toHaveBeenLastCalledWith(
      expect.any(String),
      30,
      expect.any(AbortSignal),
    )
  })
})

const view: CourseLessonView = {
  lesson_id: 'lesson-1',
  course_id: 'course-stable',
  title: '理解函数',
  status: 'ready',
  content_version: 1,
  revision: 1,
  blocks: [
    { type: 'explanation', synthetic: false, text: '函数封装重复操作。', source_refs: ['ref-1'] },
    { type: 'example', text: '用加法函数作为示例。', synthetic: true },
    { type: 'reference', synthetic: false, text: '来自课程资料。' },
    { type: 'recap', synthetic: false, text: '参数是输入，返回值是输出。' },
  ],
}
function lessonProps() {
  return {
    lesson: view,
    pendingWeakPoints: [],
    onReloadReviews: vi.fn(),
    onGenerate: vi.fn(),
    onEvidence: vi.fn(),
    onUnavailable: vi.fn(),
    onNext: vi.fn(),
  }
}
describe('continuous lesson presentation', () => {
  it('renders the four block types and retains citations, reading, practice and review actions', async () => {
    const props = lessonProps()
    mount(<CourseLesson {...props} />)
    expect(screen.getByRole('region', { name: '课文' })).not.toHaveClass('card')
    for (const [name, type] of [
      ['讲解 1', 'explanation'],
      ['示例 2', 'example'],
      ['资料说明 3', 'reference'],
      ['小结 4', 'recap'],
    ]) {
      expect(screen.getByRole('region', { name })).toHaveClass(`course-block-${type}`)
    }
    await userEvent.click(screen.getByRole('button', { name: '查看第 1 段依据 1' }))
    expect(props.onEvidence).toHaveBeenCalledWith('ref-1')
    expect(screen.getByRole('button', { name: '标记已读' })).toBeEnabled()
    expect(screen.getByRole('button', { name: '生成本课 3 题' })).toBeEnabled()
    expect(screen.getByRole('button', { name: '刷新复习安排' })).toBeEnabled()
    await userEvent.click(screen.getByRole('button', { name: '下一课' }))
    expect(props.onNext).toHaveBeenCalledOnce()
  })

  it('does not render lesson text until generation is ready', async () => {
    const props = lessonProps()
    mount(<CourseLesson {...props} lesson={{ ...view, status: 'not_generated' }} />)
    expect(screen.queryByText('函数封装重复操作。')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '生成这一课' }))
    expect(props.onGenerate).toHaveBeenCalledOnce()
  })
})
