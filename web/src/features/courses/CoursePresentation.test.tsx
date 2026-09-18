import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Link, MemoryRouter, Route, Routes } from 'react-router-dom'
import { CoursePage } from '../../pages/study/CoursePage'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { courseKeys, coursesApi } from '../../services/courses'
import { ApiError } from '../../services/http'
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
  useLessonTutor: () => ({
    query: { isPending: false },
    checksQuery: { isPending: false },
    attempts: [],
    busy: false,
    refreshFeedback: vi.fn(),
  }),
}))
vi.mock('../../services/experienceEvents', () => ({
  recordExperienceEvent: vi.fn().mockResolvedValue(undefined),
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
  criteria_revision: 1,
  teaching_mode: 'fast',
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
const originalScrollIntoView = Object.getOwnPropertyDescriptor(
  HTMLElement.prototype,
  'scrollIntoView',
)
afterEach(() => {
  vi.restoreAllMocks()
  if (originalScrollIntoView)
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', originalScrollIntoView)
  else Reflect.deleteProperty(HTMLElement.prototype, 'scrollIntoView')
  vi.unstubAllGlobals()
})

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

  it('selects books with native buttons and shows only the selected course details', async () => {
    vi.spyOn(coursesApi, 'list').mockResolvedValue({
      items: [
        course,
        {
          ...course,
          course_id: 'second-course',
          title: '第二门课程',
          lessons: [{ ...lesson, read_at: '2026-09-16' }],
        },
        { ...course, course_id: 'revoked-course', title: '私密标题', source_status: 'revoked' },
      ],
      total: 3,
      page: 1,
      page_size: 6,
    })
    mount(<CourseListSection />)
    const first = await screen.findByRole('button', { name: '主题课程 Python 函数入门' })
    expect(first).toHaveAttribute('aria-pressed', 'true')
    expect(first.querySelector('h3')).toBeNull()
    expect(screen.getAllByRole('progressbar')).toHaveLength(1)
    const second = screen.getByRole('button', { name: '主题课程 第二门课程' })
    second.focus()
    await userEvent.keyboard('{Enter}')
    expect(second).toHaveAttribute('aria-pressed', 'true')
    expect(first).toHaveAttribute('aria-pressed', 'false')
    expect(screen.getByRole('region', { name: '第二门课程' })).toHaveAttribute(
      'id',
      second.getAttribute('aria-controls'),
    )
    expect(screen.getAllByRole('progressbar')).toHaveLength(1)
    expect(screen.getByRole('progressbar')).toHaveAttribute('value', '1')
    expect(screen.getByRole('link', { name: '继续学习' })).toHaveAttribute(
      'href',
      '/study/courses/second-course?lesson=lesson-1',
    )
    await userEvent.click(screen.getByRole('button', { name: '资料已失效 资料已失效的课程' }))
    expect(screen.queryByText('私密标题')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /私密标题/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: '查看状态' })).toHaveAttribute(
      'href',
      '/study/courses/revoked-course',
    )
  })

  it('groups books into shared responsive rows and cleans up media listeners', async () => {
    const desktop = {
      matches: true,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }
    const tablet = {
      matches: true,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }
    vi.stubGlobal(
      'matchMedia',
      vi.fn((query: string) => (query.includes('1200') ? desktop : tablet)),
    )
    vi.spyOn(coursesApi, 'list').mockResolvedValue({
      items: Array.from({ length: 5 }, (_, index) => ({ ...course, course_id: `book-${index}` })),
      total: 5,
      page: 1,
      page_size: 6,
    })
    const { container, unmount } = mount(<CourseListSection />)
    await screen.findByRole('group', { name: '选择课程' })
    expect(container.querySelectorAll('.course-bookshelf-row')).toHaveLength(2)
    expect(container.querySelector('.course-bookshelf-row')?.children).toHaveLength(3)
    const cabinet = screen.getByRole('group', { name: '选择课程' })
    expect(cabinet.querySelector('.course-bookshelf-detail')).toBeTruthy()
    expect(container.querySelectorAll('.course-bookshelf-detail')).toHaveLength(1)
    const update = desktop.addEventListener.mock.calls[0][1] as () => void
    act(() => {
      desktop.matches = false
      update()
    })
    expect(container.querySelectorAll('.course-bookshelf-row')).toHaveLength(3)
    expect(container.querySelector('.course-bookshelf-row')?.children).toHaveLength(2)
    act(() => {
      tablet.matches = false
      update()
    })
    expect(container.querySelectorAll('.course-bookshelf-row')).toHaveLength(5)
    expect(container.querySelector('.course-bookshelf-row')?.children).toHaveLength(1)
    const rows = container.querySelectorAll('.course-bookshelf-row')
    expect(rows[0].nextElementSibling).toHaveClass('course-bookshelf-detail')
    await userEvent.click(within(rows[2] as HTMLElement).getByRole('button'))
    expect(rows[2].nextElementSibling).toHaveClass('course-bookshelf-detail')
    expect(rows[0].nextElementSibling).toBe(rows[1])
    expect(container.querySelectorAll('.course-bookshelf-detail')).toHaveLength(1)
    act(() => {
      desktop.matches = true
      tablet.matches = true
      update()
    })
    expect(cabinet.querySelector('.course-bookshelf-detail')).toBeTruthy()
    expect(container.querySelectorAll('.course-bookshelf-detail')).toHaveLength(1)
    expect(screen.getAllByRole('button', { pressed: true })).toHaveLength(1)
    unmount()
    expect(desktop.removeEventListener).toHaveBeenCalledWith('change', update)
    expect(tablet.removeEventListener).toHaveBeenCalledWith('change', update)
  })

  it('allows the study page to omit the duplicate heading without hiding shelf content', async () => {
    vi.spyOn(coursesApi, 'list').mockResolvedValue({
      items: [course],
      total: 1,
      page: 1,
      page_size: 6,
    })
    mount(<CourseListSection showHeading={false} showCreate={false} />)
    await screen.findByRole('group', { name: '选择课程' })
    expect(screen.queryByRole('heading', { name: '我的课程' })).not.toBeInTheDocument()
    expect(screen.queryByText('从上次停下的地方，继续一点点理解。')).not.toBeInTheDocument()
    expect(screen.getByRole('region', { name: '我的课程' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '查看课程' })).toBeInTheDocument()
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
    expect(within(items[0]).getByRole('link', { name: '继续阅读' })).toHaveAttribute(
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
const secondLesson = { ...lesson, lesson_id: 'lesson-2', title: '传递参数', position: 2 }
function mountReader(reducedMotion = false, narrow = true, options: {
  initialEntry?: string
  cachedLesson?: CourseLessonView
} = {}) {
  localStorage.setItem('xunke.outlineCollapsed', '0')
  vi.stubGlobal(
    'matchMedia',
    vi.fn((query: string) => ({
      matches: query.includes('reduced-motion') ? reducedMotion : narrow,
    })),
  )
  const scroll = vi.fn()
  Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
    configurable: true,
    value: scroll,
  })
  vi.spyOn(coursesApi, 'course').mockImplementation(async (id) => ({
    ...course,
    course_id: id,
    lessons: [lesson, secondLesson],
  }))
  vi.spyOn(coursesApi, 'reviews').mockResolvedValue([])
  vi.spyOn(coursesApi, 'outcomes').mockImplementation(async (id) => ({
    course_id: id, criteria_revision: 1, criteria: [],
  }))
  vi.spyOn(coursesApi, 'assessments').mockResolvedValue([])
  vi.spyOn(coursesApi, 'progress').mockResolvedValue({
    course_id: course.course_id,
    available_lessons: 2,
    generated_lessons: 2,
    initial_answered: 0,
    initial_correct: 0,
    practiced_lessons: 0,
    read_lessons: 0,
    total_lessons: 2,
    next_action: { type: 'learn_lesson', lesson_id: 'lesson-2', reason: '继续学习参数' },
  })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  if (options.cachedLesson)
    client.setQueryData(courseKeys.lesson('presentation-test', course.course_id, options.cachedLesson.lesson_id), options.cachedLesson)
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[options.initialEntry || '/study/courses/course-stable?lesson=lesson-1']}>
        <Link to="/study/courses/other-course?lesson=lesson-1">另一门课程</Link>
        <Routes>
          <Route path="/study/courses/:courseId" element={<CoursePage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return { scroll, client }
}

describe('explicit reader navigation', () => {
  it('focuses an explicit summary once and never scrolls again after a background refresh', async () => {
    vi.spyOn(coursesApi, 'lesson').mockResolvedValue(view)
    const { scroll, client } = mountReader()
    await screen.findByRole('heading', { name: '理解函数' })
    await userEvent.click(screen.getByRole('button', { name: '本次先到这里' }))
    const summary = screen.getByRole('region', { name: '本课小结' })
    await waitFor(() => expect(summary).toHaveFocus())
    expect(scroll).toHaveBeenCalledOnce()
    expect(scroll.mock.instances[0]).toBe(summary)
    await act(async () => { await client.invalidateQueries() })
    expect(scroll).toHaveBeenCalledOnce()
  })

  it('waits for fresh owner-scoped data before focusing a cached deep link', async () => {
    let resolveLesson!: (value: CourseLessonView) => void
    const response = new Promise<CourseLessonView>((resolve) => { resolveLesson = resolve })
    vi.spyOn(coursesApi, 'lesson').mockReturnValue(response)
    const { scroll, client } = mountReader(true, true, {
      initialEntry: '/study/courses/course-stable?lesson=lesson-1#lesson-summary', cachedLesson: view,
    })
    await screen.findByRole('heading', { name: '理解函数' })
    expect(scroll).not.toHaveBeenCalled()
    await act(async () => { resolveLesson(view) })
    const summary = screen.getByRole('region', { name: '本课小结' })
    await waitFor(() => expect(summary).toHaveFocus())
    expect(scroll).toHaveBeenCalledExactlyOnceWith({ behavior: 'auto', block: 'start' })
    await act(async () => { await client.invalidateQueries() })
    expect(scroll).toHaveBeenCalledOnce()
  })

  it('does not focus a cached deep link when the fresh lesson read fails', async () => {
    let rejectLesson!: (reason: Error) => void
    const response = new Promise<CourseLessonView>((_resolve, reject) => { rejectLesson = reject })
    vi.spyOn(coursesApi, 'lesson').mockReturnValue(response)
    const { scroll } = mountReader(false, true, {
      initialEntry: '/study/courses/course-stable?lesson=lesson-1#lesson-summary', cachedLesson: view,
    })
    await screen.findByRole('heading', { name: '理解函数' })
    expect(scroll).not.toHaveBeenCalled()
    await act(async () => { rejectLesson(new ApiError('资料已失效', 410, 'source_revoked')) })
    await screen.findByRole('heading', { name: '课程资料已失效' })
    expect(scroll).not.toHaveBeenCalled()
    expect(screen.queryByRole('article', { name: '当前课时' })).not.toBeInTheDocument()
  })

  it.each([false, true])(
    'focuses only after selected data arrives, reduced motion=%s',
    async (reducedMotion) => {
      let resolveSelected!: (value: CourseLessonView) => void
      const selected = new Promise<CourseLessonView>((resolve) => {
        resolveSelected = resolve
      })
      vi.spyOn(coursesApi, 'lesson').mockImplementation(async (_courseId, id) =>
        id === 'lesson-1' ? view : selected,
      )
      const { scroll, client } = mountReader(reducedMotion)
      await screen.findByRole('heading', { name: '理解函数' })
      expect(scroll).not.toHaveBeenCalled()
      await userEvent.click(screen.getByRole('button', { name: /传递参数/ }))
      expect(screen.getByRole('button', { name: '展开课程目录' })).toBeInTheDocument()
      expect(screen.queryByRole('region', { name: '课程纲要' })).not.toBeInTheDocument()
      expect(scroll).not.toHaveBeenCalled()
      await act(async () => {
        resolveSelected({ ...view, ...secondLesson })
      })
      const heading = await screen.findByRole('heading', { name: '传递参数' })
      await waitFor(() => expect(heading).toHaveFocus())
      expect(heading).toHaveAttribute('tabindex', '-1')
      expect(scroll).toHaveBeenCalledExactlyOnceWith({
        behavior: reducedMotion ? 'auto' : 'smooth',
        block: 'start',
      })
      expect(scroll.mock.instances[0]).toBe(heading)
      await act(async () => {
        await client.invalidateQueries()
      })
      expect(scroll).toHaveBeenCalledOnce()
    },
  )

  it('keeps the desktop directory open and supports next-lesson navigation', async () => {
    vi.spyOn(coursesApi, 'lesson').mockImplementation(async (_courseId, id) =>
      id === 'lesson-1' ? view : { ...view, ...secondLesson },
    )
    const { scroll } = mountReader(false, false)
    await screen.findByRole('heading', { name: '理解函数' })
    await userEvent.click(await screen.findByRole('button', { name: '继续下一课' }))
    await waitFor(() => expect(screen.getByRole('heading', { name: '传递参数' })).toHaveFocus())
    expect(screen.getByRole('region', { name: '课程纲要' })).toBeInTheDocument()
    expect(scroll).toHaveBeenCalledOnce()
  })

  it('does not focus stale selected data after navigating to another course', async () => {
    let resolveSelected!: (value: CourseLessonView) => void
    const selected = new Promise<CourseLessonView>((resolve) => {
      resolveSelected = resolve
    })
    vi.spyOn(coursesApi, 'lesson').mockImplementation(async (courseId, id) =>
      id === 'lesson-2' ? selected : { ...view, course_id: courseId },
    )
    const { scroll } = mountReader()
    await screen.findByRole('heading', { name: '理解函数' })
    await userEvent.click(screen.getByRole('button', { name: /传递参数/ }))
    await userEvent.click(screen.getByRole('link', { name: '另一门课程' }))
    await screen.findByRole('heading', { name: '理解函数' })
    await act(async () => {
      resolveSelected({ ...view, ...secondLesson })
    })
    expect(scroll).not.toHaveBeenCalled()
    expect(screen.queryByRole('heading', { name: '传递参数' })).not.toBeInTheDocument()
  })

  it('cancels pending focus and hides content when selected lesson access is revoked', async () => {
    vi.spyOn(coursesApi, 'lesson').mockImplementation(async (_courseId, id) => {
      if (id === 'lesson-1') return view
      throw new ApiError('资料已失效', 410, 'source_revoked')
    })
    const { scroll } = mountReader()
    await screen.findByRole('heading', { name: '理解函数' })
    await userEvent.click(screen.getByRole('button', { name: /传递参数/ }))
    await screen.findByRole('heading', { name: '课程资料已失效' })
    expect(scroll).not.toHaveBeenCalled()
    expect(screen.queryByText('Python 函数入门')).not.toBeInTheDocument()
    expect(screen.queryByRole('article', { name: '当前课时' })).not.toBeInTheDocument()
  })

  it('does not move focus when selected lesson loading fails', async () => {
    vi.spyOn(coursesApi, 'lesson').mockImplementation(async (_courseId, id) => {
      if (id === 'lesson-1') return view
      throw new Error('读取失败')
    })
    const { scroll } = mountReader()
    await screen.findByRole('heading', { name: '理解函数' })
    await userEvent.click(screen.getByRole('button', { name: /传递参数/ }))
    await screen.findByRole('button', { name: '重新加载' })
    expect(scroll).not.toHaveBeenCalled()
    expect(screen.queryByRole('heading', { name: '传递参数' })).not.toBeInTheDocument()
  })
})

function lessonProps() {
  return {
    lesson: view,
    sourcePolicy: 'topic' as const,
    progressState: 'confirmed' as const,
    pendingWeakPoints: [],
    nextAction: { type: 'learn_lesson' as const, lesson_id: 'lesson-2', reason: '继续学习参数' },
    onReloadReviews: vi.fn(),
    onGenerate: vi.fn(),
    onEvidence: vi.fn(),
    onUnavailable: vi.fn(),
    onNextAction: vi.fn(),
  }
}
describe('continuous lesson presentation', () => {
  it('renders the four block types and retains citations, reading, practice and review actions', async () => {
    const props = lessonProps()
    mount(<CourseLesson {...props} />)
    expect(screen.getByRole('region', { name: '本课正文' })).not.toHaveClass('card')
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
    expect(screen.getByRole('button', { name: '记录已读，进入本课练习' })).toBeEnabled()
    expect(screen.getByRole('button', { name: '本次先到这里' })).toBeEnabled()
    expect(screen.getByRole('button', { name: '刷新复习安排' })).toBeEnabled()
    await userEvent.click(screen.getByRole('button', { name: '继续下一课' }))
    expect(props.onNextAction).toHaveBeenCalledExactlyOnceWith(props.nextAction)
  })

  it('does not render lesson text until generation is ready', async () => {
    const props = lessonProps()
    mount(<CourseLesson {...props} lesson={{ ...view, status: 'not_generated' }} />)
    expect(screen.queryByText('函数封装重复操作。')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '生成这一课' }))
    expect(props.onGenerate).toHaveBeenCalledOnce()
  })
})
