import { Navigate, Outlet, Route, Routes, useLocation } from 'react-router-dom'
import { AuthProvider, useAuth } from './AuthProvider'
import { AppShell } from '../components/AppShell'
import { Loading, PageHeading } from '../components/ui'
import { HomePage } from '../pages/HomePage'
import { LoginPage } from '../pages/LoginPage'
import { KnowledgePage } from '../pages/KnowledgePage'
import { QaPage } from '../pages/QaPage'
import { TaskPage } from '../pages/TaskPage'
import { QuizPage } from '../pages/QuizPage'
import { ReportPage } from '../pages/ReportPage'
import { DemoPage } from '../pages/DemoPage'
import { ProfilePage } from '../pages/ProfilePage'
import { PracticePage } from '../pages/PracticePage'
import { PracticeTaskPage } from '../pages/PracticeTaskPage'
import { StudyHomePage } from '../pages/study/StudyHomePage'
import { CourseCreatePage } from '../pages/study/CourseCreatePage'
import { CoursePrintPage } from '../pages/study/CoursePrintPage'
import { CoursePage } from '../pages/study/CoursePage'
import { StudySpacePage } from '../pages/study/StudySpacePage'
import { ReviewPage } from '../pages/study/ReviewPage'
import { ConceptProgressPage } from '../pages/study/ConceptProgressPage'
import { LearningRecordsPage } from '../pages/study/LearningRecordsPage'
import { DatasetsPage } from '../pages/evaluation/DatasetsPage'
import { DatasetEditorPage } from '../pages/evaluation/DatasetEditorPage'
import { RunsPage } from '../pages/evaluation/RunsPage'
import { RunDetailPage } from '../pages/evaluation/RunDetailPage'
import { ComparePage } from '../pages/evaluation/ComparePage'
import { SourcesPage } from '../pages/evaluation/SourcesPage'
import { FeedbackPage } from '../pages/evaluation/FeedbackPage'

function ProtectedRoute({ evaluation = false }: { evaluation?: boolean }) {
  const { status, user } = useAuth()
  const location = useLocation()
  if (status === 'initializing') return <Loading>正在确认登录状态…</Loading>
  if (status !== 'authenticated')
    return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />
  if (evaluation && user?.role !== 'evaluator')
    return <PageHeading title="此页面需要评测权限" description="你的学习与资料仍可正常使用。" />
  return <Outlet />
}
export function AppRoutes() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<AppShell />}>
          <Route index element={<HomePage />} />
          <Route path="demo" element={<DemoPage />} />
          <Route element={<ProtectedRoute />}>
            <Route path="knowledge" element={<KnowledgePage />} />
            <Route path="qa" element={<QaPage />} />
            <Route path="qa/:sessionId" element={<QaPage />} />
            <Route path="study" element={<StudyHomePage />} />
            <Route path="study/courses/new" element={<CourseCreatePage />} />
            <Route path="study/courses/:courseId" element={<CoursePage />} />
            <Route path="study/courses/:courseId/print" element={<CoursePrintPage />} />
            <Route path="study/spaces/:spaceId" element={<StudySpacePage />} />
            <Route path="study/reviews" element={<ReviewPage />} />
            <Route path="study/concepts/:conceptId" element={<ConceptProgressPage />} />
            <Route path="study/wrong-questions" element={<LearningRecordsPage kind="wrong" />} />
            <Route path="study/history" element={<LearningRecordsPage kind="history" />} />
            <Route path="practice/tasks/:taskId" element={<PracticeTaskPage />} />
            <Route path="practice/:practiceId" element={<PracticePage />} />
            <Route path="me" element={<ProfilePage />} />
            <Route path="tasks/:taskId" element={<TaskPage />} />
            <Route path="quizzes/:quizId" element={<QuizPage />} />
            <Route path="quizzes/:quizId/report" element={<ReportPage />} />
            <Route element={<ProtectedRoute evaluation />}>
              <Route path="evaluations" element={<DatasetsPage />} />
              <Route path="evaluations/sources" element={<SourcesPage />} />
              <Route path="evaluations/feedback" element={<FeedbackPage />} />
              <Route
                path="evaluations/datasets/:datasetId/versions/:version"
                element={<DatasetEditorPage />}
              />
              <Route path="evaluations/runs" element={<RunsPage />} />
              <Route path="evaluations/runs/:runId" element={<RunDetailPage />} />
              <Route path="evaluations/compare" element={<ComparePage />} />
            </Route>
          </Route>
          <Route
            path="*"
            element={<PageHeading title="页面不存在" description="请通过导航返回学习首页。" />}
          />
        </Route>
      </Routes>
    </AuthProvider>
  )
}
