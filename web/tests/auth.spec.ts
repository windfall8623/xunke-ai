import { test, expect } from '@playwright/test'
import { installTestApi } from './fixtures'

test('expired session returns protected navigation to login then resumes the page', async ({
  page,
}) => {
  const state = await installTestApi(page, { guest: true })
  await page.goto('/knowledge')
  await expect(page).toHaveURL(/\/login$/)
  await page.getByLabel('账号或邮箱', { exact: true }).fill('xiaoyu')
  await page.getByLabel('密码', { exact: true }).fill('a-strong-password')
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page.getByRole('heading', { name: '我的资料', exact: true })).toBeVisible()
  expect(state.authenticated).toBe(true)
  await expect.poll(() => page.evaluate(() => localStorage.length)).toBe(0)
})

test('registration shows the recovery code until the user acknowledges it', async ({ page }) => {
  await installTestApi(page, { guest: true })
  await page.goto('/login')
  await page.getByRole('button', { name: '立即注册' }).click()
  await page.getByLabel('邮箱', { exact: true }).fill('xiaoyu-new@example.test')
  await page.getByRole('button', { name: '发送验证码', exact: true }).click()
  await page.getByLabel('邮箱验证码', { exact: true }).fill('123456')
  await page.getByLabel('昵称', { exact: true }).fill('新同学')
  await page.getByLabel('密码', { exact: true }).fill('a-strong-password')
  await page.getByRole('button', { name: '注册账号', exact: true }).click()
  await expect(page.getByRole('heading', { name: '保存你的恢复码' })).toBeVisible()
  await expect(page.getByText('TEST-RECOVERY-ONLY-ONCE')).toBeVisible()
  await page.getByRole('button', { name: '我已保存，开始学习' }).click()
  await expect(page.getByRole('button', { name: '生成练习', exact: true })).toBeVisible()
})

test('a learner cannot open the evaluation workbench', async ({ page }) => {
  await installTestApi(page)
  await page.goto('/evaluations')
  await expect(page.getByRole('heading', { name: '此页面需要评测权限' })).toBeVisible()
  await expect(page.getByRole('link', { name: '评测工作台' })).toHaveCount(0)
})

test('legacy migration stays hidden when the server disables it', async ({ page }) => {
  await installTestApi(page, { guest: true })
  await page.goto('/login')
  await expect(page.getByRole('heading', { name: '欢迎回来' })).toBeVisible()
  await expect(page.getByRole('button', { name: '迁移旧账号', exact: true })).toHaveCount(0)
})

test('enabled legacy migration redeems a code and shows recovery before resuming learning', async ({
  page,
}) => {
  const state = await installTestApi(page, { guest: true })
  state.user.nickname = '原微信学习者'
  state.user.total_xp = 246
  const bindRequests: unknown[] = []
  await page.route('**/api/v1/auth/capabilities', (route) =>
    route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({ code: 0, data: { legacy_link_enabled: true } }),
    }),
  )
  await page.route('**/api/v1/auth/bind', (route) => {
    bindRequests.push(route.request().postDataJSON())
    state.authenticated = true
    return route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        code: 0,
        data: {
          user: state.user,
          csrf_token: 'browser-csrf',
          recovery_code: 'MIGRATION-RECOVERY-ONLY-ONCE',
        },
      }),
    })
  })
  await page.goto('/knowledge')
  await page.getByRole('button', { name: '迁移旧账号', exact: true }).click()
  await page.getByLabel('原账号', { exact: true }).fill('existing-learner')
  await page.getByLabel('一次性迁移码').fill('LEGACY-CODE-FOR-BROWSER-TEST')
  await page.getByLabel('密码', { exact: true }).fill('Strong-secret-357!')
  await page.getByRole('button', { name: '关联并设置网页账号' }).click()
  await expect(page.getByRole('heading', { name: '保存你的恢复码' })).toBeVisible()
  expect(bindRequests).toEqual([
    {
      account: 'existing-learner',
      password: 'Strong-secret-357!',
      code: 'LEGACY-CODE-FOR-BROWSER-TEST',
      verification_code: '',
    },
  ])
  await page.getByRole('button', { name: '我已保存，开始学习' }).click()
  await expect(page).toHaveURL(/\/knowledge$/)
  await expect(page.locator('.account-link')).toContainText('原微信学习者')
  await expect(page.getByText('MIGRATION-RECOVERY-ONLY-ONCE')).toHaveCount(0)
  expect(await page.evaluate(() => localStorage.length + sessionStorage.length)).toBe(0)
})
