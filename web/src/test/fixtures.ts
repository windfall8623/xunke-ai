export const learner = {
  id: 7,
  nickname: '小鱼同学',
  avatar_url: '',
  total_xp: 128,
  role: 'learner',
}
export const session = { user: learner, csrf_token: 'csrf-test' }
export const questions = [
  {
    id: 'q1',
    type: 'single',
    stem: '集合中重复元素应如何处理？',
    options: [
      { key: 'A', text: '只保留一个' },
      { key: 'B', text: '保留所有副本' },
    ],
    knowledge_point: '集合的互异性',
    difficulty: 'easy',
    citation_refs: ['e1'],
  },
  {
    id: 'q2',
    type: 'single',
    stem: '空集与其他集合有什么关系？',
    options: [
      { key: 'A', text: '是任意集合的子集' },
      { key: 'B', text: '仅是非空集合的子集' },
    ],
    knowledge_point: '空集',
    difficulty: 'medium',
    citation_refs: ['e2'],
  },
  {
    id: 'q3',
    type: 'multiple',
    stem: '哪些运算满足交换律？',
    options: [
      { key: 'A', text: '并集' },
      { key: 'B', text: '交集' },
      { key: 'C', text: '差集' },
    ],
    knowledge_point: '集合运算',
    difficulty: 'medium',
    citation_refs: ['e3'],
  },
]
export const quiz = {
  quiz_id: 'quiz-1',
  title: '集合基础练习',
  summary: '理解集合概念与常见运算。',
  questions,
  answer_records: [],
  revision: 0,
  status: 'in_progress',
  source_status: 'verified',
  source_policy: 'strict_docs',
  images_status: 'not_requested',
  report_status: 'not_started',
  source_scope: { type: 'selected_documents', documents: [{ doc_id: 'doc-1' }] },
}
export const documentFixture = {
  doc_id: 'doc-1',
  file_name: '离散数学 · 第一章.pdf',
  file_type: 'pdf',
  file_size: 40960,
  status: 'ready',
  active_version_id: 'version-1',
  active_build_id: 'build-1',
  section_catalog_revision: 'parse-1',
  sections: [{ section_id: 'section-1', title: '第一节 集合基础' }],
  document_revision: 1,
  created_at: '2026-09-07T10:00:00Z',
}

export function json(data: unknown, status = 200) {
  return new Response(JSON.stringify({ code: 0, message: 'ok', data }), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}
export function apiFailure(status = 401, message = '登录已失效') {
  return new Response(
    JSON.stringify({
      code: status * 10,
      error_code: status === 401 ? 'AUTH_REQUIRED' : 'FAILED',
      message,
      data: null,
    }),
    { status, headers: { 'Content-Type': 'application/json' } },
  )
}
