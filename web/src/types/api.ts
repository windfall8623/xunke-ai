import type { components } from './api.generated'

/** Concrete server schemas are generated; opaque legacy response fields stay local. */
export type ApiSchemas = components['schemas']
export type User = ApiSchemas['UserView']
export type Role = User['role']
export type AuthSession = ApiSchemas['SessionView']
export type Profile = ApiSchemas['UserProfile']
export interface Page<T> {
  items: T[]
  total: number
  page?: number
  page_size?: number
}
export type Difficulty = ApiSchemas['GenerateBody']['difficulty']
export type SourcePolicy = NonNullable<ApiSchemas['GenerateBody']['source_policy']>
export type SourceStatus = ApiSchemas['QuizView']['source_status']
export type SelectedDocument = ApiSchemas['RequestedDocument']
export type SourceScope = ApiSchemas['RequestedScope']
export type SourceExcerpt = ApiSchemas['SourceExcerptView']
/** These two request fields have server defaults and can be omitted by callers. */
export type GenerateRequest = Omit<ApiSchemas['GenerateBody'], 'difficulty' | 'generate_images'> &
  Partial<Pick<ApiSchemas['GenerateBody'], 'difficulty' | 'generate_images'>>
export type Question = ApiSchemas['QuestionView']
export type AnswerRecord = ApiSchemas['AnswerView']
export type Quiz = ApiSchemas['QuizView'] & {
  answered_count?: number
  correct_count?: number
  image_notice?: string | null
}
export type AnswerReceipt = ApiSchemas['AnswerReceipt']
export type CompletionReceipt = ApiSchemas['CompletionReceipt']
export type Task = ApiSchemas['TaskView']
export type ReportText = ApiSchemas['ReportText']
export type Report = ApiSchemas['ReportView']
export type HistoryItem = ApiSchemas['QuizHistoryItem']
export type DocumentItem = ApiSchemas['DocumentView']
/** Display also accepts locator names retained in older saved evidence. */
export type EvidenceLocator = Partial<ApiSchemas['DocumentLocator']> & {
  page_number?: number
  title_path?: string[] | string
  section_title?: string
  line?: number
}
export type Evidence = ApiSchemas['DocumentEvidence'] | ApiSchemas['PublicWebEvidence']
export type Feedback = ApiSchemas['FeedbackCreate']
