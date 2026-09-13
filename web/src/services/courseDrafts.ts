import type { SourceScope } from '../types/api'
import type { CourseSourcePolicy, CourseTeachingMode } from '../types/course'

/** A local form draft, never a copy of a server response or document contents. */
export type CourseDraft = {
  topic: string
  goal: string
  prior_knowledge: string
  daily_minutes: number
  lesson_count: number
  timezone: string
  preload_first_lesson: boolean
  source_policy: CourseSourcePolicy
  teaching_mode: CourseTeachingMode
  scope: SourceScope | null
  document_versions: Record<string, string>
}

const prefix = 'course-draft:'
const storageKey = (identity: string | number) => `${prefix}${encodeURIComponent(identity)}`
const record = (value: unknown): value is Record<string, unknown> =>
  !!value && typeof value === 'object' && !Array.isArray(value)
const shortText = (value: unknown, limit: number) =>
  typeof value === 'string' ? value.slice(0, limit) : ''

export function loadCourseDraft(identity: string | number): CourseDraft | null {
  if (identity === 'guest') return null
  try {
    const raw = sessionStorage.getItem(storageKey(identity))
    if (!raw || raw.length > 50_000) return null
    const saved: unknown = JSON.parse(raw)
    if (!record(saved) || saved.version !== 1 || !record(saved.draft)) return null
    const draft = saved.draft
    const documents =
      record(draft.scope) && Array.isArray(draft.scope.documents)
        ? draft.scope.documents
            .filter(record)
            .slice(0, 5)
            .flatMap((doc) => {
              if (typeof doc.doc_id !== 'string' || !doc.doc_id || doc.doc_id.length > 128)
                return []
              return [
                {
                  doc_id: doc.doc_id,
                  ...(Array.isArray(doc.section_ids)
                    ? {
                        section_ids: doc.section_ids
                          .filter((id): id is string => typeof id === 'string' && id.length <= 256)
                          .slice(0, 100),
                      }
                    : {}),
                  ...(typeof doc.section_catalog_revision === 'string'
                    ? { section_catalog_revision: doc.section_catalog_revision.slice(0, 256) }
                    : {}),
                },
              ]
            })
        : []
    const versions = record(draft.document_versions) ? draft.document_versions : {}
    return {
      topic: shortText(draft.topic, 2000),
      goal: shortText(draft.goal, 1000),
      prior_knowledge: shortText(draft.prior_knowledge, 1000),
      daily_minutes:
        typeof draft.daily_minutes === 'number' && Number.isFinite(draft.daily_minutes)
          ? draft.daily_minutes
          : 20,
      lesson_count:
        typeof draft.lesson_count === 'number' && Number.isFinite(draft.lesson_count)
          ? draft.lesson_count
          : 6,
      timezone: shortText(draft.timezone, 100) || 'Asia/Shanghai',
      preload_first_lesson: draft.preload_first_lesson !== false,
      source_policy: draft.source_policy === 'strict_docs' ? 'strict_docs' : 'topic',
      teaching_mode: draft.teaching_mode === 'fast' ? 'fast' : 'guided',
      scope: documents.length ? { type: 'selected_documents', documents } : null,
      document_versions: Object.fromEntries(
        documents.flatMap((doc) => {
          const version = versions[doc.doc_id]
          return typeof version === 'string' && version.length <= 2000
            ? [[doc.doc_id, version]]
            : []
        }),
      ),
    }
  } catch {
    return null
  }
}

export function saveCourseDraft(identity: string | number, draft: CourseDraft) {
  if (identity === 'guest') return
  try {
    sessionStorage.setItem(storageKey(identity), JSON.stringify({ version: 1, draft }))
  } catch {
    // The form remains usable when this browser does not allow session storage.
  }
}

export function clearCourseDraft(identity: string | number) {
  try {
    sessionStorage.removeItem(storageKey(identity))
  } catch {
    /* Optional browser storage. */
  }
}

export function clearCourseDrafts(keepIdentity?: string | number) {
  try {
    const keep = keepIdentity === undefined ? null : storageKey(keepIdentity)
    for (let index = sessionStorage.length - 1; index >= 0; index--) {
      const key = sessionStorage.key(index)
      if (key?.startsWith(prefix) && key !== keep) sessionStorage.removeItem(key)
    }
  } catch {
    /* Optional browser storage. */
  }
}
