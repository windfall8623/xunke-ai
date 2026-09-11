import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useRef } from 'react'
import { useIdentityKey } from '../../app/AuthProvider'
import { api } from '../../services/api'
import { ApiError } from '../../services/http'
import type { Quiz } from '../../types/api'

export function useQuizProgress(quizId: string) {
  const identity = useIdentityKey()
  const client = useQueryClient()
  const key = [identity, 'quiz', quizId] as const
  const pendingAnswer = useRef<{
    questionId: string
    data: { selected_answers: string[]; duration_ms: number }
  } | null>(null)
  const completionKey = useRef(crypto.randomUUID())
  const quizQuery = useQuery({
    queryKey: key,
    queryFn: ({ signal }) => api.quiz(quizId, signal),
    refetchOnWindowFocus: true,
    refetchInterval: (state) =>
      ['pending', 'queued', 'running', 'processing'].includes(state.state.data?.images_status || '')
        ? 4000
        : false,
    refetchIntervalInBackground: false,
  })
  const answerMutation = useMutation({
    mutationFn: ({
      questionId,
      selected,
      duration,
    }: {
      questionId: string
      selected: string[]
      duration: number
    }) => {
      if (
        pendingAnswer.current?.questionId !== questionId ||
        JSON.stringify(pendingAnswer.current.data.selected_answers) !== JSON.stringify(selected)
      )
        pendingAnswer.current = {
          questionId,
          data: { selected_answers: selected, duration_ms: Math.max(0, Math.round(duration)) },
        }
      return api.answer(quizId, questionId, pendingAnswer.current.data)
    },
    onSuccess: (receipt) => {
      client.setQueryData<Quiz>(key, (current) => {
        if (!current || receipt.revision < current.revision) return current
        const records = new Map(
          (current.answer_records || []).map((answer) => [answer.question_id, answer]),
        )
        records.set(receipt.answer_record.question_id, receipt.answer_record)
        return {
          ...current,
          revision: receipt.revision,
          answer_records: [...records.values()],
          answered_count: receipt.answered_count,
          correct_count: receipt.correct_count,
        }
      })
      pendingAnswer.current = null
    },
    onError: (cause) => {
      if (cause instanceof ApiError && cause.status === 409)
        void client.invalidateQueries({ queryKey: key })
    },
  })
  const completion = useMutation({
    mutationFn: () => api.complete(quizId, quizQuery.data!.revision, completionKey.current),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: [identity, 'history'] })
      void client.invalidateQueries({ queryKey: [identity, 'profile'] })
      void client.invalidateQueries({ queryKey: key })
    },
    onError: (cause) => {
      if (cause instanceof ApiError && cause.status === 409)
        void client.invalidateQueries({ queryKey: key })
    },
  })
  return { quizQuery, answerMutation, completion }
}
