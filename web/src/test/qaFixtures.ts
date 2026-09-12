import { documentFixture } from './fixtures'
import type { QaAnswer, QaEvidence, QaMessage, QaSession, QaTask } from '../types/qa'

export const qaDocument = {
  ...documentFixture,
  sections: [{ section_id: 'parse-1:section-1', title: '第一节 集合基础' }],
}

export const qaEvidence = {
  evidence_id: 'evidence-1',
  source_type: 'document' as const,
  owner_id: 7,
  namespace: 'production',
  title: qaDocument.file_name,
  excerpt: '集合中的元素具有互异性，重复出现的元素只计一次。',
  text_hash: 'a'.repeat(64),
  doc_id: 'doc-1',
  document_version_id: 'version-1',
  parse_artifact_id: 'parse-1',
  index_build_id: 'build-1',
  attempt_id: 'attempt-1',
  chunk_id: 'chunk-1',
  locator: {
    source_sha256: 'b'.repeat(64),
    parse_artifact_id: 'parse-1',
    canonical_text_hash: 'c'.repeat(64),
    parser_version: 'fixture-v1',
    normalizer_version: 'fixture-v1',
    block_id: 'block-1',
    start_char: 0,
    end_char: 26,
    quote_hash: 'a'.repeat(64),
    section_id: 'parse-1:section-1',
    heading_path: ['第一章', '第一节 集合基础'],
    page: 2,
  },
} satisfies QaEvidence

export const qaSession = {
  session_id: 'session-1',
  title: '集合学习',
  scope_revision: 1,
  source_status: 'active' as const,
  active_task_id: null as string | null,
  scope: {
    documents: [
      {
        doc_id: 'doc-1',
        document_version_id: 'version-1',
        source_sha256: 'b'.repeat(64),
        parse_artifact_id: 'parse-1',
        canonical_text_hash: 'c'.repeat(64),
        index_build_id: 'build-1',
        authorization_revision: 1,
        title: qaDocument.file_name,
        section_ids: [] as string[],
        section_catalog_revision: null as string | null,
      },
    ],
  },
  created_at: '2026-09-08T12:00:00Z',
  updated_at: '2026-09-08T12:00:00Z',
} satisfies QaSession

export const qaAnswer = {
  answer_id: 'answer-1',
  session_id: 'session-1',
  message_id: 'message-2',
  scope_revision: 1,
  answer_status: 'answered' as const,
  blocks: [
    {
      block_id: 'answer-block-1',
      text: '重复元素只保留一个。',
      kind: 'fact' as const,
      citation_refs: ['evidence-1'],
    },
  ],
  evidence: [qaEvidence],
  retrieval_query: '集合中重复元素如何处理？',
  usage: { cost_usd: null, cost_status: 'unreported' },
  created_at: '2026-09-08T12:01:00Z',
} satisfies QaAnswer

export const qaMessages = [
  {
    message_id: 'message-1',
    session_id: 'session-1',
    sequence: 1,
    role: 'user' as const,
    content: '集合中重复元素如何处理？',
    scope_revision: 1,
    task_id: 'task-1',
    status: 'completed' as const,
    answer: null,
    error_code: null,
    created_at: '2026-09-08T12:00:00Z',
  },
  {
    message_id: 'message-2',
    session_id: 'session-1',
    sequence: 2,
    role: 'assistant' as const,
    content: '重复元素只保留一个。',
    scope_revision: 1,
    task_id: 'task-1',
    status: 'completed' as const,
    answer: qaAnswer,
    error_code: null,
    created_at: '2026-09-08T12:01:00Z',
  },
] satisfies QaMessage[]

export const qaTask = {
  task_id: 'task-1',
  session_id: 'session-1',
  message_id: 'message-2',
  status: 'pending' as const,
  stage: 'queued',
  error_code: null,
  error_message: null,
  answer: null,
  queue_ms: null,
  execution_ms: null,
} satisfies QaTask
