import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { useIdentityKey } from '../../app/AuthProvider'
import {
  completePractice,
  getPractice,
  practiceKeys,
  submitPracticeAnswer,
} from '../../services/practice'
import { ApiError } from '../../services/http'
import { studyKeys } from '../../services/study'
import type { PracticeAnswer, PracticeAnswerBody, PracticeQuestion } from '../../types/practice'

export type PendingPracticeAnswer = {
  key: string
  questionId: string
  questionVersion: string
  body: PracticeAnswerBody
}
const canonical = (answer: PracticeAnswer): PracticeAnswer =>
  answer.type === 'cloze'
    ? {
        type: 'cloze',
        blanks: [...answer.blanks].sort((a, b) => a.blank_id.localeCompare(b.blank_id)),
      }
    : answer

export function usePracticeProgress(practiceId: string) {
  const identity = useIdentityKey()
  const client = useQueryClient()
  const [packages, setPackages] = useState<Record<string, PendingPracticeAnswer>>({})
  const pending = useRef<Record<string, PendingPracticeAnswer>>({})
  const inFlight = useRef(new Set<string>())
  const alive = useRef(true)
  const controllers = useRef(new Set<AbortController>())
  const storageKey = (questionId: string) =>
    `qa-submission:${identity}:practice:${practiceId}:${questionId}`
  const queryKey = practiceKeys.practice(identity, practiceId)
  const practiceQuery = useQuery({
    queryKey,
    queryFn: ({ signal }) => getPractice(practiceId, signal),
    retry: false,
    staleTime: 0,
    gcTime: 0,
    refetchInterval: (query) =>
      query.state.data?.status === 'generating' ||
      query.state.data?.submissions?.some((item) =>
        ['pending', 'running'].includes(item.grading_status || ''),
      )
        ? 2500
        : false,
    refetchIntervalInBackground: false,
  })
  function forget(questionId: string) {
    delete pending.current[questionId]
    try {
      sessionStorage.removeItem(storageKey(questionId))
    } catch {
      /* Storage may be disabled. */
    }
    if (alive.current) setPackages({ ...pending.current })
  }
  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
      controllers.current.forEach((controller) => controller.abort())
    }
  }, [])
  useEffect(() => {
    const practice = practiceQuery.data
    if (!practice || practiceQuery.error) return
    if (practice.source_status !== 'active') {
      pending.current = {}
      setPackages({})
      return
    }
    for (const question of practice.questions || []) {
      if (practice.submissions?.some((attempt) => attempt.question_id === question.id)) {
        forget(question.id)
        continue
      }
      if (pending.current[question.id]) continue
      try {
        const stored = JSON.parse(
          sessionStorage.getItem(storageKey(question.id)) || 'null',
        ) as PendingPracticeAnswer | null
        if (
          stored &&
          stored.questionId === question.id &&
          stored.questionVersion === question.question_version &&
          typeof stored.key === 'string' &&
          stored.body?.answer?.type === question.type &&
          Number.isInteger(stored.body.duration_ms) &&
          stored.body.duration_ms >= 0 &&
          stored.body.duration_ms <= 86400000
        )
          pending.current[question.id] = stored
      } catch {
        /* Invalid storage is never sent automatically. */
      }
    }
    setPackages({ ...pending.current })
    // Scope and user changes remount PracticePage; restoring a draft never submits it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [practiceQuery.data, practiceQuery.error])
  const answerMutation = useMutation({
    mutationFn: async ({
      question,
      answer,
      duration,
    }: {
      question: PracticeQuestion
      answer: PracticeAnswer
      duration: number
    }) => {
      if (inFlight.current.has(question.id))
        throw new ApiError('这道题正在提交，请稍候。', 409, 'SUBMIT_PENDING')
      inFlight.current.add(question.id)
      const controller = new AbortController()
      controllers.current.add(controller)
      const submission = pending.current[question.id] || {
        key: crypto.randomUUID(),
        questionId: question.id,
        questionVersion: question.question_version,
        body: {
          answer: canonical(answer),
          duration_ms: Math.max(0, Math.min(86400000, Math.round(duration))),
        },
      }
      pending.current[question.id] = submission
      setPackages({ ...pending.current })
      try {
        sessionStorage.setItem(storageKey(question.id), JSON.stringify(submission))
      } catch {
        /* In-memory retries still preserve the original request. */
      }
      try {
        return await submitPracticeAnswer(
          practiceId,
          question.id,
          submission.body,
          submission.key,
          controller.signal,
        )
      } finally {
        controllers.current.delete(controller)
        inFlight.current.delete(question.id)
      }
    },
    onSuccess: async (receipt) => {
      if (!alive.current) return
      forget(receipt.question_id)
      await client.invalidateQueries({ queryKey })
    },
    onError: async (error, variables) => {
      if (!alive.current) return
      if (error instanceof ApiError && error.status === 422) forget(variables.question.id)
      if (error instanceof ApiError && [403, 404, 409, 410].includes(error.status))
        await client.invalidateQueries({ queryKey })
    },
  })
  const completion = useMutation({
    mutationFn: () => completePractice(practiceId, practiceQuery.data!.revision),
    onSuccess: async () => {
      if (!alive.current) return
      await Promise.all([
        client.invalidateQueries({ queryKey }),
        client.invalidateQueries({ queryKey: studyKeys.all(identity) }),
      ])
    },
    onError: async () => {
      if (alive.current) await client.invalidateQueries({ queryKey })
    },
  })
  return { practiceQuery, answerMutation, completion, pendingAnswers: packages }
}
