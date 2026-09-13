import { useEffect, useState } from 'react'
import {
  getReminderPreferences,
  updateReminderPreferences,
  type LearningReminderPreferences,
} from '../../services/learningSummary'

/**
 * 可控提醒设置（B07）：默认站内与邮件都关闭；打开邮件前提示
 * 使用注册邮箱，内容只有短提示与站内入口。
 */
export function LearningReminderSettings() {
  const [prefs, setPrefs] = useState<LearningReminderPreferences | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const [pending, setPending] = useState(false)

  useEffect(() => {
    let active = true
    getReminderPreferences()
      .then((view) => {
        if (active) setPrefs(view)
      })
      .catch(() => {
        if (active) setError('提醒设置暂未读回，请稍后重试。')
      })
    return () => {
      active = false
    }
  }, [])

  async function save(patch: Partial<LearningReminderPreferences>) {
    if (!prefs || pending) return
    setPending(true)
    setError(null)
    try {
      const view = await updateReminderPreferences({
        expected_revision: prefs.revision,
        in_app_enabled: patch.in_app_enabled ?? prefs.in_app_enabled,
        email_enabled: patch.email_enabled ?? prefs.email_enabled,
        frequency: patch.frequency ?? prefs.frequency,
        local_time: prefs.local_time,
        timezone: prefs.timezone,
      })
      setPrefs(view)
      setSaved(true)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '保存未完成，请刷新后重试')
    } finally {
      setPending(false)
    }
  }

  if (error) return <p className="tiny muted">{error}</p>
  if (!prefs) return null
  return (
    <section className="card reminder-settings" aria-label="学习提醒设置">
      <h3>学习提醒</h3>
      <p className="tiny muted">
        默认关闭。邮件只发送短提示和站内入口，不包含答题内容或薄弱点列表；
        使用注册邮箱接收，不能填写其他地址。
      </p>
      <div className="button-row">
        <button
          type="button"
          className="button secondary"
          disabled={pending}
          onClick={() => void save({ in_app_enabled: !prefs.in_app_enabled })}
        >
          站内提醒：{prefs.in_app_enabled ? '已开启（点击关闭）' : '已关闭（点击开启）'}
        </button>
        <button
          type="button"
          className="button secondary"
          disabled={pending}
          onClick={() => void save({ email_enabled: !prefs.email_enabled })}
        >
          邮件周报：{prefs.email_enabled ? '已开启（点击关闭）' : '已关闭（点击开启）'}
        </button>
        {prefs.in_app_enabled || prefs.email_enabled ? (
          <button
            type="button"
            className="button secondary"
            disabled={pending}
            onClick={() => void save({ frequency: prefs.frequency === 'weekly' ? 'daily_due' : 'weekly' })}
          >
            频率：{prefs.frequency === 'weekly' ? '每周一封' : '每天到期提醒'}
          </button>
        ) : null}
      </div>
      {saved && <p className="tiny muted" role="status">已保存。</p>}
    </section>
  )
}
