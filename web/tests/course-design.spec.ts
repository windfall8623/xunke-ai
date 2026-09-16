import { test, expect, type Page } from '@playwright/test'
import { installTestApi } from './fixtures'
import {
  courseFixture,
  courseLessonFixture,
  courseListFixture,
  courseProgressFixture,
  courseTodayFixture,
  revokedCourseFixture,
  unstartedCourseFixture,
} from './courseFixtures'

const coursePath = `/study/courses/${courseFixture.course_id}`
const lessonPath = `${coursePath}?lesson=${courseLessonFixture.lesson_id}`

async function installCourseDesignApi(page: Page) {
  const base = await installTestApi(page, { longName: true })
  const course = structuredClone(courseFixture)
  const lesson = structuredClone(courseLessonFixture)
  const progress = structuredClone(courseProgressFixture)
  // Registered after the shared handler: only these routes override the base fixture.
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname.replace('/api/v1', '')
    const respond = (data: unknown) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ code: 0, message: 'ok', data }),
      })
    if (request.method() === 'GET') {
      if (path === '/courses')
        return respond({
          items: [course, ...courseListFixture.slice(1)],
          total: courseListFixture.length,
          page: 1,
          page_size: Number(url.searchParams.get('page_size') || 6),
        })
      if (path === '/courses/today')
        return respond({
          ...courseTodayFixture,
          minutes_budget: Number(url.searchParams.get('minutes_budget') || 20),
        })
      if (path === `/courses/${course.course_id}`) return respond(course)
      if (path === `/courses/${course.course_id}/progress`) return respond(progress)
      if (path === `/courses/${course.course_id}/reviews`) return respond([])
      if (path === `/courses/${course.course_id}/lessons/${lesson.lesson_id}`)
        return respond(lesson)
      if (
        [
          `/courses/${course.course_id}/lessons/${lesson.lesson_id}/tutor-turns`,
          `/courses/${course.course_id}/lessons/${lesson.lesson_id}/self-check-attempts`,
        ].includes(path)
      )
        return respond([])
      if (['/study/reviews', '/study/history'].includes(path))
        return respond({ items: [], total: 0, next_cursor: null })
    }
    if (
      request.method() === 'PATCH' &&
      path === `/courses/${course.course_id}/lessons/${lesson.lesson_id}/progress`
    ) {
      const body = request.postDataJSON() as { read: boolean }
      lesson.read_at = body.read ? '2026-09-16T10:00:00Z' : null
      lesson.revision += 1
      course.lessons = course.lessons?.map((item) =>
        item.lesson_id === lesson.lesson_id ? { ...item, read_at: lesson.read_at } : item,
      )
      progress.read_lessons = body.read ? 3 : 2
      return respond(lesson)
    }
    return route.fallback()
  })
  return base
}

async function expectNoOverflow(page: Page, context: string) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1)
  expect(overflow, `horizontal overflow: ${context}`).toBe(false)
}

async function expectLesson(page: Page) {
  const lesson = page.getByRole('article', { name: '当前课时' })
  await expect(
    lesson.getByRole('heading', { name: courseLessonFixture.title, exact: true }),
  ).toBeVisible()
  await expect(lesson.getByRole('region', { name: '课文', exact: true })).toBeVisible()
  return lesson
}

test('course covers expose saved reading progress, hide revoked content and open the saved lesson', async ({
  page,
}) => {
  await installCourseDesignApi(page)
  await page.goto('/')
  await expect(page.getByRole('heading', { name: '接着上次，继续探索。' })).toBeVisible()
  const shelf = page.getByRole('region', { name: '我的课程', exact: true })
  const cover = shelf.getByRole('link', { name: `主题课程 ${courseFixture.title}`, exact: true })
  await expect(cover).toHaveAttribute('href', lessonPath)
  const reading = shelf.getByRole('progressbar', { name: `${courseFixture.title}阅读进度` })
  await expect(reading).toHaveAttribute('value', '2')
  await expect(reading).toHaveAttribute('max', '4')
  await expect(shelf.getByText('50%', { exact: true })).toBeVisible()
  await expect(
    shelf.getByRole('progressbar', { name: `${unstartedCourseFixture.title}阅读进度` }),
  ).toHaveAttribute('value', '0')
  await expect(shelf.getByText(revokedCourseFixture.title)).toHaveCount(0)
  await expect(shelf.getByText(revokedCourseFixture.mission!.goal)).toHaveCount(0)
  const revoked = shelf
    .getByRole('article')
    .filter({ has: page.getByRole('heading', { name: '资料已失效的课程' }) })
  await expect(revoked.getByRole('progressbar')).toHaveCount(0)
  await expect(revoked.getByRole('link', { name: '查看状态' })).toHaveAttribute(
    'href',
    `/study/courses/${revokedCourseFixture.course_id}`,
  )
  const binding = await cover.getAttribute('class')
  await page.reload()
  await expect(cover).toHaveAttribute('class', binding!)
  await cover.click()
  await expect(page).toHaveURL(lessonPath)
  const lesson = await expectLesson(page)
  for (const label of ['讲解 1', '示例 2', '资料说明 3', '小结 4']) {
    await expect(lesson.getByRole('region', { name: label, exact: true })).toBeVisible()
  }
  await expect(lesson.getByText('示意示例', { exact: true })).toBeVisible()
  await lesson.getByRole('button', { name: '标记已读', exact: true }).click()
  await expect(lesson.getByRole('button', { name: '取消已读标记' })).toBeVisible()
  await expect(
    page.getByRole('progressbar', { name: '课程阅读进度', exact: true }),
  ).toHaveAttribute('value', '3')
  await expect(
    page.getByRole('progressbar', { name: '课程阅读进度', exact: true }),
  ).toHaveAttribute('max', '4')
})

for (const width of [360, 768, 1440]) {
  test(`home and continuous lesson reflow without horizontal overflow at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 960 })
    await installCourseDesignApi(page)
    await page.goto('/')
    await expect(page.getByRole('heading', { name: '接着上次，继续探索。' })).toBeVisible()
    await expect(
      page.getByRole('progressbar', { name: `${courseFixture.title}阅读进度` }),
    ).toBeVisible()
    await expectNoOverflow(page, `home ${width}px`)
    await page.goto(lessonPath)
    const lesson = await expectLesson(page)
    await expect(lesson.locator('pre')).toBeVisible()
    await expectNoOverflow(page, `lesson ${width}px`)
    // Exercise both collapsed and expanded directory layouts, regardless of viewport default.
    const expand = page.getByRole('button', { name: '展开课程目录', exact: true })
    if (await expand.isVisible()) await expand.click()
    await expect(page.getByRole('heading', { name: '课程目录', exact: true })).toBeVisible()
    await expectNoOverflow(page, `expanded outline ${width}px`)
  })
}

test('reduced motion removes cover movement and reading scroll animation', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 960 })
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await installCourseDesignApi(page)
  await page.goto('/')
  const cover = page.getByRole('link', { name: `主题课程 ${courseFixture.title}`, exact: true })
  await expect(cover).toBeVisible()
  await cover.hover()
  const motion = await cover.evaluate((element) => {
    const style = getComputedStyle(element)
    return {
      transform: style.transform,
      durations: style.transitionDuration.split(',').map((value) => Number.parseFloat(value)),
    }
  })
  expect(motion.transform).toBe('none')
  expect(motion.durations.every((duration) => duration <= 0.001)).toBe(true)
  await cover.click()
  await expectLesson(page)
  await expect(page.getByRole('region', { name: '课文', exact: true })).toHaveCSS(
    'scroll-behavior',
    'auto',
  )
  // Observe the actual hash-navigation scroll request without replacing native behavior.
  await page.evaluate(() => {
    const original = Element.prototype.scrollIntoView
    const state = window as typeof window & { courseScrollBehaviors?: (string | undefined)[] }
    state.courseScrollBehaviors = []
    Element.prototype.scrollIntoView = function (options) {
      state.courseScrollBehaviors!.push(typeof options === 'object' ? options.behavior : undefined)
      original.call(this, options)
    }
  })
  await page.evaluate(() => {
    window.location.hash = 'course-practice'
  })
  await expect
    .poll(() =>
      page.evaluate(
        () =>
          (window as typeof window & { courseScrollBehaviors?: string[] }).courseScrollBehaviors,
      ),
    )
    .toContain('auto')
})

test('mobile More navigation is a dialog and Escape restores its trigger focus', async ({
  page,
}) => {
  await page.setViewportSize({ width: 360, height: 800 })
  await installCourseDesignApi(page)
  await page.goto('/')
  await expect(page.getByRole('heading', { name: '接着上次，继续探索。' })).toBeVisible()
  const tabs = page.getByRole('navigation', { name: '手机导航' })
  await expect(tabs.getByRole('link')).toHaveCount(3)
  await expect(page.getByRole('navigation', { name: '主要导航' })).toBeHidden()
  const more = tabs.getByRole('button', { name: '更多导航' })
  await more.focus()
  await page.keyboard.press('Enter')
  const dialog = page.getByRole('dialog', { name: '导航', exact: true })
  await expect(dialog).toBeVisible()
  await expect(dialog.getByRole('navigation', { name: '全部导航' })).toBeVisible()
  await expect(more).toHaveAttribute('aria-expanded', 'true')
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  await expect(more).toBeFocused()
  await expect(more).toHaveAttribute('aria-expanded', 'false')
  await more.click()
  const close = dialog.getByRole('button', { name: '关闭导航', exact: true })
  await expect(close).toHaveCSS('color', 'rgb(37, 50, 56)')
  await close.click()
  await expect(dialog).toHaveCount(0)
  await more.click()
  await dialog.getByRole('link', { name: '我的资料', exact: true }).click()
  await expect(page).toHaveURL(/\/knowledge$/)
  await expect(dialog).toHaveCount(0)
})

test('advanced practice settings expand by keyboard and retain the submitted choices', async ({
  page,
}) => {
  const state = await installCourseDesignApi(page)
  await page.goto('/')
  await expect(page.getByRole('heading', { name: '接着上次，继续探索。' })).toBeVisible()
  const settings = page.locator('details.practice-options')
  await expect(settings).not.toHaveAttribute('open', '')
  await expect(page.getByLabel('题目数量', { exact: true })).toBeHidden()
  const toggle = settings.locator('summary')
  await expect(toggle).toContainText('调整练习设置')
  await toggle.focus()
  await page.keyboard.press('Enter')
  await expect(settings).toHaveAttribute('open', '')
  await page.getByLabel('题目数量', { exact: true }).selectOption('3')
  await page.getByLabel('练习难度', { exact: true }).selectOption('easy')
  await page.getByRole('checkbox', { name: /添加辅助配图/ }).check()
  await toggle.click()
  await expect(settings).not.toHaveAttribute('open', '')
  await expect(toggle).toContainText('3 题 / 入门')
  await page.getByLabel('学习目标', { exact: true }).fill('理解函数的参数与返回值')
  await page.getByRole('button', { name: '生成练习', exact: true }).click()
  await expect.poll(() => state.generationRequests.length).toBe(1)
  expect(state.generationRequests[0]).toMatchObject({
    question_count: 3,
    difficulty: 'easy',
    generate_images: true,
    source_policy: 'topic',
  })
})
