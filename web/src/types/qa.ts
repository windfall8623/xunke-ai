import type { ApiSchemas } from './api'

export type QaEvidence = ApiSchemas['DocumentEvidence']
export type QaScope = ApiSchemas['PublicResolvedScope']
export type QaSession = ApiSchemas['QaSessionView']
export type QaSessionList = ApiSchemas['QaSessionList']
/** Title can be omitted so the server applies its fixed, privacy-safe default. */
export type QaSessionCreate = Omit<ApiSchemas['QaSessionCreate'], 'title'> &
  Partial<Pick<ApiSchemas['QaSessionCreate'], 'title'>>
export type QaScopeUpdate = ApiSchemas['QaScopeUpdate']
export type QaMessageCreate = ApiSchemas['QaMessageCreate']
export type QaAnswer = ApiSchemas['QaAnswerView']
export type QaTask = ApiSchemas['QaTaskView']
export type QaMessage = ApiSchemas['QaMessageView']
export type QaMessageList = ApiSchemas['QaMessageList']
export type QaFeedback = ApiSchemas['QaFeedbackBody']
export type QaFeedbackView = ApiSchemas['QaFeedbackView']
