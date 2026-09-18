import { request } from './http'
import type { ApiSchemas } from '../types/api'

export type WeeklyLearningSummary = ApiSchemas['WeeklyLearningSummary']
export type LearningReminderPreferences = ApiSchemas['LearningReminderPreferences']
export type LearningReminderPreferencesUpdate = ApiSchemas['LearningReminderPreferencesUpdate']
export type LearningReminderView = ApiSchemas['LearningReminderView']

const segment = encodeURIComponent

/** 本周一（ISO 星期一）。 */
export function mondayOf(date = new Date()): string {
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000)
  const iso = local.toISOString().slice(0, 10)
  const day = new Date(`${iso}T00:00:00`).getUTCDay()
  const offset = (day + 6) % 7
  const monday = new Date(`${iso}T00:00:00Z`)
  monday.setUTCDate(monday.getUTCDate() - offset)
  return monday.toISOString().slice(0, 10)
}

export function getWeeklySummary(timezone: string, signal?: AbortSignal) {
  return request<WeeklyLearningSummary>(
    `/study/weekly-summary?week_start=${mondayOf()}&timezone=${encodeURIComponent(timezone)}`,
    { signal },
  )
}

export function getReminderPreferences(signal?: AbortSignal) {
  return request<LearningReminderPreferences>('/study/notification-preferences', { signal })
}

export function updateReminderPreferences(
  body: LearningReminderPreferencesUpdate,
  signal?: AbortSignal,
) {
  return request<LearningReminderPreferences>('/study/notification-preferences', {
    method: 'PATCH',
    data: body,
    signal,
  })
}

export function listReminders(signal?: AbortSignal) {
  return request<{ items: LearningReminderView[]; total: number }>('/study/reminders', { signal })
}

/** 已读只更新提醒；稍后提醒只推迟这一条，不伪造完成。 */
export function updateReminder(
  reminderId: string,
  body: { action: 'read' | 'snooze'; send_after?: string },
  signal?: AbortSignal,
) {
  return request<LearningReminderView>(
    `/study/reminders/${segment(reminderId)}`,
    { method: 'PATCH', data: body, signal },
  )
}
