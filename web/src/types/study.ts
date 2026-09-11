import type { ApiSchemas } from './api'

export type StudyScope = ApiSchemas['PublicResolvedScope']
export type StudyScopeView = ApiSchemas['StudyScopeView']
export type StudyScopeUpdate = ApiSchemas['StudyScopeUpdate']
export type StudySpace = ApiSchemas['StudySpaceView']
export type StudySpaceCreate = ApiSchemas['StudySpaceCreate']
export type StudySpaceUpdate = ApiSchemas['StudySpaceUpdate']
export type StudySpaceList = ApiSchemas['StudySpaceList']
export type StudyGoal = ApiSchemas['StudyGoalView']
export type StudyGoalCreate = ApiSchemas['StudyGoalCreate']
export type StudyGoalUpdate = ApiSchemas['StudyGoalUpdate']
export type StudyGoalList = ApiSchemas['StudyGoalList']
export type StudyUnit = ApiSchemas['StudyUnitView']
export type StudyUnitCreate = ApiSchemas['StudyUnitCreate']
export type StudyUnitUpdate = ApiSchemas['StudyUnitUpdate']
export type StudyUnitReorder = ApiSchemas['StudyUnitReorder']
export type StudyUnitList = ApiSchemas['StudyUnitList']
export type StudyConcept = ApiSchemas['StudyConceptView']
export type StudyConceptCreate = ApiSchemas['StudyConceptCreate']
export type StudyConceptUpdate = ApiSchemas['StudyConceptUpdate']
export type StudyConceptList = ApiSchemas['StudyConceptList']
export type StudyQaPracticeContext = ApiSchemas['StudyQaPracticeContextView']
export type StudyQuizFromQa = ApiSchemas['StudyQuizFromQaBody']
export type StudyObjective = ApiSchemas['ObjectiveRef']
export type StudyReview = ApiSchemas['StudyReviewView']
export type StudyReviewList = ApiSchemas['StudyReviewList']
export type StudyReviewUpdate = ApiSchemas['ReviewUpdateBody']
export type StudyReviewQuiz = ApiSchemas['ReviewQuizBody']
export type StudyWrongQuestion = ApiSchemas['StudyWrongQuestionView']
export type StudyWrongQuestionList = ApiSchemas['StudyWrongQuestionList']
export type StudyHistory = ApiSchemas['StudyHistoryView']
export type StudyHistoryList = ApiSchemas['StudyHistoryList']
export type StudyConceptProgress = ApiSchemas['StudyConceptProgressView']

export type StudyListFilters = {
  space_id?: string
  concept_id?: string
  scope_revision?: number
  status?: string
  origin_kind?: 'quiz' | 'practice'
  question_type?: StudyWrongQuestion['question_type']
  association_status?: 'linked' | 'unlinked'
  paused?: boolean
  due_before?: string
  cursor?: string
  limit?: number
}
