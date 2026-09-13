export type ContentBlock = { block_id: string; text: string; source_refs: string[] }
export type ContentFrame = {
  schema_version: 'xunke-content.v1'
  task_id: string
  execution_id: string
  generation_revision: number
  seq: number
  type: 'snapshot' | 'delta' | 'block' | 'reset' | 'finalized' | 'unavailable' | 'revoked'
  payload: {
    block_id?: string
    text?: string
    validated_blocks?: ContentBlock[]
    validation?: 'preview' | 'structure_and_references_checked'
    reason?: string
  }
}

export type ContentPreviewState = {
  taskId?: string
  executionId?: string
  generationRevision: number
  seq: number
  text: string
  blocks: ContentBlock[]
  status: 'waiting' | 'streaming' | 'reconnecting' | 'finalized' | 'unavailable' | 'revoked'
}

export const emptyContentPreview: ContentPreviewState = {
  generationRevision: 0, seq: 0, text: '', blocks: [], status: 'waiting',
}
