/** Generated from contracts/openapi.json. Run npm run api:generate to update. */
export interface paths {
  '/api/v1/auth/bind': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Bind */
    post: operations['bind_api_v1_auth_bind_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/auth/capabilities': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Capabilities */
    get: operations['capabilities_api_v1_auth_capabilities_get']
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/auth/change-password': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Change Password */
    post: operations['change_password_api_v1_auth_change_password_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/auth/link-code': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Link Code */
    post: operations['link_code_api_v1_auth_link_code_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/auth/login': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Login */
    post: operations['login_api_v1_auth_login_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/auth/logout': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Logout */
    post: operations['logout_api_v1_auth_logout_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/auth/recover': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Recover */
    post: operations['recover_api_v1_auth_recover_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/auth/register': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Register */
    post: operations['register_api_v1_auth_register_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/auth/session': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Session */
    get: operations['session_api_v1_auth_session_get']
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/eval/compare': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Compare */
    get: operations['compare_api_v1_eval_compare_get']
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/eval/datasets': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** List Datasets */
    get: operations['list_datasets_api_v1_eval_datasets_get']
    put?: never
    /** Create Dataset */
    post: operations['create_dataset_api_v1_eval_datasets_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/eval/datasets/{dataset_id}/versions/{version}': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Get Dataset */
    get: operations['get_dataset_api_v1_eval_datasets__dataset_id__versions__version__get']
    put?: never
    post?: never
    /** Revoke Dataset */
    delete: operations['revoke_dataset_api_v1_eval_datasets__dataset_id__versions__version__delete']
    options?: never
    head?: never
    /** Edit Dataset */
    patch: operations['edit_dataset_api_v1_eval_datasets__dataset_id__versions__version__patch']
    trace?: never
  }
  '/api/v1/eval/datasets/{dataset_id}/versions/{version}/freeze': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Freeze Dataset */
    post: operations['freeze_dataset_api_v1_eval_datasets__dataset_id__versions__version__freeze_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/eval/datasets/{dataset_id}/versions/{version}/samples/{sample_id}/review': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Review Sample */
    post: operations['review_sample_api_v1_eval_datasets__dataset_id__versions__version__samples__sample_id__review_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/eval/documents': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Eval List */
    get: operations['eval_list_api_v1_eval_documents_get']
    put?: never
    /** Eval Upload */
    post: operations['eval_upload_api_v1_eval_documents_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/eval/documents/{doc_id}': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Eval Document */
    get: operations['eval_document_api_v1_eval_documents__doc_id__get']
    put?: never
    post?: never
    /** Eval Delete */
    delete: operations['eval_delete_api_v1_eval_documents__doc_id__delete']
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/eval/documents/{doc_id}/reindex': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Eval Reindex */
    post: operations['eval_reindex_api_v1_eval_documents__doc_id__reindex_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/eval/documents/{doc_id}/source': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Eval Source */
    get: operations['eval_source_api_v1_eval_documents__doc_id__source_get']
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/eval/feedback': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** List Feedback */
    get: operations['list_feedback_api_v1_eval_feedback_get']
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/eval/feedback/{feedback_id}/promote': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Promote */
    post: operations['promote_api_v1_eval_feedback__feedback_id__promote_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/eval/feedback/{feedback_id}/review': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    /** Review */
    put: operations['review_api_v1_eval_feedback__feedback_id__review_put']
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/eval/judges': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Judges */
    get: operations['judges_api_v1_eval_judges_get']
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/eval/pipelines': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Pipelines */
    get: operations['pipelines_api_v1_eval_pipelines_get']
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/eval/runs': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** List Runs */
    get: operations['list_runs_api_v1_eval_runs_get']
    put?: never
    /** Create Run */
    post: operations['create_run_api_v1_eval_runs_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/eval/runs/estimate': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Estimate Run */
    get: operations['estimate_run_api_v1_eval_runs_estimate_get']
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/eval/runs/{run_id}': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Get Run */
    get: operations['get_run_api_v1_eval_runs__run_id__get']
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/eval/runs/{run_id}/cancel': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Cancel Run */
    post: operations['cancel_run_api_v1_eval_runs__run_id__cancel_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/eval/runs/{run_id}/export': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Export Run */
    get: operations['export_run_api_v1_eval_runs__run_id__export_get']
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/eval/runs/{run_id}/results': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Get Results */
    get: operations['get_results_api_v1_eval_runs__run_id__results_get']
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/eval/runs/{run_id}/results/{result_id}/review': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    /** Review Result */
    put: operations['review_result_api_v1_eval_runs__run_id__results__result_id__review_put']
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/eval/runs/{run_id}/resume': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Resume Run */
    post: operations['resume_run_api_v1_eval_runs__run_id__resume_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/health': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Health Check */
    get: operations['health_check_api_v1_health_get']
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/internal/eval/scoring/claim': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Claim */
    post: operations['claim_api_v1_internal_eval_scoring_claim_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/internal/eval/scoring/{result_id}/calls': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Calls */
    post: operations['calls_api_v1_internal_eval_scoring__result_id__calls_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/internal/eval/scoring/{result_id}/complete': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Complete */
    post: operations['complete_api_v1_internal_eval_scoring__result_id__complete_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/internal/eval/scoring/{result_id}/fail': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Fail */
    post: operations['fail_api_v1_internal_eval_scoring__result_id__fail_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/internal/eval/scoring/{result_id}/heartbeat': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Heartbeat */
    post: operations['heartbeat_api_v1_internal_eval_scoring__result_id__heartbeat_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/knowledge/documents': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Listing */
    get: operations['listing_api_v1_knowledge_documents_get']
    put?: never
    /** Upload */
    post: operations['upload_api_v1_knowledge_documents_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/knowledge/documents/{doc_id}': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Get Document */
    get: operations['get_document_api_v1_knowledge_documents__doc_id__get']
    put?: never
    post?: never
    /** Delete */
    delete: operations['delete_api_v1_knowledge_documents__doc_id__delete']
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/knowledge/documents/{doc_id}/reindex': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Reindex */
    post: operations['reindex_api_v1_knowledge_documents__doc_id__reindex_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/knowledge/documents/{doc_id}/source': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Source */
    get: operations['source_api_v1_knowledge_documents__doc_id__source_get']
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/knowledge/documents/{doc_id}/versions': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Version */
    post: operations['version_api_v1_knowledge_documents__doc_id__versions_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/practice/attempts/{attempt_id}': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Attempt */
    get: operations['attempt_api_v1_practice_attempts__attempt_id__get']
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/practice/attempts/{attempt_id}/retry-grading': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Retry Grading */
    post: operations['retry_grading_api_v1_practice_attempts__attempt_id__retry_grading_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/practice/attempts/{attempt_id}/review': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Review */
    post: operations['review_api_v1_practice_attempts__attempt_id__review_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/practice/attempts/{attempt_id}/review-context': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Review Context */
    get: operations['review_context_api_v1_practice_attempts__attempt_id__review_context_get']
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/practice/attempts/{attempt_id}/self-review': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Self Review */
    post: operations['self_review_api_v1_practice_attempts__attempt_id__self_review_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/practice/cost-preview': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Cost Preview */
    post: operations['cost_preview_api_v1_practice_cost_preview_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/practice/generate/async': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Generate */
    post: operations['generate_api_v1_practice_generate_async_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/practice/review-jobs': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Review Job */
    post: operations['review_job_api_v1_practice_review_jobs_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/practice/tasks/{task_id}': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Task */
    get: operations['task_api_v1_practice_tasks__task_id__get']
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/practice/tasks/{task_id}/cancel': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Cancel */
    post: operations['cancel_api_v1_practice_tasks__task_id__cancel_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/practice/{practice_id}': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Practice */
    get: operations['practice_api_v1_practice__practice_id__get']
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/practice/{practice_id}/complete': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Complete */
    post: operations['complete_api_v1_practice__practice_id__complete_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/practice/{practice_id}/questions/{question_id}/attempts': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Submit Answer */
    post: operations['submit_answer_api_v1_practice__practice_id__questions__question_id__attempts_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/practice/{practice_id}/questions/{question_id}/evidence/{evidence_id}': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Evidence */
    get: operations['evidence_api_v1_practice__practice_id__questions__question_id__evidence__evidence_id__get']
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/practice/{practice_id}/questions/{question_id}/help': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Help Used */
    post: operations['help_used_api_v1_practice__practice_id__questions__question_id__help_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/qa/answers/{answer_id}/evidence/{evidence_id}': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Evidence */
    get: operations['evidence_api_v1_qa_answers__answer_id__evidence__evidence_id__get']
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/qa/answers/{answer_id}/feedback': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Feedback */
    post: operations['feedback_api_v1_qa_answers__answer_id__feedback_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/qa/sessions': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Sessions */
    get: operations['sessions_api_v1_qa_sessions_get']
    put?: never
    /** Create Session */
    post: operations['create_session_api_v1_qa_sessions_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/qa/sessions/{session_id}': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Session */
    get: operations['session_api_v1_qa_sessions__session_id__get']
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/qa/sessions/{session_id}/messages': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Messages */
    get: operations['messages_api_v1_qa_sessions__session_id__messages_get']
    put?: never
    /** Create Message */
    post: operations['create_message_api_v1_qa_sessions__session_id__messages_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/qa/sessions/{session_id}/scope': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    /** Scope */
    patch: operations['scope_api_v1_qa_sessions__session_id__scope_patch']
    trace?: never
  }
  '/api/v1/qa/tasks/{task_id}': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Task */
    get: operations['task_api_v1_qa_tasks__task_id__get']
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/qa/tasks/{task_id}/cancel': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Cancel */
    post: operations['cancel_api_v1_qa_tasks__task_id__cancel_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/quiz/generate': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Legacy Generate */
    post: operations['legacy_generate_api_v1_quiz_generate_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/quiz/generate/async': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Create */
    post: operations['create_api_v1_quiz_generate_async_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/quiz/task/{task_id}': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Get Task */
    get: operations['get_task_api_v1_quiz_task__task_id__get']
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/quiz/task/{task_id}/cancel': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Cancel Task */
    post: operations['cancel_task_api_v1_quiz_task__task_id__cancel_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/quiz/{quiz_id}/answers/{question_id}': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    /** Answer */
    put: operations['answer_api_v1_quiz__quiz_id__answers__question_id__put']
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/quiz/{quiz_id}/complete': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Complete */
    post: operations['complete_api_v1_quiz__quiz_id__complete_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/quiz/{quiz_id}/evidence/{evidence_id}': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Evidence */
    get: operations['evidence_api_v1_quiz__quiz_id__evidence__evidence_id__get']
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/quiz/{quiz_id}/feedback': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Create */
    post: operations['create_api_v1_quiz__quiz_id__feedback_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/ready': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Readiness */
    get: operations['readiness_api_v1_ready_get']
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/report/generate': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Legacy Report */
    post: operations['legacy_report_api_v1_report_generate_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/report/{quiz_id}': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Get Report */
    get: operations['get_report_api_v1_report__quiz_id__get']
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/report/{quiz_id}/retry': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Retry */
    post: operations['retry_api_v1_report__quiz_id__retry_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/study/concepts/{concept_id}': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    /** Update Concept */
    patch: operations['update_concept_api_v1_study_concepts__concept_id__patch']
    trace?: never
  }
  '/api/v1/study/concepts/{concept_id}/progress': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Concept Progress */
    get: operations['concept_progress_api_v1_study_concepts__concept_id__progress_get']
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/study/goals/{goal_id}': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    /** Update Goal */
    patch: operations['update_goal_api_v1_study_goals__goal_id__patch']
    trace?: never
  }
  '/api/v1/study/goals/{goal_id}/units': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** List Units */
    get: operations['list_units_api_v1_study_goals__goal_id__units_get']
    put?: never
    /** Create Unit */
    post: operations['create_unit_api_v1_study_goals__goal_id__units_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/study/goals/{goal_id}/units/order': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    /** Reorder Units */
    patch: operations['reorder_units_api_v1_study_goals__goal_id__units_order_patch']
    trace?: never
  }
  '/api/v1/study/history': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Learning History */
    get: operations['learning_history_api_v1_study_history_get']
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/study/qa-answers/{answer_id}/practice-context': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Practice Context */
    get: operations['practice_context_api_v1_study_qa_answers__answer_id__practice_context_get']
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/study/quiz-jobs/from-qa': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Create Quiz From Qa */
    post: operations['create_quiz_from_qa_api_v1_study_quiz_jobs_from_qa_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/study/review-quiz-jobs': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Start Review Quiz */
    post: operations['start_review_quiz_api_v1_study_review_quiz_jobs_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/study/reviews': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Due Reviews */
    get: operations['due_reviews_api_v1_study_reviews_get']
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/study/reviews/{review_id}': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    /** Update Review */
    patch: operations['update_review_api_v1_study_reviews__review_id__patch']
    trace?: never
  }
  '/api/v1/study/spaces': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** List Spaces */
    get: operations['list_spaces_api_v1_study_spaces_get']
    put?: never
    /** Create Space */
    post: operations['create_space_api_v1_study_spaces_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/study/spaces/{space_id}': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Get Space */
    get: operations['get_space_api_v1_study_spaces__space_id__get']
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    /** Update Space */
    patch: operations['update_space_api_v1_study_spaces__space_id__patch']
    trace?: never
  }
  '/api/v1/study/spaces/{space_id}/concepts': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** List Concepts */
    get: operations['list_concepts_api_v1_study_spaces__space_id__concepts_get']
    put?: never
    /** Create Concept */
    post: operations['create_concept_api_v1_study_spaces__space_id__concepts_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/study/spaces/{space_id}/goals': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** List Goals */
    get: operations['list_goals_api_v1_study_spaces__space_id__goals_get']
    put?: never
    /** Create Goal */
    post: operations['create_goal_api_v1_study_spaces__space_id__goals_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/study/spaces/{space_id}/scope': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    /** Change Scope */
    patch: operations['change_scope_api_v1_study_spaces__space_id__scope_patch']
    trace?: never
  }
  '/api/v1/study/spaces/{space_id}/scopes/{scope_revision}': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Get Scope */
    get: operations['get_scope_api_v1_study_spaces__space_id__scopes__scope_revision__get']
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/study/units/{unit_id}': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    /** Update Unit */
    patch: operations['update_unit_api_v1_study_units__unit_id__patch']
    trace?: never
  }
  '/api/v1/study/wrong-questions': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Wrong Questions */
    get: operations['wrong_questions_api_v1_study_wrong_questions_get']
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/user/assets/{asset_id}': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Get Asset */
    get: operations['get_asset_api_v1_user_assets__asset_id__get']
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/user/avatar': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Upload Avatar */
    post: operations['upload_avatar_api_v1_user_avatar_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/user/login': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    get?: never
    put?: never
    /** Login */
    post: operations['login_api_v1_user_login_post']
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/user/profile': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Get Profile */
    get: operations['get_profile_api_v1_user_profile_get']
    /** Update Profile */
    put: operations['update_profile_api_v1_user_profile_put']
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/user/quizzes': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Get Quiz List */
    get: operations['get_quiz_list_api_v1_user_quizzes_get']
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
  '/api/v1/user/quizzes/{quiz_id}': {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    /** Get Quiz Detail */
    get: operations['get_quiz_detail_api_v1_user_quizzes__quiz_id__get']
    put?: never
    post?: never
    delete?: never
    options?: never
    head?: never
    patch?: never
    trace?: never
  }
}
export type webhooks = Record<string, never>
export interface components {
  schemas: {
    /** AnswerBlock */
    AnswerBlock: {
      /** Block Id */
      block_id: string
      /** Citation Refs */
      citation_refs?: string[]
      /**
       * Kind
       * @default fact
       * @enum {string}
       */
      kind: 'fact' | 'notice'
      /** Text */
      text: string
    }
    /** AnswerBody */
    AnswerBody: {
      /** Duration Ms */
      duration_ms: number
      /** Selected Answers */
      selected_answers: string[]
    }
    /** AnswerGradingEvalArtifact */
    AnswerGradingEvalArtifact: {
      /**
       * @description discriminator enum property added by openapi-typescript
       * @enum {string}
       */
      case_type: 'answer_grading'
      /**
       * Error Code
       * @default null
       */
      error_code: string | null
      /** @default null */
      grade: components['schemas']['GradeArtifact'] | null
      /**
       * Repeat Index
       * @default 0
       */
      repeat_index: number
      /** Run Id */
      run_id: string
      /** Sample Id */
      sample_id: string
      /**
       * Schema Version
       * @default 1
       * @constant
       */
      schema_version: '1'
      /**
       * Status
       * @enum {string}
       */
      status: 'completed' | 'failed' | 'cancelled' | 'timeout'
      usage?: components['schemas']['LearningEvaluationUsage']
    }
    /** AnswerGradingSample */
    AnswerGradingSample: {
      /** Annotation */
      annotation?: {
        [key: string]: unknown
      }
      /** Answer */
      answer:
        | components['schemas']['ClozeAnswer']
        | components['schemas']['NumericAnswer']
        | components['schemas']['ShortAnswer']
      /**
       * @description discriminator enum property added by openapi-typescript
       * @enum {string}
       */
      case_type: 'answer_grading'
      /**
       * Expected Error Code
       * @default null
       */
      expected_error_code: string | null
      /**
       * Expected Grade Status
       * @enum {string}
       */
      expected_grade_status: 'graded' | 'needs_review' | 'failed' | 'cancelled'
      /** Family Ids */
      family_ids?: string[]
      /** Gold Evidence Groups */
      gold_evidence_groups?: {
        [key: string]: unknown
      }[]
      /** Question */
      question:
        | components['schemas']['ClozeQuestion']
        | components['schemas']['NumericQuestion']
        | components['schemas']['ShortAnswerQuestion']
      /**
       * Question Type
       * @enum {string}
       */
      question_type: 'cloze' | 'numeric' | 'short_answer'
      /** Question Version */
      question_version: string
      /** @default null */
      reference_grade: components['schemas']['ReferenceGrade'] | null
      /** Response Hash */
      response_hash: string
      /** Rubric Hash */
      rubric_hash: string
      /** Sample Id */
      sample_id: string
      /**
       * Schema Version
       * @default 1
       */
      schema_version: string
      /** Source Refs */
      source_refs: {
        [key: string]: unknown
      }[]
      /**
       * Split
       * @enum {string}
       */
      split: 'dev' | 'judge_calibration' | 'locked_test'
      /** Tags */
      tags?: string[]
    } & {
      [key: string]: unknown
    }
    /** AnswerReceipt */
    AnswerReceipt: {
      answer_record: components['schemas']['AnswerView']
      /** Answered Count */
      answered_count: number
      /** Correct Count */
      correct_count: number
      /** Revision */
      revision: number
    }
    /** AnswerRecord */
    AnswerRecord: {
      /** Duration Ms */
      duration_ms: number
      /** Is Correct */
      is_correct: boolean
      /** Question Id */
      question_id: string
      /** Selected Answers */
      selected_answers: string[]
    }
    /** AnswerView */
    AnswerView: {
      /** Citation Refs */
      citation_refs?: string[]
      /** Correct Answers */
      correct_answers: string[]
      /** Duration Ms */
      duration_ms: number
      /** Explanation */
      explanation: string
      /** Is Correct */
      is_correct: boolean
      /** Question Id */
      question_id: string
      /** Selected Answers */
      selected_answers: string[]
    }
    /** ApiResponse[AnswerReceipt] */
    ApiResponse_AnswerReceipt_: {
      /**
       * Code
       * @default 0
       */
      code: number
      data?: components['schemas']['AnswerReceipt'] | null
      /** Error Code */
      error_code?: string | null
      /**
       * Message
       * @default ok
       */
      message: string
    }
    /** ApiResponse[AssessmentRef] */
    ApiResponse_AssessmentRef_: {
      /**
       * Code
       * @default 0
       */
      code: number
      data?: components['schemas']['AssessmentRef'] | null
      /** Error Code */
      error_code?: string | null
      /**
       * Message
       * @default ok
       */
      message: string
    }
    /** ApiResponse[AuthCapabilitiesView] */
    ApiResponse_AuthCapabilitiesView_: {
      /**
       * Code
       * @default 0
       */
      code: number
      data?: components['schemas']['AuthCapabilitiesView'] | null
      /** Error Code */
      error_code?: string | null
      /**
       * Message
       * @default ok
       */
      message: string
    }
    /** ApiResponse[AvatarUploadResponse] */
    ApiResponse_AvatarUploadResponse_: {
      /**
       * Code
       * @default 0
       */
      code: number
      data?: components['schemas']['AvatarUploadResponse'] | null
      /** Error Code */
      error_code?: string | null
      /**
       * Message
       * @default ok
       */
      message: string
    }
    /** ApiResponse[CompletionReceipt] */
    ApiResponse_CompletionReceipt_: {
      /**
       * Code
       * @default 0
       */
      code: number
      data?: components['schemas']['CompletionReceipt'] | null
      /** Error Code */
      error_code?: string | null
      /**
       * Message
       * @default ok
       */
      message: string
    }
    /** ApiResponse[DatasetList] */
    ApiResponse_DatasetList_: {
      /**
       * Code
       * @default 0
       */
      code: number
      data?: components['schemas']['DatasetList'] | null
      /** Error Code */
      error_code?: string | null
      /**
       * Message
       * @default ok
       */
      message: string
    }
    /** ApiResponse[DatasetView] */
    ApiResponse_DatasetView_: {
      /**
       * Code
       * @default 0
       */
      code: number
      data?: components['schemas']['DatasetView'] | null
      /** Error Code */
      error_code?: string | null
      /**
       * Message
       * @default ok
       */
      message: string
    }
    /** ApiResponse[DocumentDeletionView] */
    ApiResponse_DocumentDeletionView_: {
      /**
       * Code
       * @default 0
       */
      code: number
      data?: components['schemas']['DocumentDeletionView'] | null
      /** Error Code */
      error_code?: string | null
      /**
       * Message
       * @default ok
       */
      message: string
    }
    /** ApiResponse[DocumentEvidence] */
    ApiResponse_DocumentEvidence_: {
      /**
       * Code
       * @default 0
       */
      code: number
      data?: components['schemas']['DocumentEvidence'] | null
      /** Error Code */
      error_code?: string | null
      /**
       * Message
       * @default ok
       */
      message: string
    }
    /** ApiResponse[DocumentList] */
    ApiResponse_DocumentList_: {
      /**
       * Code
       * @default 0
       */
      code: number
      data?: components['schemas']['DocumentList'] | null
      /** Error Code */
      error_code?: string | null
      /**
       * Message
       * @default ok
       */
      message: string
    }
    /** ApiResponse[DocumentView] */
    ApiResponse_DocumentView_: {
      /**
       * Code
       * @default 0
       */
      code: number
      data?: components['schemas']['DocumentView'] | null
      /** Error Code */
      error_code?: string | null
      /**
       * Message
       * @default ok
       */
      message: string
    }
    /** ApiResponse[FeedbackList] */
    ApiResponse_FeedbackList_: {
      /**
       * Code
       * @default 0
       */
      code: number
      data?: components['schemas']['FeedbackList'] | null
      /** Error Code */
      error_code?: string | null
      /**
       * Message
       * @default ok
       */
      message: string
    }
    /** ApiResponse[FeedbackView] */
    ApiResponse_FeedbackView_: {
      /**
       * Code
       * @default 0
       */
      code: number
      data?: components['schemas']['FeedbackView'] | null
      /** Error Code */
      error_code?: string | null
      /**
       * Message
       * @default ok
       */
      message: string
    }
    /** ApiResponse[JudgeProfileList] */
    ApiResponse_JudgeProfileList_: {
      /**
       * Code
       * @default 0
       */
      code: number
      data?: components['schemas']['JudgeProfileList'] | null
      /** Error Code */
      error_code?: string | null
      /**
       * Message
       * @default ok
       */
      message: string
    }
    /** ApiResponse[LoginResponse] */
    ApiResponse_LoginResponse_: {
      /**
       * Code
       * @default 0
       */
      code: number
      data?: components['schemas']['LoginResponse'] | null
      /** Error Code */
      error_code?: string | null
      /**
       * Message
       * @default ok
       */
      message: string
    }
    /** ApiResponse[NoneType] */
    ApiResponse_NoneType_: {
      /**
       * Code
       * @default 0
       */
      code: number
      /** Data */
      data?: null
      /** Error Code */
      error_code?: string | null
      /**
       * Message
       * @default ok
       */
      message: string
    }
    /** ApiResponse[PracticeAttemptView] */
    ApiResponse_PracticeAttemptView_: {
      /**
       * Code
       * @default 0
       */
      code: number
      data?: components['schemas']['PracticeAttemptView'] | null
      /** Error Code */
      error_code?: string | null
      /**
       * Message
       * @default ok
       */
      message: string
    }
    /** ApiResponse[PracticeCompletionReceipt] */
    ApiResponse_PracticeCompletionReceipt_: {
      /**
       * Code
       * @default 0
       */
      code: number
      data?: components['schemas']['PracticeCompletionReceipt'] | null
      /** Error Code */
      error_code?: string | null
      /**
       * Message
       * @default ok
       */
      message: string
    }
    /** ApiResponse[PracticeCostPreview] */
    ApiResponse_PracticeCostPreview_: {
      /**
       * Code
       * @default 0
       */
      code: number
      data?: components['schemas']['PracticeCostPreview'] | null
      /** Error Code */
      error_code?: string | null
      /**
       * Message
       * @default ok
       */
      message: string
    }
    /** ApiResponse[PracticeHelpView] */
    ApiResponse_PracticeHelpView_: {
      /**
       * Code
       * @default 0
       */
      code: number
      data?: components['schemas']['PracticeHelpView'] | null
      /** Error Code */
      error_code?: string | null
      /**
       * Message
       * @default ok
       */
      message: string
    }
    /** ApiResponse[PracticeReviewContext] */
    ApiResponse_PracticeReviewContext_: {
      /**
       * Code
       * @default 0
       */
      code: number
      data?: components['schemas']['PracticeReviewContext'] | null
      /** Error Code */
      error_code?: string | null
      /**
       * Message
       * @default ok
       */
      message: string
    }
    /** ApiResponse[PracticeSelfReviewReceipt] */
    ApiResponse_PracticeSelfReviewReceipt_: {
      /**
       * Code
       * @default 0
       */
      code: number
      data?: components['schemas']['PracticeSelfReviewReceipt'] | null
      /** Error Code */
      error_code?: string | null
      /**
       * Message
       * @default ok
       */
      message: string
    }
    /** ApiResponse[PracticeSubmissionReceipt] */
    ApiResponse_PracticeSubmissionReceipt_: {
      /**
       * Code
       * @default 0
       */
      code: number
      data?: components['schemas']['PracticeSubmissionReceipt'] | null
      /** Error Code */
      error_code?: string | null
      /**
       * Message
       * @default ok
       */
      message: string
    }
    /** ApiResponse[PracticeTaskView] */
    ApiResponse_PracticeTaskView_: {
      /**
       * Code
       * @default 0
       */
      code: number
      data?: components['schemas']['PracticeTaskView'] | null
      /** Error Code */
      error_code?: string | null
      /**
       * Message
       * @default ok
       */
      message: string
    }
    /** ApiResponse[PracticeView] */
    ApiResponse_PracticeView_: {
      /**
       * Code
       * @default 0
       */
      code: number
      data?: components['schemas']['PracticeView'] | null
      /** Error Code */
      error_code?: string | null
      /**
       * Message
       * @default ok
       */
      message: string
    }
    /** ApiResponse[PromotionView] */
    ApiResponse_PromotionView_: {
      /**
       * Code
       * @default 0
       */
      code: number
      data?: components['schemas']['PromotionView'] | null
      /** Error Code */
      error_code?: string | null
      /**
       * Message
       * @default ok
       */
      message: string
    }
    /** ApiResponse[PublicPracticeEvidence] */
    ApiResponse_PublicPracticeEvidence_: {
      /**
       * Code
       * @default 0
       */
      code: number
      data?: components['schemas']['PublicPracticeEvidence'] | null
      /** Error Code */
      error_code?: string | null
      /**
       * Message
       * @default ok
       */
      message: string
    }
    /** ApiResponse[QaFeedbackView] */
    ApiResponse_QaFeedbackView_: {
      /**
       * Code
       * @default 0
       */
      code: number
      data?: components['schemas']['QaFeedbackView'] | null
      /** Error Code */
      error_code?: string | null
      /**
       * Message
       * @default ok
       */
      message: string
    }
    /** ApiResponse[QaMessageList] */
    ApiResponse_QaMessageList_: {
      /**
       * Code
       * @default 0
       */
      code: number
      data?: components['schemas']['QaMessageList'] | null
      /** Error Code */
      error_code?: string | null
      /**
       * Message
       * @default ok
       */
      message: string
    }
    /** ApiResponse[QaSessionList] */
    ApiResponse_QaSessionList_: {
      /**
       * Code
       * @default 0
       */
      code: number
      data?: components['schemas']['QaSessionList'] | null
      /** Error Code */
      error_code?: string | null
      /**
       * Message
       * @default ok
       */
      message: string
    }
    /** ApiResponse[QaSessionView] */
    ApiResponse_QaSessionView_: {
      /**
       * Code
       * @default 0
       */
      code: number
      data?: components['schemas']['QaSessionView'] | null
      /** Error Code */
      error_code?: string | null
      /**
       * Message
       * @default ok
       */
      message: string
    }
    /** ApiResponse[QaTaskView] */
    ApiResponse_QaTaskView_: {
      /**
       * Code
       * @default 0
       */
      code: number
      data?: components['schemas']['QaTaskView'] | null
      /** Error Code */
      error_code?: string | null
      /**
       * Message
       * @default ok
       */
      message: string
    }
    /** ApiResponse[QuizHistoryList] */
    ApiResponse_QuizHistoryList_: {
      /**
       * Code
       * @default 0
       */
      code: number
      data?: components['schemas']['QuizHistoryList'] | null
      /** Error Code */
      error_code?: string | null
      /**
       * Message
       * @default ok
       */
      message: string
    }
    /** ApiResponse[QuizView] */
    ApiResponse_QuizView_: {
      /**
       * Code
       * @default 0
       */
      code: number
      data?: components['schemas']['QuizView'] | null
      /** Error Code */
      error_code?: string | null
      /**
       * Message
       * @default ok
       */
      message: string
    }
    /** ApiResponse[ReportRetryView] */
    ApiResponse_ReportRetryView_: {
      /**
       * Code
       * @default 0
       */
      code: number
      data?: components['schemas']['ReportRetryView'] | null
      /** Error Code */
      error_code?: string | null
      /**
       * Message
       * @default ok
       */
      message: string
    }
    /** ApiResponse[ReportView] */
    ApiResponse_ReportView_: {
      /**
       * Code
       * @default 0
       */
      code: number
      data?: components['schemas']['ReportView'] | null
      /** Error Code */
      error_code?: string | null
      /**
       * Message
       * @default ok
       */
      message: string
    }
    /** ApiResponse[ResultList] */
    ApiResponse_ResultList_: {
      /**
       * Code
       * @default 0
       */
      code: number
      data?: components['schemas']['ResultList'] | null
      /** Error Code */
      error_code?: string | null
      /**
       * Message
       * @default ok
       */
      message: string
    }
    /** ApiResponse[RunCostPreview] */
    ApiResponse_RunCostPreview_: {
      /**
       * Code
       * @default 0
       */
      code: number
      data?: components['schemas']['RunCostPreview'] | null
      /** Error Code */
      error_code?: string | null
      /**
       * Message
       * @default ok
       */
      message: string
    }
    /** ApiResponse[RunList] */
    ApiResponse_RunList_: {
      /**
       * Code
       * @default 0
       */
      code: number
      data?: components['schemas']['RunList'] | null
      /** Error Code */
      error_code?: string | null
      /**
       * Message
       * @default ok
       */
      message: string
    }
    /** ApiResponse[RunView] */
    ApiResponse_RunView_: {
      /**
       * Code
       * @default 0
       */
      code: number
      data?: components['schemas']['RunView'] | null
      /** Error Code */
      error_code?: string | null
      /**
       * Message
       * @default ok
       */
      message: string
    }
    /** ApiResponse[SessionView] */
    ApiResponse_SessionView_: {
      /**
       * Code
       * @default 0
       */
      code: number
      data?: components['schemas']['SessionView'] | null
      /** Error Code */
      error_code?: string | null
      /**
       * Message
       * @default ok
       */
      message: string
    }
    /** ApiResponse[SourceExcerptView] */
    ApiResponse_SourceExcerptView_: {
      /**
       * Code
       * @default 0
       */
      code: number
      data?: components['schemas']['SourceExcerptView'] | null
      /** Error Code */
      error_code?: string | null
      /**
       * Message
       * @default ok
       */
      message: string
    }
    /** ApiResponse[StudyConceptList] */
    ApiResponse_StudyConceptList_: {
      /**
       * Code
       * @default 0
       */
      code: number
      data?: components['schemas']['StudyConceptList'] | null
      /** Error Code */
      error_code?: string | null
      /**
       * Message
       * @default ok
       */
      message: string
    }
    /** ApiResponse[StudyConceptProgressView] */
    ApiResponse_StudyConceptProgressView_: {
      /**
       * Code
       * @default 0
       */
      code: number
      data?: components['schemas']['StudyConceptProgressView'] | null
      /** Error Code */
      error_code?: string | null
      /**
       * Message
       * @default ok
       */
      message: string
    }
    /** ApiResponse[StudyConceptView] */
    ApiResponse_StudyConceptView_: {
      /**
       * Code
       * @default 0
       */
      code: number
      data?: components['schemas']['StudyConceptView'] | null
      /** Error Code */
      error_code?: string | null
      /**
       * Message
       * @default ok
       */
      message: string
    }
    /** ApiResponse[StudyGoalList] */
    ApiResponse_StudyGoalList_: {
      /**
       * Code
       * @default 0
       */
      code: number
      data?: components['schemas']['StudyGoalList'] | null
      /** Error Code */
      error_code?: string | null
      /**
       * Message
       * @default ok
       */
      message: string
    }
    /** ApiResponse[StudyGoalView] */
    ApiResponse_StudyGoalView_: {
      /**
       * Code
       * @default 0
       */
      code: number
      data?: components['schemas']['StudyGoalView'] | null
      /** Error Code */
      error_code?: string | null
      /**
       * Message
       * @default ok
       */
      message: string
    }
    /** ApiResponse[StudyHistoryList] */
    ApiResponse_StudyHistoryList_: {
      /**
       * Code
       * @default 0
       */
      code: number
      data?: components['schemas']['StudyHistoryList'] | null
      /** Error Code */
      error_code?: string | null
      /**
       * Message
       * @default ok
       */
      message: string
    }
    /** ApiResponse[StudyQaPracticeContextView] */
    ApiResponse_StudyQaPracticeContextView_: {
      /**
       * Code
       * @default 0
       */
      code: number
      data?: components['schemas']['StudyQaPracticeContextView'] | null
      /** Error Code */
      error_code?: string | null
      /**
       * Message
       * @default ok
       */
      message: string
    }
    /** ApiResponse[StudyReviewList] */
    ApiResponse_StudyReviewList_: {
      /**
       * Code
       * @default 0
       */
      code: number
      data?: components['schemas']['StudyReviewList'] | null
      /** Error Code */
      error_code?: string | null
      /**
       * Message
       * @default ok
       */
      message: string
    }
    /** ApiResponse[StudyReviewView] */
    ApiResponse_StudyReviewView_: {
      /**
       * Code
       * @default 0
       */
      code: number
      data?: components['schemas']['StudyReviewView'] | null
      /** Error Code */
      error_code?: string | null
      /**
       * Message
       * @default ok
       */
      message: string
    }
    /** ApiResponse[StudyScopeView] */
    ApiResponse_StudyScopeView_: {
      /**
       * Code
       * @default 0
       */
      code: number
      data?: components['schemas']['StudyScopeView'] | null
      /** Error Code */
      error_code?: string | null
      /**
       * Message
       * @default ok
       */
      message: string
    }
    /** ApiResponse[StudySpaceList] */
    ApiResponse_StudySpaceList_: {
      /**
       * Code
       * @default 0
       */
      code: number
      data?: components['schemas']['StudySpaceList'] | null
      /** Error Code */
      error_code?: string | null
      /**
       * Message
       * @default ok
       */
      message: string
    }
    /** ApiResponse[StudySpaceView] */
    ApiResponse_StudySpaceView_: {
      /**
       * Code
       * @default 0
       */
      code: number
      data?: components['schemas']['StudySpaceView'] | null
      /** Error Code */
      error_code?: string | null
      /**
       * Message
       * @default ok
       */
      message: string
    }
    /** ApiResponse[StudyUnitList] */
    ApiResponse_StudyUnitList_: {
      /**
       * Code
       * @default 0
       */
      code: number
      data?: components['schemas']['StudyUnitList'] | null
      /** Error Code */
      error_code?: string | null
      /**
       * Message
       * @default ok
       */
      message: string
    }
    /** ApiResponse[StudyUnitView] */
    ApiResponse_StudyUnitView_: {
      /**
       * Code
       * @default 0
       */
      code: number
      data?: components['schemas']['StudyUnitView'] | null
      /** Error Code */
      error_code?: string | null
      /**
       * Message
       * @default ok
       */
      message: string
    }
    /** ApiResponse[StudyWrongQuestionList] */
    ApiResponse_StudyWrongQuestionList_: {
      /**
       * Code
       * @default 0
       */
      code: number
      data?: components['schemas']['StudyWrongQuestionList'] | null
      /** Error Code */
      error_code?: string | null
      /**
       * Message
       * @default ok
       */
      message: string
    }
    /** ApiResponse[TaskView] */
    ApiResponse_TaskView_: {
      /**
       * Code
       * @default 0
       */
      code: number
      data?: components['schemas']['TaskView'] | null
      /** Error Code */
      error_code?: string | null
      /**
       * Message
       * @default ok
       */
      message: string
    }
    /** ApiResponse[Union[DocumentEvidence, PublicWebEvidence]] */
    ApiResponse_Union_DocumentEvidence__PublicWebEvidence__: {
      /**
       * Code
       * @default 0
       */
      code: number
      /** Data */
      data?:
        | components['schemas']['DocumentEvidence']
        | components['schemas']['PublicWebEvidence']
        | null
      /** Error Code */
      error_code?: string | null
      /**
       * Message
       * @default ok
       */
      message: string
    }
    /** ApiResponse[Union[QuizView, TaskView]] */
    ApiResponse_Union_QuizView__TaskView__: {
      /**
       * Code
       * @default 0
       */
      code: number
      /** Data */
      data?: components['schemas']['QuizView'] | components['schemas']['TaskView'] | null
      /** Error Code */
      error_code?: string | null
      /**
       * Message
       * @default ok
       */
      message: string
    }
    /** ApiResponse[UserProfile] */
    ApiResponse_UserProfile_: {
      /**
       * Code
       * @default 0
       */
      code: number
      data?: components['schemas']['UserProfile'] | null
      /** Error Code */
      error_code?: string | null
      /**
       * Message
       * @default ok
       */
      message: string
    }
    /** ApiResponse[dict] */
    ApiResponse_dict_: {
      /**
       * Code
       * @default 0
       */
      code: number
      /** Data */
      data?: {
        [key: string]: unknown
      } | null
      /** Error Code */
      error_code?: string | null
      /**
       * Message
       * @default ok
       */
      message: string
    }
    /** ArtifactQuestion */
    ArtifactQuestion: {
      /** Answer */
      answer: string[]
      /** Citation Refs */
      citation_refs?: string[]
      /**
       * Coverage Target Id
       * @default null
       */
      coverage_target_id: string | null
      /**
       * Difficulty
       * @enum {string}
       */
      difficulty: 'easy' | 'medium' | 'hard'
      /** Explanation */
      explanation: string
      /** Id */
      id: string
      /** Knowledge Point */
      knowledge_point: string
      /** Options */
      options: components['schemas']['QuestionOption'][]
      /** Stem */
      stem: string
      /** Support Quotes */
      support_quotes?: string[]
      /**
       * Type
       * @enum {string}
       */
      type: 'single' | 'multiple' | 'judge'
    }
    /** AssessmentDraft */
    AssessmentDraft: {
      /**
       * Confirmation
       * @enum {string}
       */
      confirmation: 'confirmed' | 'provisional'
      /** Criterion Results */
      criterion_results?: {
        [key: string]: components['schemas']['JsonValue']
      }[]
      /** Evidence Refs */
      evidence_refs?: string[]
      /**
       * Feedback
       * @default
       */
      feedback: string
      /** Grader Version */
      grader_version: string
      /**
       * Independent Eligible
       * @default false
       */
      independent_eligible: boolean
      /** Rubric Hash */
      rubric_hash: string
      /** Rubric Version */
      rubric_version: string
      /**
       * Score
       * @default null
       */
      score: number | string | null
      /**
       * Source
       * @enum {string}
       */
      source: 'deterministic' | 'model' | 'human'
      /**
       * Status
       * @enum {string}
       */
      status: 'graded' | 'needs_review' | 'failed' | 'cancelled'
      /**
       * Supersedes Assessment Id
       * @default null
       */
      supersedes_assessment_id: string | null
    }
    /** AssessmentRef */
    AssessmentRef: {
      /** Assessment Id */
      assessment_id: string
      /** Attempt Id */
      attempt_id: string
      /**
       * Confirmation
       * @enum {string}
       */
      confirmation: 'confirmed' | 'provisional'
      /** Revision */
      revision: number
      /**
       * Status
       * @enum {string}
       */
      status: 'graded' | 'needs_review' | 'failed' | 'cancelled'
    }
    /** AuthCapabilitiesView */
    AuthCapabilitiesView: {
      /**
       * Legacy Link Enabled
       * @default false
       */
      legacy_link_enabled: boolean
    }
    /** AvatarUploadResponse */
    AvatarUploadResponse: {
      /** Avatar Url */
      avatar_url: string
    }
    /** BindBody */
    BindBody: {
      /** Account */
      account: string
      /** Code */
      code: string
      /**
       * Nickname
       * @default 学习者
       */
      nickname: string
      /** Password */
      password: string
    }
    /** BlankResponse */
    BlankResponse: {
      /** Blank Id */
      blank_id: string
      /** Text */
      text: string
    }
    /** Body_eval_upload_api_v1_eval_documents_post */
    Body_eval_upload_api_v1_eval_documents_post: {
      /** File */
      file: string
    }
    /** Body_upload_api_v1_knowledge_documents_post */
    Body_upload_api_v1_knowledge_documents_post: {
      /** File */
      file: string
    }
    /** Body_upload_avatar_api_v1_user_avatar_post */
    Body_upload_avatar_api_v1_user_avatar_post: {
      /** File */
      file: string
    }
    /** Body_version_api_v1_knowledge_documents__doc_id__versions_post */
    Body_version_api_v1_knowledge_documents__doc_id__versions_post: {
      /** File */
      file: string
    }
    /** CallBody */
    CallBody: {
      /** Attempt */
      attempt: number
      /** Call */
      call: {
        [key: string]: unknown
      }
      /** Lease Token */
      lease_token: string
    }
    /** CanonicalBlock */
    CanonicalBlock: {
      /** Block Id */
      block_id: string
      /** End Char */
      end_char: number
      /** Heading Level */
      heading_level?: number | null
      /** Heading Path */
      heading_path?: string[]
      /**
       * Kind
       * @enum {string}
       */
      kind: 'paragraph' | 'heading' | 'table_row' | 'page' | 'code'
      /** Line End */
      line_end?: number | null
      /** Line Start */
      line_start?: number | null
      /** Page */
      page?: number | null
      /** Paragraph */
      paragraph?: number | null
      /** Section Id */
      section_id: string
      /** Start Char */
      start_char: number
      /** Table Row */
      table_row?: number | null
    }
    /** ChatAnswerArtifact */
    ChatAnswerArtifact: {
      /**
       * Answer Status
       * @enum {string}
       */
      answer_status:
        | 'answered'
        | 'partial'
        | 'needs_clarification'
        | 'insufficient_evidence'
        | 'conflicting_sources'
      /** Blocks */
      blocks: components['schemas']['AnswerBlock'][]
      /**
       * @description discriminator enum property added by openapi-typescript
       * @enum {string}
       */
      case_type: 'qa'
      /** Effective Config */
      effective_config?: {
        [key: string]: unknown
      }
      /** Evidence */
      evidence?: components['schemas']['DocumentEvidence'][]
      /**
       * Model Fingerprint
       * @default unconfigured
       */
      model_fingerprint: string
      /** Pipeline Config Hash */
      pipeline_config_hash: string
      /**
       * Prompt Version
       * @default qa-v1
       */
      prompt_version: string
      /** Retrieval Query */
      retrieval_query: string
      /** Run Id */
      run_id: string
      /**
       * Schema Version
       * @default 1
       * @constant
       */
      schema_version: '1'
      /** Scope Fingerprint */
      scope_fingerprint: string
      /** Trace */
      trace?: {
        [key: string]: unknown
      }[]
      usage?: components['schemas']['Usage']
    }
    /** ClaimBody */
    ClaimBody: {
      /**
       * Lease Seconds
       * @default 120
       */
      lease_seconds: number
      /** Run Id */
      run_id?: string | null
      /** Worker Id */
      worker_id: string
    }
    /** ClozeAnswer */
    ClozeAnswer: {
      /** Blanks */
      blanks: components['schemas']['BlankResponse'][]
      /**
       * @description discriminator enum property added by openapi-typescript
       * @enum {string}
       */
      type: 'cloze'
    }
    /** ClozeQuestion */
    ClozeQuestion: {
      /** Citation Refs */
      citation_refs: string[]
      /** Concept Ids */
      concept_ids: string[]
      /**
       * Difficulty
       * @enum {string}
       */
      difficulty: 'easy' | 'medium' | 'hard'
      /** Id */
      id: string
      rubric: components['schemas']['ClozeRubric']
      /** Stem */
      stem: string
      /** Support Quotes */
      support_quotes: string[]
      /**
       * @description discriminator enum property added by openapi-typescript
       * @enum {string}
       */
      type: 'cloze'
    }
    /** ClozeRubric */
    ClozeRubric: {
      /** Explanation */
      explanation: string
      /**
       * Normalization
       * @default nfkc-space-v1
       * @enum {string}
       */
      normalization: 'nfkc-space-v1' | 'nfkc-space-casefold-v1'
      /** Slots */
      slots: components['schemas']['ClozeSlot'][]
      /**
       * Version
       * @default cloze-rules-v1
       * @constant
       */
      version: 'cloze-rules-v1'
    }
    /** ClozeSlot */
    ClozeSlot: {
      /** Accepted */
      accepted: string[]
      /** Blank Id */
      blank_id: string
      /** Weight */
      weight: number | string
    }
    /** CompletionReceipt */
    CompletionReceipt: {
      /** Accuracy */
      accuracy: number
      /** Correct Count */
      correct_count: number
      /** Quiz Id */
      quiz_id: string
      /** Report Status */
      report_status: string
      /** Revision */
      revision: number
      /** Total */
      total: number
      /** Total Questions */
      total_questions: number
      /** Xp Awarded */
      xp_awarded: number
    }
    /** CostPreviewComponent */
    CostPreviewComponent: {
      /** Assumptions */
      assumptions?: string[]
      /**
       * First Attempt Calls
       * @default 0
       */
      first_attempt_calls: number
      /** First Attempt Cny */
      first_attempt_cny?: number | null
      /**
       * First Attempt Input Tokens
       * @default 0
       */
      first_attempt_input_tokens: number
      /**
       * First Attempt Output Tokens
       * @default 0
       */
      first_attempt_output_tokens: number
      /** Missing Prices */
      missing_prices?: string[]
      /** Prices */
      prices?: {
        [key: string]: number | null
      }
      /** Reason */
      reason?: string | null
      /**
       * Retry Scenario Calls
       * @default 0
       */
      retry_scenario_calls: number
      /** Retry Scenario Cny */
      retry_scenario_cny?: number | null
      /**
       * Retry Scenario Input Tokens
       * @default 0
       */
      retry_scenario_input_tokens: number
      /**
       * Retry Scenario Output Tokens
       * @default 0
       */
      retry_scenario_output_tokens: number
      /**
       * Stage
       * @enum {string}
       */
      stage: 'retrieval' | 'generation' | 'grading' | 'scoring' | 'indexing'
      /**
       * Status
       * @enum {string}
       */
      status: 'estimated' | 'unknown' | 'not_applicable'
    }
    /** CoveragePlan */
    CoveragePlan: {
      /**
       * Planner Version
       * @default deterministic-catalog-v1
       */
      planner_version: string
      /** Subqueries */
      subqueries: string[]
      /** Targets */
      targets: components['schemas']['CoverageTarget'][]
    }
    /** CoverageTarget */
    CoverageTarget: {
      /** Doc Ids */
      doc_ids?: string[]
      /** Evidence Ids */
      evidence_ids?: string[]
      /** Question Quota */
      question_quota: number
      /** Section Ids */
      section_ids?: string[]
      /** Target Id */
      target_id: string
      /** Title */
      title: string
    }
    /** DatasetCreate */
    DatasetCreate: {
      /** Dataset Id */
      dataset_id?: string | null
      /** Manifest */
      manifest: {
        [key: string]: unknown
      }
      /** Name */
      name: string
      /** Samples */
      samples: {
        [key: string]: unknown
      }[]
    }
    /** DatasetList */
    DatasetList: {
      /** Items */
      items: components['schemas']['DatasetView'][]
      /** Total */
      total: number
    }
    /** DatasetPatch */
    DatasetPatch: {
      /** Manifest */
      manifest?: {
        [key: string]: unknown
      } | null
      /** Name */
      name?: string | null
      /** Revision */
      revision: number
      /** Samples */
      samples?:
        | {
            [key: string]: unknown
          }[]
        | null
    }
    /** DatasetReview */
    DatasetReview: {
      /**
       * Comment
       * @default
       */
      comment: string
      /** Expected Revision */
      expected_revision: number
      /**
       * Verdict
       * @enum {string}
       */
      verdict: 'approved' | 'needs_changes'
    }
    /** DatasetView */
    DatasetView: {
      /** Checksum */
      checksum?: string | null
      /** Dataset Id */
      dataset_id: string
      /** Manifest */
      manifest: {
        [key: string]: unknown
      }
      /** Name */
      name: string
      /** Revision */
      revision: number
      /**
       * Sample Count
       * @default 0
       */
      sample_count: number
      /** Samples */
      samples?: {
        [key: string]: unknown
      }[]
      /** Split Counts */
      split_counts?: {
        [key: string]: number
      }
      /** Status */
      status: string
      /** Validation */
      validation?: {
        [key: string]: unknown
      } | null
      /** Version */
      version: number
    }
    /** DocumentDeletionView */
    DocumentDeletionView: {
      /** Doc Id */
      doc_id: string
      /**
       * Status
       * @constant
       */
      status: 'deleted'
      /** Task Id */
      task_id: string
    }
    /** DocumentEvidence */
    DocumentEvidence: {
      /** Attempt Id */
      attempt_id: string
      /** Chunk Id */
      chunk_id: string
      /** Doc Id */
      doc_id: string
      /** Document Version Id */
      document_version_id: string
      /** Evidence Id */
      evidence_id: string
      /** Excerpt */
      excerpt: string
      /** Index Build Id */
      index_build_id: string
      locator: components['schemas']['DocumentLocator']
      /** Namespace */
      namespace: string
      /** Owner Id */
      owner_id: number
      /** Parent Id */
      parent_id?: string | null
      /** Parse Artifact Id */
      parse_artifact_id: string
      /** Retrieval Scores */
      retrieval_scores?: {
        [key: string]: number
      }
      /** Score */
      score?: number | null
      /**
       * @description discriminator enum property added by openapi-typescript
       * @enum {string}
       */
      source_type: 'document'
      /** Text Hash */
      text_hash: string
      /** Title */
      title: string
    }
    /** DocumentList */
    DocumentList: {
      /** Items */
      items: components['schemas']['DocumentView'][]
      /** Total */
      total: number
    }
    /** DocumentLocator */
    DocumentLocator: {
      /** Block Id */
      block_id: string
      /** Block Ids */
      block_ids?: string[]
      /** Canonical Text Hash */
      canonical_text_hash: string
      /** End Char */
      end_char: number
      /** Heading Path */
      heading_path?: string[]
      /** Line End */
      line_end?: number | null
      /** Line Start */
      line_start?: number | null
      /** Normalizer Version */
      normalizer_version: string
      /** Page */
      page?: number | null
      /** Paragraph */
      paragraph?: number | null
      /** Parse Artifact Id */
      parse_artifact_id: string
      /** Parser Version */
      parser_version: string
      /** Quote Hash */
      quote_hash: string
      /** Section Id */
      section_id?: string | null
      /** Section Ids */
      section_ids?: string[]
      /** Source Sha256 */
      source_sha256: string
      /** Start Char */
      start_char: number
      /** Table Row */
      table_row?: number | null
    }
    /** DocumentView */
    DocumentView: {
      /** Active Build Id */
      active_build_id?: string | null
      /** Active Version Id */
      active_version_id?: string | null
      /**
       * Chunk Count
       * @default 0
       */
      chunk_count: number
      /** Created At */
      created_at?: string | null
      /** Doc Id */
      doc_id: string
      /** Document Revision */
      document_revision: number
      /** Error Code */
      error_code?: string | null
      /** Error Message */
      error_message?: string | null
      /** File Name */
      file_name: string
      /** File Size */
      file_size: number
      /** File Type */
      file_type: string
      /**
       * Purpose
       * @default production
       */
      purpose: string
      /** Section Catalog Revision */
      section_catalog_revision?: string | null
      /** Sections */
      sections?: components['schemas']['SectionView'][]
      /** Status */
      status: string
      /** Task Id */
      task_id?: string | null
    }
    EvalSample:
      | components['schemas']['RetrievalSample']
      | components['schemas']['QuizSample']
      | components['schemas']['QaSample']
      | components['schemas']['PolicySample']
      | components['schemas']['PracticeGenerationSample']
      | components['schemas']['AnswerGradingSample']
    EvaluationArtifact:
      | components['schemas']['RetrievalArtifact']
      | components['schemas']['QuizArtifact']
      | components['schemas']['ChatAnswerArtifact']
      | components['schemas']['PolicyArtifact']
      | components['schemas']['PracticeGenerationEvalArtifact']
      | components['schemas']['AnswerGradingEvalArtifact']
    /** EvidencePack */
    EvidencePack: {
      /**
       * Context Tokens
       * @default 0
       */
      context_tokens: number
      /** @default null */
      coverage: components['schemas']['CoveragePlan'] | null
      /** Evidence */
      evidence?: (
        | components['schemas']['DocumentEvidence']
        | components['schemas']['WebEvidence']
      )[]
      /**
       * Policy
       * @enum {string}
       */
      policy: 'topic' | 'strict_docs' | 'doc_plus_web'
      /** Provided Evidence Ids */
      provided_evidence_ids?: string[]
      resolved_scope: components['schemas']['ResolvedScope']
      /**
       * Status
       * @enum {string}
       */
      status: 'ready' | 'model_only' | 'insufficient'
      /**
       * Token Count Method
       * @default utf8-upper-bound-v1
       */
      token_count_method: string
      /** Trace Id */
      trace_id: string
      usage?: components['schemas']['Usage']
      /** Warnings */
      warnings?: string[]
    }
    /** FailBody */
    FailBody: {
      /** Attempt */
      attempt: number
      /** Error Code */
      error_code: string
      /** Error Message */
      error_message?: string | null
      /** Judge Calls */
      judge_calls?: {
        [key: string]: unknown
      }[]
      /** Lease Token */
      lease_token: string
    }
    /** FeedbackCreate */
    FeedbackCreate: {
      /**
       * Allow Evaluation Use
       * @default false
       */
      allow_evaluation_use: boolean
      /**
       * Comment
       * @default
       */
      comment: string
      /** Question Id */
      question_id: string
      /**
       * Reason
       * @enum {string}
       */
      reason:
        | 'incorrect_answer'
        | 'unsupported_explanation'
        | 'citation_mismatch'
        | 'duplicate'
        | 'other'
    }
    /** FeedbackList */
    FeedbackList: {
      /** Items */
      items: components['schemas']['FeedbackView'][]
      /** Total */
      total: number
    }
    /** FeedbackPromote */
    FeedbackPromote: {
      /** Dataset Id */
      dataset_id?: string | null
      /** Expected Revision */
      expected_revision: number
      /** Name */
      name: string
      /**
       * Question Count
       * @default 3
       */
      question_count: number
      /** Redacted Request */
      redacted_request: string
    }
    /** FeedbackReview */
    FeedbackReview: {
      /**
       * Comment
       * @default
       */
      comment: string
      /** Expected Revision */
      expected_revision: number
      /**
       * Verdict
       * @enum {string}
       */
      verdict: 'approved' | 'rejected' | 'needs_changes'
    }
    /** FeedbackView */
    FeedbackView: {
      /**
       * Access Scope
       * @default owner_only
       * @constant
       */
      access_scope: 'owner_only'
      /** Allow Evaluation Use */
      allow_evaluation_use: boolean
      /** Comment */
      comment: string
      /** Created At */
      created_at: string
      /** Feedback Id */
      feedback_id: string
      /** Promotion */
      promotion?: {
        [key: string]: unknown
      } | null
      /** Question Id */
      question_id: string
      /** Quiz Id */
      quiz_id: string
      /** Reason */
      reason: string
      /** Review */
      review?: {
        [key: string]: unknown
      } | null
      /** Revision */
      revision: number
      /** Status */
      status: string
    }
    /** FreezeBody */
    FreezeBody: {
      /** Checklist */
      checklist?: {
        [key: string]: boolean
      } | null
      /** Expected Revision */
      expected_revision: number
    }
    /** GenerateBody */
    GenerateBody: {
      /**
       * Difficulty
       * @default mixed
       * @enum {string}
       */
      difficulty: 'easy' | 'medium' | 'hard' | 'mixed'
      /** Doc Id */
      doc_id?: string | null
      /**
       * Generate Images
       * @default false
       */
      generate_images: boolean
      /**
       * Question Count
       * @default 5
       */
      question_count: number
      /** Review Of Quiz Id */
      review_of_quiz_id?: string | null
      scope?: components['schemas']['RequestedScope'] | null
      /** Source Policy */
      source_policy?: ('topic' | 'strict_docs' | 'doc_plus_web') | null
      /** User Input */
      user_input?: string | null
    }
    /**
     * GradeArtifact
     * @description Server-sealed assessment; the grader also verifies its immutable snapshot.
     */
    GradeArtifact: {
      /** Artifact Id */
      artifact_id: string
      assessment: components['schemas']['AssessmentDraft']
      /** Attempt Id */
      attempt_id: string
      /**
       * Calibration Profile Hash
       * @default null
       */
      calibration_profile_hash: string | null
      /**
       * Case Type
       * @default answer_grading
       * @constant
       */
      case_type: 'answer_grading'
      /** Grader Version */
      grader_version: string
      /** Grading Request Id */
      grading_request_id: string
      /**
       * Mode
       * @enum {string}
       */
      mode: 'production' | 'evaluation'
      /** Model Fingerprint */
      model_fingerprint: string
      /** Owner Id */
      owner_id: number
      /** Prompt Hash */
      prompt_hash: string
      /** Prompt Version */
      prompt_version: string
      /** Question Version */
      question_version: string
      /** Response Hash */
      response_hash: string
      /** Rubric Hash */
      rubric_hash: string
      /** Rubric Version */
      rubric_version: string
      /** Run Id */
      run_id: string
      /**
       * Schema Version
       * @default grade-artifact.v1
       * @constant
       */
      schema_version: 'grade-artifact.v1'
      /** Scope Fingerprint */
      scope_fingerprint: string
      usage: components['schemas']['PracticeUsage']
    }
    /** HTTPValidationError */
    HTTPValidationError: {
      /** Detail */
      detail?: components['schemas']['ValidationError'][]
    }
    /** HeartbeatBody */
    HeartbeatBody: {
      /** Attempt */
      attempt: number
      /**
       * Lease Seconds
       * @default 120
       */
      lease_seconds: number
      /** Lease Token */
      lease_token: string
    }
    JsonValue: unknown
    /** JudgeProfile */
    JudgeProfile: {
      /**
       * Calibrated
       * @default false
       */
      calibrated: boolean
      /** Description */
      description: string
      /** Judge Profile Id */
      judge_profile_id: string
      /** Name */
      name: string
    }
    /** JudgeProfileList */
    JudgeProfileList: {
      /** Items */
      items: components['schemas']['JudgeProfile'][]
      /** Total */
      total: number
    }
    /**
     * LearningEvaluationUsage
     * @description One outer provider ledger; private artifact usage is trace-only.
     */
    LearningEvaluationUsage: {
      /** Calls */
      calls?: {
        [key: string]: unknown
      }[]
      /**
       * Cost Cny
       * @default null
       */
      cost_cny: number | string | null
      /**
       * Cost Status
       * @default unreported
       * @enum {string}
       */
      cost_status: 'unreported' | 'estimated' | 'reported'
      /**
       * Cost Status Cny
       * @default unreported
       * @enum {string}
       */
      cost_status_cny: 'unreported' | 'estimated' | 'unknown'
      /**
       * Cost Usd
       * @default null
       */
      cost_usd: number | null
      /**
       * Embedding Calls
       * @default 0
       */
      embedding_calls: number
      /**
       * Embedding Tokens
       * @default 0
       */
      embedding_tokens: number
      /**
       * Fetch Calls
       * @default 0
       */
      fetch_calls: number
      /**
       * Input Tokens
       * @default 0
       */
      input_tokens: number
      /**
       * Known Cost Cny
       * @default 0
       */
      known_cost_cny: number | string
      /**
       * Ledger Complete
       * @default false
       */
      ledger_complete: boolean
      /**
       * Llm Calls
       * @default 0
       */
      llm_calls: number
      /**
       * Output Tokens
       * @default 0
       */
      output_tokens: number
      /**
       * Reranker Calls
       * @default 0
       */
      reranker_calls: number
      /**
       * Reserved Cost Cny
       * @default null
       */
      reserved_cost_cny: number | string | null
      /**
       * Search Calls
       * @default 0
       */
      search_calls: number
      /** Stage Ms */
      stage_ms?: {
        [key: string]: number
      }
      /**
       * Token Count Method
       * @default provider-reported-or-utf8-upper-bound-v1
       */
      token_count_method: string
      /**
       * Unknown Call Count
       * @default 0
       */
      unknown_call_count: number
      /**
       * Unknown Reserved Cost Cny
       * @default null
       */
      unknown_reserved_cost_cny: number | string | null
    }
    /** LoginBody */
    LoginBody: {
      /** Account */
      account: string
      /** Password */
      password: string
    }
    /** LoginRequest */
    LoginRequest: {
      /**
       * Code
       * @description wx.login() 返回的 code
       */
      code: string
    }
    /** LoginResponse */
    LoginResponse: {
      /** Token */
      token: string
      user: components['schemas']['UserBrief']
    }
    /** MetricValue */
    MetricValue: {
      /**
       * Applicable Count
       * @default 0
       */
      applicable_count: number
      /**
       * Denominator
       * @default 0
       */
      denominator: number
      /**
       * Error Count
       * @default 0
       */
      error_count: number
      /**
       * Metric Version
       * @default evidence-v1
       */
      metric_version: string
      /** Numerator */
      numerator?: number | null
      /** Reason */
      reason?: string | null
      /**
       * Status
       * @enum {string}
       */
      status: 'ok' | 'na' | 'error'
      /**
       * Unit
       * @default ratio
       */
      unit: string
      /**
       * Unknown Count
       * @default 0
       */
      unknown_count: number
      /** Value */
      value?: number | null
    } & {
      [key: string]: unknown
    }
    /** NumericAnswer */
    NumericAnswer: {
      /**
       * @description discriminator enum property added by openapi-typescript
       * @enum {string}
       */
      type: 'numeric'
      /**
       * Unit
       * @default
       */
      unit: string
      /** Value */
      value: string
    }
    /** NumericQuestion */
    NumericQuestion: {
      /** Citation Refs */
      citation_refs: string[]
      /** Concept Ids */
      concept_ids: string[]
      /**
       * Difficulty
       * @enum {string}
       */
      difficulty: 'easy' | 'medium' | 'hard'
      /** Id */
      id: string
      rubric: components['schemas']['NumericRubric']
      /** Stem */
      stem: string
      /** Support Quotes */
      support_quotes: string[]
      /**
       * @description discriminator enum property added by openapi-typescript
       * @enum {string}
       */
      type: 'numeric'
    }
    /** NumericRubric */
    NumericRubric: {
      /** Absolute Tolerance */
      absolute_tolerance: number | string
      /** Explanation */
      explanation: string
      /** Relative Tolerance */
      relative_tolerance: number | string
      /** Target */
      target: number | string
      /** Unit */
      unit: string
      /** Unit Aliases */
      unit_aliases: string[]
      /**
       * Version
       * @default numeric-rules-v1
       * @constant
       */
      version: 'numeric-rules-v1'
    }
    /** ObjectiveRef */
    ObjectiveRef: {
      /** Concept Id */
      concept_id: string
      /** Title */
      title: string
    }
    /** PasswordBody */
    PasswordBody: {
      /** Current Password */
      current_password: string
      /** New Password */
      new_password: string
    }
    /** PolicyArtifact */
    PolicyArtifact: {
      /**
       * @description discriminator enum property added by openapi-typescript
       * @enum {string}
       */
      case_type: 'policy'
      /** Observations */
      observations: {
        [key: string]: unknown
      }
      /** Run Id */
      run_id: string
      /**
       * Schema Version
       * @default policy-artifact.v1
       * @constant
       */
      schema_version: 'policy-artifact.v1'
      /** Side Effect Diff */
      side_effect_diff?: {
        [key: string]: unknown
      }
      usage?: components['schemas']['Usage']
    }
    /** PolicySample */
    PolicySample: {
      /** Annotation */
      annotation?: {
        [key: string]: unknown
      }
      /**
       * @description discriminator enum property added by openapi-typescript
       * @enum {string}
       */
      case_type: 'policy'
      /** Family Ids */
      family_ids?: string[]
      /** Harness */
      harness: {
        [key: string]: unknown
      }
      /** Sample Id */
      sample_id: string
      /**
       * Schema Version
       * @default 1
       */
      schema_version: string
      /** Source Refs */
      source_refs?: {
        [key: string]: unknown
      }[]
      /**
       * Split
       * @enum {string}
       */
      split: 'dev' | 'judge_calibration' | 'locked_test'
      /** Tags */
      tags?: string[]
    } & {
      [key: string]: unknown
    }
    /** PracticeAnswerBody */
    PracticeAnswerBody: {
      /** Answer */
      answer:
        | components['schemas']['ClozeAnswer']
        | components['schemas']['NumericAnswer']
        | components['schemas']['ShortAnswer']
      /** Duration Ms */
      duration_ms: number
    }
    /** PracticeArtifact */
    PracticeArtifact: {
      /** Artifact Id */
      artifact_id: string
      /**
       * Case Type
       * @default practice_generation
       * @constant
       */
      case_type: 'practice_generation'
      evidence_pack: components['schemas']['EvidencePack']
      /**
       * Mode
       * @enum {string}
       */
      mode: 'production' | 'evaluation'
      /** Model Fingerprint */
      model_fingerprint: string
      /** Owner Id */
      owner_id: number
      /** Pipeline Config Hash */
      pipeline_config_hash: string
      /** Prompt Hash */
      prompt_hash: string
      /** Prompt Version */
      prompt_version: string
      /** Question Versions */
      question_versions: {
        [key: string]: string
      }
      /** Questions */
      questions: (
        | components['schemas']['ClozeQuestion']
        | components['schemas']['NumericQuestion']
        | components['schemas']['ShortAnswerQuestion']
      )[]
      /** Rubric Hashes */
      rubric_hashes: {
        [key: string]: string
      }
      /** Run Id */
      run_id: string
      /**
       * Schema Version
       * @default practice-artifact.v1
       * @constant
       */
      schema_version: 'practice-artifact.v1'
      /** Scope Fingerprint */
      scope_fingerprint: string
      /** Scope Revision */
      scope_revision: number
      /** Space Id */
      space_id: string
      /** Summary */
      summary: string
      /** Title */
      title: string
      usage: components['schemas']['PracticeUsage']
    }
    /** PracticeAssessmentView */
    PracticeAssessmentView: {
      /** Assessment Id */
      assessment_id: string
      /** Attempt Id */
      attempt_id: string
      /**
       * Confirmation
       * @enum {string}
       */
      confirmation: 'confirmed' | 'provisional'
      /** Created At */
      created_at?: string | null
      /** Criterion Results */
      criterion_results?: components['schemas']['PracticeCriterionResultView'][]
      /** Evidence Refs */
      evidence_refs?: string[]
      /**
       * Feedback
       * @default
       */
      feedback: string
      /**
       * Independent Eligible
       * @default false
       */
      independent_eligible: boolean
      /** Revision */
      revision: number
      /** Score */
      score?: string | null
      /**
       * Source
       * @enum {string}
       */
      source: 'deterministic' | 'model' | 'human'
      /**
       * Status
       * @enum {string}
       */
      status: 'graded' | 'needs_review' | 'failed' | 'cancelled'
      /** Supersedes Assessment Id */
      supersedes_assessment_id?: string | null
    }
    /** PracticeAttemptView */
    PracticeAttemptView: {
      /** Active Task Id */
      active_task_id?: string | null
      /** Answer */
      answer:
        | components['schemas']['ClozeAnswer']
        | components['schemas']['NumericAnswer']
        | components['schemas']['ShortAnswer']
      /** Assessment History */
      assessment_history?: components['schemas']['PracticeAssessmentView'][]
      /** Attempt Id */
      attempt_id: string
      /** Created At */
      created_at?: string | null
      current_assessment?: components['schemas']['PracticeAssessmentView'] | null
      /** Duration Ms */
      duration_ms: number
      /**
       * Grading Revision
       * @default 0
       */
      grading_revision: number
      /** Grading Status */
      grading_status?: ('pending' | 'running' | 'completed' | 'failed' | 'cancelled') | null
      /**
       * Help Usage
       * @enum {string}
       */
      help_usage: 'none' | 'hints' | 'unknown'
      /** Practice Id */
      practice_id: string
      /** Question Id */
      question_id: string
      /** Question Version */
      question_version: string
      receipt: components['schemas']['PracticeSubmissionReceipt']
      /** Self Reviews */
      self_reviews?: components['schemas']['PracticeSelfReviewView'][]
    }
    /** PracticeCallUsage */
    PracticeCallUsage: {
      /** Attempt */
      attempt: number
      /** Call Id */
      call_id: string
      /**
       * Cost Cny
       * @default null
       */
      cost_cny: number | string | null
      /**
       * Cost Status
       * @default unknown
       * @enum {string}
       */
      cost_status: 'estimated' | 'unknown'
      /**
       * Reserved Cost Cny
       * @default null
       */
      reserved_cost_cny: number | string | null
      /**
       * Stage
       * @enum {string}
       */
      stage: 'llm' | 'embedding' | 'reranker' | 'search' | 'fetch' | 'images'
      /**
       * Status
       * @enum {string}
       */
      status: 'reserved' | 'completed' | 'unknown'
      /** Task Id */
      task_id: string
    }
    /** PracticeCompleteBody */
    PracticeCompleteBody: {
      /** Expected Revision */
      expected_revision: number
    }
    /** PracticeCompletionReceipt */
    PracticeCompletionReceipt: {
      /** Accepted Revision */
      accepted_revision: number
      /** Answer Set Hash */
      answer_set_hash: string
      /** Attempt Ids */
      attempt_ids: string[]
      /**
       * Completed At
       * Format: date-time
       */
      completed_at: string
      /** Completion Id */
      completion_id: string
      /** Practice Id */
      practice_id: string
    }
    /** PracticeCostPreview */
    PracticeCostPreview: {
      /** Cost Cny Upper */
      cost_cny_upper: string | null
      /**
       * Cost Status
       * @enum {string}
       */
      cost_status: 'estimated' | 'unknown'
      /** Embedding Token Upper */
      embedding_token_upper: number
      /**
       * Generation Llm Call Upper
       * @default 5
       */
      generation_llm_call_upper: number
      /** Grading Llm Call Upper */
      grading_llm_call_upper: number
      /** Input Token Upper */
      input_token_upper: number
      /** Output Token Upper */
      output_token_upper: number
      /** Pricing Version */
      pricing_version: string
    }
    /** PracticeCriterionResultView */
    PracticeCriterionResultView: {
      /** Answer Quotes */
      answer_quotes?: string[]
      /**
       * Credit
       * @enum {string}
       */
      credit: 'full' | 'half' | 'none' | 'uncertain'
      /** Criterion Id */
      criterion_id: string
      /** Evidence Refs */
      evidence_refs?: string[]
      /**
       * Rationale
       * @default
       */
      rationale: string
    }
    /** PracticeGenerationEvalArtifact */
    PracticeGenerationEvalArtifact: {
      /**
       * @description discriminator enum property added by openapi-typescript
       * @enum {string}
       */
      case_type: 'practice_generation'
      /**
       * Error Code
       * @default null
       */
      error_code: string | null
      /** @default null */
      practice: components['schemas']['PracticeArtifact'] | null
      /**
       * Repeat Index
       * @default 0
       */
      repeat_index: number
      /** Run Id */
      run_id: string
      /** Sample Id */
      sample_id: string
      /**
       * Schema Version
       * @default 1
       * @constant
       */
      schema_version: '1'
      /**
       * Status
       * @enum {string}
       */
      status: 'completed' | 'refused' | 'failed' | 'cancelled' | 'timeout'
      usage?: components['schemas']['LearningEvaluationUsage']
    }
    /**
     * PracticeGenerationRubric
     * @description Review instructions, never a model's claim that review has passed.
     */
    PracticeGenerationRubric: {
      /**
       * Notes
       * @default
       */
      notes: string
      /** Required Semantics */
      required_semantics?: (
        | 'answer_correctness'
        | 'source_support'
        | 'solvability'
        | 'explanation_correctness'
        | 'scope_compliance'
        | 'citation_support'
        | 'citation_completeness'
      )[]
      /**
       * Version
       * @default practice-generation-rubric.v1
       * @constant
       */
      version: 'practice-generation-rubric.v1'
    }
    /** PracticeGenerationSample */
    PracticeGenerationSample: {
      /** Annotation */
      annotation?: {
        [key: string]: unknown
      }
      /**
       * @description discriminator enum property added by openapi-typescript
       * @enum {string}
       */
      case_type: 'practice_generation'
      /**
       * Expected Error Code
       * @default null
       */
      expected_error_code: string | null
      /**
       * Expected Outcome
       * @enum {string}
       */
      expected_outcome: 'generate' | 'refuse' | 'failed'
      /** Family Ids */
      family_ids?: string[]
      generation_rubric?: components['schemas']['PracticeGenerationRubric']
      /** Gold Evidence Groups */
      gold_evidence_groups?: {
        [key: string]: unknown
      }[]
      /** Sample Id */
      sample_id: string
      /**
       * Schema Version
       * @default 1
       */
      schema_version: string
      /** Source Refs */
      source_refs: {
        [key: string]: unknown
      }[]
      spec: components['schemas']['PracticeSpec']
      /**
       * Split
       * @enum {string}
       */
      split: 'dev' | 'judge_calibration' | 'locked_test'
      /** Tags */
      tags?: string[]
    } & {
      [key: string]: unknown
    }
    /** PracticeHelpView */
    PracticeHelpView: {
      /** Evidence Ids */
      evidence_ids: string[]
      /**
       * Help Usage
       * @default hints
       * @constant
       */
      help_usage: 'hints'
      /** Practice Id */
      practice_id: string
      /** Question Id */
      question_id: string
    }
    /** PracticeReviewBody */
    PracticeReviewBody: {
      /** Criterion Results */
      criterion_results: components['schemas']['PracticeReviewCriterion'][]
      /** Evidence Refs */
      evidence_refs: string[]
      /** Expected Assessment Id */
      expected_assessment_id: string | null
      /** Expected Grading Revision */
      expected_grading_revision: number
      /** Feedback */
      feedback: string
    }
    /**
     * PracticeReviewContext
     * @description Private rubric points exposed only to the owning evaluator after submission.
     */
    PracticeReviewContext: {
      answer: components['schemas']['ShortAnswer']
      /** Attempt Id */
      attempt_id: string
      /** Criteria */
      criteria: components['schemas']['PracticeReviewPoint'][]
      /** Current Assessment Id */
      current_assessment_id: string | null
      /** Grading Revision */
      grading_revision: number
      /**
       * Help Usage
       * @enum {string}
       */
      help_usage: 'none' | 'hints' | 'unknown'
      /** Practice Id */
      practice_id: string
      /** Question Id */
      question_id: string
      /** Question Version */
      question_version: string
      /** Rubric Version */
      rubric_version: string
      scope: components['schemas']['PublicResolvedScope']
      /** Stem */
      stem: string
    }
    /** PracticeReviewCriterion */
    PracticeReviewCriterion: {
      /** Answer Quotes */
      answer_quotes?: string[]
      /**
       * Credit
       * @enum {string}
       */
      credit: 'full' | 'half' | 'none'
      /** Criterion Id */
      criterion_id: string
      /** Evidence Refs */
      evidence_refs: string[]
      /** Rationale */
      rationale: string
    }
    /** PracticeReviewPoint */
    PracticeReviewPoint: {
      /** Criterion Id */
      criterion_id: string
      /** Evidence Refs */
      evidence_refs: string[]
      /** Reference Point */
      reference_point: string
      /** Weight */
      weight: string
    }
    /** PracticeSelfReviewBody */
    PracticeSelfReviewBody: {
      /**
       * Notes
       * @default
       */
      notes: string
      /**
       * Self Rating
       * @enum {string}
       */
      self_rating: 'understood' | 'needs_practice' | 'unsure'
    }
    /** PracticeSelfReviewReceipt */
    PracticeSelfReviewReceipt: {
      /** Annotation Id */
      annotation_id: string
    }
    /** PracticeSelfReviewView */
    PracticeSelfReviewView: {
      /** Annotation Id */
      annotation_id: string
      /**
       * Created At
       * Format: date-time
       */
      created_at: string
      /**
       * Independent Eligible
       * @default false
       * @constant
       */
      independent_eligible: false
      /**
       * Notes
       * @default
       */
      notes: string
      /**
       * Self Rating
       * @enum {string}
       */
      self_rating: 'understood' | 'needs_practice' | 'unsure'
    }
    /** PracticeSpec */
    PracticeSpec: {
      /** Concept Ids */
      concept_ids: string[]
      /**
       * Difficulty
       * @enum {string}
       */
      difficulty: 'easy' | 'medium' | 'hard' | 'mixed'
      /** Objectives */
      objectives: string[]
      /** Question Count */
      question_count: number
      /** Question Types */
      question_types: ('cloze' | 'numeric' | 'short_answer')[]
      /** Scope Revision */
      scope_revision: number
      /** Space Id */
      space_id: string
    }
    /**
     * PracticeSubmissionReceipt
     * @description The original response to a submission; current grading is queried separately.
     */
    PracticeSubmissionReceipt: {
      /** Accepted Revision */
      accepted_revision: number
      /** Assessment Id */
      assessment_id?: string | null
      /** Attempt Id */
      attempt_id: string
      /** Grading Request Id */
      grading_request_id?: string | null
      /** Practice Id */
      practice_id: string
      /** Question Id */
      question_id: string
      /** Task Id */
      task_id?: string | null
    }
    /** PracticeTaskView */
    PracticeTaskView: {
      /** Error Code */
      error_code?: string | null
      /** Error Message */
      error_message?: string | null
      /** Execution Ms */
      execution_ms?: number | null
      /**
       * Operation
       * @enum {string}
       */
      operation: 'generate' | 'grade'
      /** Practice Id */
      practice_id: string
      /** Queue Ms */
      queue_ms?: number | null
      /** Result */
      result?:
        | components['schemas']['PracticeView']
        | components['schemas']['PracticeAttemptView']
        | null
      /**
       * Stage
       * @default queued
       */
      stage: string
      /**
       * Status
       * @enum {string}
       */
      status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
      /** Task Id */
      task_id: string
    }
    /**
     * PracticeUsage
     * @description The worker fills the complete logical-request ledger across task retries.
     */
    PracticeUsage: {
      /** Calls */
      calls?: components['schemas']['PracticeCallUsage'][]
      /**
       * Cost Cny
       * @default null
       */
      cost_cny: number | string | null
      /**
       * Cost Status
       * @default unreported
       * @enum {string}
       */
      cost_status: 'unreported' | 'estimated' | 'reported'
      /**
       * Cost Status Cny
       * @default unreported
       * @enum {string}
       */
      cost_status_cny: 'unreported' | 'estimated' | 'unknown'
      /**
       * Cost Usd
       * @default null
       */
      cost_usd: number | null
      /**
       * Embedding Calls
       * @default 0
       */
      embedding_calls: number
      /**
       * Embedding Tokens
       * @default 0
       */
      embedding_tokens: number
      /**
       * Fetch Calls
       * @default 0
       */
      fetch_calls: number
      /**
       * Input Tokens
       * @default 0
       */
      input_tokens: number
      /**
       * Known Cost Cny
       * @default 0
       */
      known_cost_cny: number | string
      /**
       * Ledger Complete
       * @default false
       */
      ledger_complete: boolean
      /**
       * Llm Calls
       * @default 0
       */
      llm_calls: number
      /**
       * Output Tokens
       * @default 0
       */
      output_tokens: number
      /**
       * Reranker Calls
       * @default 0
       */
      reranker_calls: number
      /**
       * Reserved Cost Cny
       * @default null
       */
      reserved_cost_cny: number | string | null
      /**
       * Search Calls
       * @default 0
       */
      search_calls: number
      /** Stage Ms */
      stage_ms?: {
        [key: string]: number
      }
      /**
       * Token Count Method
       * @default provider-reported-or-utf8-upper-bound-v1
       */
      token_count_method: string
    }
    /** PracticeView */
    PracticeView: {
      /** Completed At */
      completed_at?: string | null
      completion?: components['schemas']['PracticeCompletionReceipt'] | null
      /**
       * Confirmed Count
       * @default 0
       */
      confirmed_count: number
      /**
       * Needs Review Count
       * @default 0
       */
      needs_review_count: number
      /**
       * Pending Grading Count
       * @default 0
       */
      pending_grading_count: number
      /** Practice Id */
      practice_id: string
      /**
       * Projection Status
       * @default not_ready
       * @enum {string}
       */
      projection_status: 'not_ready' | 'pending' | 'applied' | 'failed'
      /** Questions */
      questions?: (
        | components['schemas']['PublicClozeQuestion']
        | components['schemas']['PublicNumericQuestion']
        | components['schemas']['PublicShortAnswerQuestion']
      )[]
      /** Revision */
      revision: number
      scope?: components['schemas']['PublicResolvedScope'] | null
      /** Scope Revision */
      scope_revision: number
      /**
       * Source Status
       * @default active
       * @enum {string}
       */
      source_status: 'active' | 'revoked'
      /** Space Id */
      space_id: string
      /**
       * Status
       * @enum {string}
       */
      status: 'generating' | 'ready' | 'completed' | 'failed' | 'cancelled'
      /** Submissions */
      submissions?: components['schemas']['PracticeAttemptView'][]
      /**
       * Submitted Count
       * @default 0
       */
      submitted_count: number
      /** Summary */
      summary: string
      /** Title */
      title: string
    }
    /** ProgressView */
    ProgressView: {
      /**
       * Completed
       * @default 0
       */
      completed: number
      /**
       * Failed
       * @default 0
       */
      failed: number
      /**
       * Pending
       * @default 0
       */
      pending: number
      /**
       * Prediction Failed
       * @default 0
       */
      prediction_failed: number
      /**
       * Scoring
       * @default 0
       */
      scoring: number
      /**
       * Total
       * @default 0
       */
      total: number
    }
    /** PromotionView */
    PromotionView: {
      /** Dataset Id */
      dataset_id?: string | null
      /** Dataset Version */
      dataset_version?: number | null
      /** Documents */
      documents?: components['schemas']['DocumentView'][]
      feedback: components['schemas']['FeedbackView']
      /**
       * Status
       * @enum {string}
       */
      status: 'preparing' | 'promoted'
    }
    /** PublicClozeQuestion */
    PublicClozeQuestion: {
      /** Blank Ids */
      blank_ids: string[]
      /** Citation Refs */
      citation_refs: string[]
      /** Concept Ids */
      concept_ids: string[]
      /**
       * Difficulty
       * @enum {string}
       */
      difficulty: 'easy' | 'medium' | 'hard'
      /** Id */
      id: string
      /** Question Version */
      question_version: string
      /** Stem */
      stem: string
      /**
       * @description discriminator enum property added by openapi-typescript
       * @enum {string}
       */
      type: 'cloze'
    }
    /** PublicNumericQuestion */
    PublicNumericQuestion: {
      /** Citation Refs */
      citation_refs: string[]
      /** Concept Ids */
      concept_ids: string[]
      /**
       * Difficulty
       * @enum {string}
       */
      difficulty: 'easy' | 'medium' | 'hard'
      /** Id */
      id: string
      /** Question Version */
      question_version: string
      /** Stem */
      stem: string
      /**
       * @description discriminator enum property added by openapi-typescript
       * @enum {string}
       */
      type: 'numeric'
      /** Unit */
      unit: string
    }
    /** PublicPracticeEvidence */
    PublicPracticeEvidence: {
      /** Doc Id */
      doc_id: string
      /** Document Version Id */
      document_version_id: string
      /** Evidence Id */
      evidence_id: string
      /** Excerpt */
      excerpt: string
      locator: components['schemas']['DocumentLocator']
      /** Practice Id */
      practice_id: string
      /** Question Id */
      question_id: string
      /**
       * Source Type
       * @default document
       * @constant
       */
      source_type: 'document'
      /** Title */
      title: string
    }
    /**
     * PublicResolvedScope
     * @description Reusable response projection; authorization still uses ResolvedScope.
     */
    PublicResolvedScope: {
      /** Documents */
      documents?: components['schemas']['PublicSourceManifest'][]
    }
    /** PublicShortAnswerQuestion */
    PublicShortAnswerQuestion: {
      /** Citation Refs */
      citation_refs: string[]
      /** Concept Ids */
      concept_ids: string[]
      /**
       * Difficulty
       * @enum {string}
       */
      difficulty: 'easy' | 'medium' | 'hard'
      /** Id */
      id: string
      /** Question Version */
      question_version: string
      /** Stem */
      stem: string
      /**
       * @description discriminator enum property added by openapi-typescript
       * @enum {string}
       */
      type: 'short_answer'
    }
    /**
     * PublicSourceManifest
     * @description Explicit public source identity; storage and worker metadata never enter it.
     */
    PublicSourceManifest: {
      /** Authorization Revision */
      authorization_revision: number
      /** Canonical Text Hash */
      canonical_text_hash: string
      /** Doc Id */
      doc_id: string
      /** Document Version Id */
      document_version_id: string
      /** Index Build Id */
      index_build_id: string
      /** Parse Artifact Id */
      parse_artifact_id: string
      /** Section Catalog Revision */
      section_catalog_revision?: string | null
      /** Section Ids */
      section_ids?: string[]
      /** Source Sha256 */
      source_sha256: string
      /**
       * Title
       * @default
       */
      title: string
    }
    /** PublicWebEvidence */
    PublicWebEvidence: {
      /** Evidence Id */
      evidence_id: string
      /** Excerpt */
      excerpt: string
      /**
       * Fetched At
       * Format: date-time
       */
      fetched_at: string
      locator: components['schemas']['WebLocator']
      /** Namespace */
      namespace: string
      /** Owner Id */
      owner_id: number
      /** Retrieval Scores */
      retrieval_scores?: {
        [key: string]: number
      }
      /** Score */
      score?: number | null
      /** Snapshot Hash */
      snapshot_hash: string
      /** Snapshot Id */
      snapshot_id: string
      /**
       * Source Type
       * @default web
       * @constant
       */
      source_type: 'web'
      /** Text Hash */
      text_hash: string
      /** Title */
      title: string
      /** Url */
      url: string
    }
    /** QaAnswerView */
    QaAnswerView: {
      /** Answer Id */
      answer_id: string
      /**
       * Answer Status
       * @enum {string}
       */
      answer_status:
        | 'answered'
        | 'partial'
        | 'needs_clarification'
        | 'insufficient_evidence'
        | 'conflicting_sources'
      /** Blocks */
      blocks: components['schemas']['AnswerBlock'][]
      /** Created At */
      created_at: string
      /** Evidence */
      evidence: components['schemas']['DocumentEvidence'][]
      /** Message Id */
      message_id: string
      /** Retrieval Query */
      retrieval_query: string
      /** Scope Revision */
      scope_revision: number
      /** Session Id */
      session_id: string
      /** Usage */
      usage?: {
        [key: string]: unknown
      }
    }
    /** QaFeedbackBody */
    QaFeedbackBody: {
      /**
       * Comment
       * @default
       */
      comment: string
      /**
       * Evaluation Consent
       * @default false
       */
      evaluation_consent: boolean
      /**
       * Rating
       * @enum {string}
       */
      rating: 'helpful' | 'unhelpful'
      /** Reason */
      reason?: ('incorrect' | 'unsupported' | 'incomplete' | 'other') | null
    }
    /** QaFeedbackView */
    QaFeedbackView: {
      /** Feedback Id */
      feedback_id: string
    }
    /**
     * QaHistoryTurn
     * @description A complete pair in this sample's source scope, bound by the eval runner.
     *
     *     Dataset authors cannot provide an arbitrary runtime scope fingerprint. A new
     *     sample/source scope is required for history from a different document set.
     */
    QaHistoryTurn: {
      /** Answer */
      answer: string
      /** Question */
      question: string
    }
    /** QaMessageCreate */
    QaMessageCreate: {
      /** Content */
      content: string
      /** Scope Revision */
      scope_revision: number
    }
    /** QaMessageList */
    QaMessageList: {
      /** Has More */
      has_more: boolean
      /** Items */
      items: components['schemas']['QaMessageView'][]
      /** Next Before */
      next_before?: number | null
    }
    /** QaMessageView */
    QaMessageView: {
      answer?: components['schemas']['QaAnswerView'] | null
      /** Content */
      content: string
      /** Created At */
      created_at: string
      /** Error Code */
      error_code?: string | null
      /** Message Id */
      message_id: string
      /**
       * Role
       * @enum {string}
       */
      role: 'user' | 'assistant'
      /** Scope Revision */
      scope_revision: number
      /** Sequence */
      sequence: number
      /** Session Id */
      session_id: string
      /**
       * Status
       * @enum {string}
       */
      status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled' | 'revoked'
      /** Task Id */
      task_id: string
    }
    /** QaSample */
    QaSample: {
      /** Annotation */
      annotation?: {
        [key: string]: unknown
      }
      /**
       * @description discriminator enum property added by openapi-typescript
       * @enum {string}
       */
      case_type: 'qa'
      /**
       * Expected Answer Status
       * @default null
       */
      expected_answer_status:
        | (
            | 'answered'
            | 'partial'
            | 'needs_clarification'
            | 'insufficient_evidence'
            | 'conflicting_sources'
          )
        | null
      /**
       * Expected Error Code
       * @default null
       */
      expected_error_code: string | null
      /** Family Ids */
      family_ids?: string[]
      /** Gold Evidence Groups */
      gold_evidence_groups?: {
        [key: string]: unknown
      }[]
      /** History */
      history?: components['schemas']['QaHistoryTurn'][]
      /** Question */
      question: string
      /** Sample Id */
      sample_id: string
      /**
       * Schema Version
       * @default 1
       */
      schema_version: string
      /** Source Refs */
      source_refs: {
        [key: string]: unknown
      }[]
      /**
       * Split
       * @enum {string}
       */
      split: 'dev' | 'judge_calibration' | 'locked_test'
      /** Tags */
      tags?: string[]
    } & {
      [key: string]: unknown
    }
    /** QaScopeUpdate */
    QaScopeUpdate: {
      /** Expected Revision */
      expected_revision: number
      scope: components['schemas']['RequestedScope']
    }
    /** QaSessionCreate */
    QaSessionCreate: {
      scope: components['schemas']['RequestedScope']
      /**
       * Title
       * @default 新的资料问答
       */
      title: string
    }
    /** QaSessionList */
    QaSessionList: {
      /** Items */
      items: components['schemas']['QaSessionView'][]
      /** Page */
      page: number
      /** Page Size */
      page_size: number
      /** Total */
      total: number
    }
    /** QaSessionView */
    QaSessionView: {
      /** Active Task Id */
      active_task_id?: string | null
      /** Created At */
      created_at: string
      scope?: components['schemas']['PublicResolvedScope'] | null
      /** Scope Revision */
      scope_revision: number
      /** Session Id */
      session_id: string
      /**
       * Source Status
       * @default active
       * @enum {string}
       */
      source_status: 'active' | 'revoked'
      /** Title */
      title: string
      /** Updated At */
      updated_at: string
    }
    /** QaTaskView */
    QaTaskView: {
      answer?: components['schemas']['QaAnswerView'] | null
      /** Error Code */
      error_code?: string | null
      /** Error Message */
      error_message?: string | null
      /** Execution Ms */
      execution_ms?: number | null
      /** Message Id */
      message_id: string
      /** Queue Ms */
      queue_ms?: number | null
      /** Session Id */
      session_id: string
      /**
       * Stage
       * @default queued
       */
      stage: string
      /**
       * Status
       * @enum {string}
       */
      status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
      /** Task Id */
      task_id: string
    }
    /** Question */
    Question: {
      /**
       * Answer
       * @description 正确答案的 key 列表
       */
      answer: string[]
      /**
       * Difficulty
       * @description 难度
       * @enum {string}
       */
      difficulty: 'easy' | 'medium' | 'hard'
      /**
       * Explanation
       * @description 详细讲解
       */
      explanation: string
      /**
       * Id
       * @description 题目编号，如 q1
       */
      id: string
      /**
       * Image Url
       * @description AI 生成的题目配图 URL（可选）
       */
      image_url?: string | null
      /**
       * Knowledge Point
       * @description 知识点标签
       */
      knowledge_point: string
      /**
       * Options
       * @description 选项列表
       */
      options: components['schemas']['QuestionOption'][]
      /**
       * Stem
       * @description 题干
       */
      stem: string
      /**
       * Type
       * @description 题型
       * @enum {string}
       */
      type: 'single' | 'multiple' | 'judge'
    }
    /** QuestionOption */
    QuestionOption: {
      /**
       * Key
       * @description 选项标识，如 A、B、C、D
       */
      key: string
      /**
       * Text
       * @description 选项文本
       */
      text: string
    }
    /** QuestionReview */
    QuestionReview: {
      /**
       * Comment
       * @default
       */
      comment: string
      decisions?: components['schemas']['SemanticDecisions']
      /** Question Id */
      question_id: string
    }
    /** QuestionView */
    QuestionView: {
      /** Citation Refs */
      citation_refs?: string[]
      /**
       * Difficulty
       * @default medium
       */
      difficulty: string
      /** Id */
      id: string
      /**
       * Image Status
       * @default not_requested
       */
      image_status: string
      /** Image Url */
      image_url?: string | null
      /**
       * Knowledge Point
       * @default
       */
      knowledge_point: string
      /** Options */
      options: components['schemas']['QuestionOption'][]
      /** Stem */
      stem: string
      /**
       * Type
       * @enum {string}
       */
      type: 'single' | 'multiple' | 'judge'
    }
    /** QuizArtifact */
    QuizArtifact: {
      /** Artifact Id */
      artifact_id: string
      /**
       * @description discriminator enum property added by openapi-typescript
       * @enum {string}
       */
      case_type: 'quiz'
      /** Effective Config */
      effective_config?: {
        [key: string]: unknown
      }
      evidence_pack: components['schemas']['EvidencePack']
      /**
       * Mode
       * @enum {string}
       */
      mode: 'production' | 'evaluation'
      /** Owner Id */
      owner_id: number
      /** Pipeline Config Hash */
      pipeline_config_hash: string
      /** Pipeline Version */
      pipeline_version: string
      /** Questions */
      questions: components['schemas']['ArtifactQuestion'][]
      /** Run Id */
      run_id: string
      /**
       * Schema Version
       * @default quiz-artifact.v1
       * @constant
       */
      schema_version: 'quiz-artifact.v1'
      /**
       * Source Status
       * @enum {string}
       */
      source_status: 'grounded' | 'model_only' | 'legacy_unverified'
      /** Summary */
      summary: string
      /** Title */
      title: string
      /** Trace */
      trace?: {
        [key: string]: unknown
      }[]
      usage: components['schemas']['Usage']
      validation: components['schemas']['ValidationResult']
    }
    /** QuizHistoryItem */
    QuizHistoryItem: {
      /** Accuracy */
      accuracy: number | null
      /** Answered Count */
      answered_count: number
      /** Created At */
      created_at: string
      /** Images Status */
      images_status: string
      /** Question Count */
      question_count: number
      /** Quiz Id */
      quiz_id: string
      /** Report Status */
      report_status: string
      /** Revision */
      revision: number
      /** Source Status */
      source_status: string
      /** Status */
      status: string
      /** Title */
      title: string
    }
    /** QuizHistoryList */
    QuizHistoryList: {
      /** Items */
      items: components['schemas']['QuizHistoryItem'][]
      /** Page */
      page: number
      /** Page Size */
      page_size: number
      /** Total */
      total: number
    }
    /** QuizSample */
    QuizSample: {
      /** Annotation */
      annotation?: {
        [key: string]: unknown
      }
      /**
       * @description discriminator enum property added by openapi-typescript
       * @enum {string}
       */
      case_type: 'quiz'
      /**
       * Expected Outcome
       * @enum {string}
       */
      expected_outcome: 'generate' | 'refuse'
      /** Family Ids */
      family_ids?: string[]
      /** Gold Evidence Groups */
      gold_evidence_groups?: {
        [key: string]: unknown
      }[]
      /** Question Count */
      question_count: number
      /** Sample Id */
      sample_id: string
      /**
       * Schema Version
       * @default 1
       */
      schema_version: string
      /**
       * Source Policy
       * @default strict_docs
       * @enum {string}
       */
      source_policy: 'topic' | 'strict_docs' | 'doc_plus_web'
      /** Source Refs */
      source_refs?: {
        [key: string]: unknown
      }[]
      /**
       * Split
       * @enum {string}
       */
      split: 'dev' | 'judge_calibration' | 'locked_test'
      /** Tags */
      tags?: string[]
      /** User Input */
      user_input: string
    } & {
      [key: string]: unknown
    }
    /** QuizView */
    QuizView: {
      /** Answer Records */
      answer_records: components['schemas']['AnswerView'][]
      /** Created At */
      created_at: string
      /** Images Status */
      images_status: string
      /** Questions */
      questions: components['schemas']['QuestionView'][]
      /** Quiz Id */
      quiz_id: string
      /** Report Status */
      report_status: string
      /** Revision */
      revision: number
      /** Source Policy */
      source_policy: string
      /** Source Scope */
      source_scope?: {
        [key: string]: unknown
      } | null
      /** Source Status */
      source_status: string
      /** Status */
      status: string
      /** Summary */
      summary: string
      /** Title */
      title: string
      /** User Input */
      user_input?: string | null
    }
    /** RecoverBody */
    RecoverBody: {
      /** Account */
      account: string
      /** New Password */
      new_password: string
      /** Recovery Code */
      recovery_code: string
    }
    /** ReferenceGrade */
    ReferenceGrade: {
      /**
       * Provenance
       * @enum {string}
       */
      provenance: 'synthetic_fixture' | 'human'
      /**
       * Score
       * @default null
       */
      score: string | null
      /**
       * Status
       * @enum {string}
       */
      status: 'graded' | 'needs_review' | 'failed' | 'cancelled'
    }
    /** RegisterBody */
    RegisterBody: {
      /** Account */
      account: string
      /**
       * Nickname
       * @default 学习者
       */
      nickname: string
      /** Password */
      password: string
    }
    /** ReindexBody */
    ReindexBody: {
      /**
       * Index Profile Id
       * @default legacy-char-v1
       * @enum {string}
       */
      index_profile_id: 'legacy-char-v1' | 'structure-v1'
    }
    /** ReportGenerateRequest */
    ReportGenerateRequest: {
      /** Answer Records */
      answer_records: components['schemas']['AnswerRecord'][]
      /** Questions */
      questions: components['schemas']['Question'][]
      /** Quiz Id */
      quiz_id: string
      /** Topic */
      topic: string
    }
    /** ReportRetryView */
    ReportRetryView: {
      /** Quiz Id */
      quiz_id: string
      /** Report Status */
      report_status: string
    }
    /** ReportText */
    ReportText: {
      /** Advice */
      advice?: string[]
      /** Mastered Points */
      mastered_points?: string[]
      /**
       * Share Quote
       * @default
       */
      share_quote: string
      /** Three Line Summary */
      three_line_summary?: string[]
      /** Weak Points */
      weak_points?: string[]
    }
    /** ReportView */
    ReportView: {
      /** Accuracy */
      accuracy: number
      /** Correct Count */
      correct_count: number
      /** Error Code */
      error_code?: string | null
      /** Quiz Id */
      quiz_id: string
      report?: components['schemas']['ReportText'] | null
      /** Report Status */
      report_status: string
      /** Total Questions */
      total_questions: number
      /** Weak Question Ids */
      weak_question_ids?: string[]
      /** Xp Awarded */
      xp_awarded: number
    }
    /** RequestedDocument */
    RequestedDocument: {
      /** Doc Id */
      doc_id: string
      /** Section Catalog Revision */
      section_catalog_revision?: string | null
      /** Section Ids */
      section_ids?: string[]
    }
    /** RequestedScope */
    RequestedScope: {
      /** Documents */
      documents: components['schemas']['RequestedDocument'][]
      /**
       * Type
       * @default selected_documents
       * @constant
       */
      type: 'selected_documents'
    }
    /** ResolvedScope */
    ResolvedScope: {
      /** Documents */
      documents?: components['schemas']['SourceManifest'][]
      /** Namespace */
      namespace: string
      /** Owner Id */
      owner_id: number
    }
    /** ResultList */
    ResultList: {
      /** Items */
      items: components['schemas']['ResultView'][]
      /** Total */
      total: number
    }
    /** ResultReview */
    ResultReview: {
      /**
       * Comment
       * @default
       */
      comment: string
      /** Expected Revision */
      expected_revision: number
      /** Question Reviews */
      question_reviews?: components['schemas']['QuestionReview'][]
      /**
       * Verdict
       * @enum {string}
       */
      verdict: 'pass' | 'fail' | 'uncertain'
    }
    /** ResultView */
    ResultView: {
      /** Artifact */
      artifact?: {
        [key: string]: unknown
      } | null
      /** Case Type */
      case_type: string
      /** Error Code */
      error_code?: string | null
      /** Metrics */
      metrics?: {
        [key: string]: components['schemas']['MetricValue']
      } | null
      /** Repeat Index */
      repeat_index: number
      /** Result Id */
      result_id: string
      /** Review */
      review?: {
        [key: string]: unknown
      } | null
      /**
       * Review Revision
       * @default 0
       */
      review_revision: number
      /** Sample */
      sample: {
        [key: string]: unknown
      }
      /** Sample Id */
      sample_id: string
      /** Status */
      status: string
    }
    /** RetrievalArtifact */
    RetrievalArtifact: {
      /**
       * @description discriminator enum property added by openapi-typescript
       * @enum {string}
       */
      case_type: 'retrieval'
      /** Evidence */
      evidence: (components['schemas']['DocumentEvidence'] | components['schemas']['WebEvidence'])[]
      /** Run Id */
      run_id: string
      /**
       * Schema Version
       * @default retrieval-artifact.v1
       * @constant
       */
      schema_version: 'retrieval-artifact.v1'
      /** Trace */
      trace?: {
        [key: string]: unknown
      }
      usage?: components['schemas']['Usage']
    }
    /** RetrievalSample */
    RetrievalSample: {
      /** Annotation */
      annotation?: {
        [key: string]: unknown
      }
      /**
       * @description discriminator enum property added by openapi-typescript
       * @enum {string}
       */
      case_type: 'retrieval'
      /** Family Ids */
      family_ids?: string[]
      /** Gold Evidence Groups */
      gold_evidence_groups?: {
        [key: string]: unknown
      }[]
      /** Query */
      query: string
      /** Sample Id */
      sample_id: string
      /**
       * Schema Version
       * @default 1
       */
      schema_version: string
      /** Source Refs */
      source_refs?: {
        [key: string]: unknown
      }[]
      /**
       * Split
       * @enum {string}
       */
      split: 'dev' | 'judge_calibration' | 'locked_test'
      /** Tags */
      tags?: string[]
    } & {
      [key: string]: unknown
    }
    /**
     * ReviewPracticeBody
     * @description The service derives space, scope, objectives, concepts and review origin.
     */
    ReviewPracticeBody: {
      /**
       * Difficulty
       * @default mixed
       * @enum {string}
       */
      difficulty: 'easy' | 'medium' | 'hard' | 'mixed'
      /** Expected Revisions */
      expected_revisions: {
        [key: string]: number
      }
      /**
       * Question Count
       * @default 5
       */
      question_count: number
      /** Question Types */
      question_types: ('cloze' | 'numeric' | 'short_answer')[]
      /** Review Task Ids */
      review_task_ids: string[]
    }
    /** ReviewQuizBody */
    ReviewQuizBody: {
      /**
       * Difficulty
       * @default mixed
       * @enum {string}
       */
      difficulty: 'easy' | 'medium' | 'hard' | 'mixed'
      /** Expected Revisions */
      expected_revisions: {
        [key: string]: number
      }
      /**
       * Question Count
       * @default 5
       */
      question_count: number
      /** Review Task Ids */
      review_task_ids: string[]
    }
    /** ReviewUpdateBody */
    ReviewUpdateBody: {
      /**
       * Action
       * @enum {string}
       */
      action: 'pause' | 'resume' | 'reschedule'
      /** Due At */
      due_at?: string | null
      /** Expected Revision */
      expected_revision: number
    }
    /** RubricCriterion */
    RubricCriterion: {
      /** Criterion Id */
      criterion_id: string
      /** Evidence Refs */
      evidence_refs: string[]
      /** Reference Point */
      reference_point: string
      /** Weight */
      weight: number | string
    }
    /** RunCostPreview */
    RunCostPreview: {
      /** Assumptions */
      assumptions: string[]
      /** Components */
      components: components['schemas']['CostPreviewComponent'][]
      /**
       * Currency
       * @default CNY
       * @constant
       */
      currency: 'CNY'
      /** First Attempt Cny */
      first_attempt_cny?: number | null
      /**
       * Method
       * @constant
       */
      method: 'configured_price_scenarios_v1'
      /**
       * Not A Bill
       * @default true
       * @constant
       */
      not_a_bill: true
      /** Planned Executions */
      planned_executions: number
      /** Pricing Version */
      pricing_version: string
      /** Repeat Count */
      repeat_count: number
      /** Retry Scenario Cny */
      retry_scenario_cny?: number | null
      /** Sample Count */
      sample_count: number
      /**
       * Status
       * @enum {string}
       */
      status: 'estimated' | 'unknown' | 'not_applicable'
    }
    /** RunCreate */
    RunCreate: {
      /** Dataset Id */
      dataset_id: string
      /** Dataset Version */
      dataset_version: number
      /**
       * Judge Profile Id
       * @default deterministic-v1
       * @enum {string}
       */
      judge_profile_id: 'deterministic-v1' | 'ragas-faithfulness-v1'
      /** Max Cost Cny */
      max_cost_cny: number
      /** Pipeline Id */
      pipeline_id: string
      /**
       * Repeat Count
       * @default 2
       */
      repeat_count: number
    }
    /** RunList */
    RunList: {
      /** Items */
      items: components['schemas']['RunView'][]
      /** Total */
      total: number
    }
    /** RunView */
    RunView: {
      /**
       * Comparison Eligible
       * @default false
       */
      comparison_eligible: boolean
      /** Created At */
      created_at: string
      /** Dataset Id */
      dataset_id: string
      /** Dataset Version */
      dataset_version: number
      /** Ineligibility Reasons */
      ineligibility_reasons?: string[]
      /** Manifest */
      manifest: {
        [key: string]: unknown
      }
      /** Max Cost Cny */
      max_cost_cny: number
      /** Pipeline Id */
      pipeline_id: string
      progress: components['schemas']['ProgressView']
      /**
       * Reserved Cny
       * @default 0
       */
      reserved_cny: number
      /** Run Id */
      run_id: string
      /**
       * Spent Cny
       * @default 0
       */
      spent_cny: number
      /** Status */
      status: string
      /** Stop Reason */
      stop_reason?: string | null
    }
    /** Section */
    Section: {
      /** End Char */
      end_char: number
      /** Heading Path */
      heading_path?: string[]
      /**
       * Level
       * @default 1
       */
      level: number
      /** Section Id */
      section_id: string
      /** Start Char */
      start_char: number
      /** Title */
      title: string
    }
    /** SectionView */
    SectionView: {
      /** Section Id */
      section_id: string
      /** Title */
      title: string
    }
    /** SemanticDecisions */
    SemanticDecisions: {
      /** Answer Correctness */
      answer_correctness?: boolean | null
      /** Citation Completeness */
      citation_completeness?: boolean | null
      /** Citation Support */
      citation_support?: boolean | null
      /** Distractor Quality */
      distractor_quality?: boolean | null
      /** Explanation Correctness */
      explanation_correctness?: boolean | null
      /** Scope Compliance */
      scope_compliance?: boolean | null
      /** Solvability */
      solvability?: boolean | null
      /** Source Support */
      source_support?: boolean | null
      /** Stem Premise Support */
      stem_premise_support?: boolean | null
    }
    /** SessionView */
    SessionView: {
      /** Csrf Token */
      csrf_token: string
      /** Recovery Code */
      recovery_code?: string | null
      user: components['schemas']['UserView']
    }
    /** ShortAnswer */
    ShortAnswer: {
      /** Text */
      text: string
      /**
       * @description discriminator enum property added by openapi-typescript
       * @enum {string}
       */
      type: 'short_answer'
    }
    /** ShortAnswerQuestion */
    ShortAnswerQuestion: {
      /** Citation Refs */
      citation_refs: string[]
      /** Concept Ids */
      concept_ids: string[]
      /**
       * Difficulty
       * @enum {string}
       */
      difficulty: 'easy' | 'medium' | 'hard'
      /** Id */
      id: string
      rubric: components['schemas']['ShortAnswerRubric']
      /** Stem */
      stem: string
      /** Support Quotes */
      support_quotes: string[]
      /**
       * @description discriminator enum property added by openapi-typescript
       * @enum {string}
       */
      type: 'short_answer'
    }
    /** ShortAnswerRubric */
    ShortAnswerRubric: {
      /** Criteria */
      criteria: components['schemas']['RubricCriterion'][]
      /** Explanation */
      explanation: string
      /** Reference Answer */
      reference_answer: string
      /**
       * Version
       * @default short-answer-v1
       * @constant
       */
      version: 'short-answer-v1'
    }
    /** SourceExcerptLocator */
    SourceExcerptLocator: {
      /** Block Id */
      block_id: string
      /** End Char */
      end_char: number
      /** Heading Level */
      heading_level?: number | null
      /** Heading Path */
      heading_path?: string[]
      /**
       * Kind
       * @enum {string}
       */
      kind: 'paragraph' | 'heading' | 'table_row' | 'page' | 'code'
      /** Line End */
      line_end?: number | null
      /** Line Start */
      line_start?: number | null
      /** Page */
      page?: number | null
      /** Paragraph */
      paragraph?: number | null
      /** Quote Hash */
      quote_hash: string
      /** Section Id */
      section_id: string
      /** Start Char */
      start_char: number
      /** Table Row */
      table_row?: number | null
    }
    /** SourceExcerptView */
    SourceExcerptView: {
      /** Block Id */
      block_id: string
      /** Blocks */
      blocks: components['schemas']['CanonicalBlock'][]
      /** Canonical Text Hash */
      canonical_text_hash: string
      /** Doc Id */
      doc_id: string
      /** Excerpt */
      excerpt: string
      locator: components['schemas']['SourceExcerptLocator']
      /** Parse Artifact Id */
      parse_artifact_id: string
      /** Sections */
      sections: components['schemas']['Section'][]
      /** Source Sha256 */
      source_sha256: string
      /** Version Id */
      version_id: string
    }
    /** SourceManifest */
    SourceManifest: {
      /** Attempt Id */
      attempt_id: string
      /** Authorization Revision */
      authorization_revision: number
      /**
       * Canonical Artifact Key
       * @default
       */
      canonical_artifact_key: string
      /** Canonical Text Hash */
      canonical_text_hash: string
      /** Doc Id */
      doc_id: string
      /** Document Version Id */
      document_version_id: string
      /** Index Build Id */
      index_build_id: string
      /**
       * Index Profile Hash
       * @default
       */
      index_profile_hash: string
      /**
       * Index Profile Id
       * @default legacy-char-v1
       */
      index_profile_id: string
      /** Namespace */
      namespace: string
      /** Owner Id */
      owner_id: number
      /** Parse Artifact Id */
      parse_artifact_id: string
      /**
       * Projection Key
       * @default
       */
      projection_key: string
      /**
       * Section Catalog Revision
       * @default null
       */
      section_catalog_revision: string | null
      /** Section Ids */
      section_ids?: string[]
      /** Source Sha256 */
      source_sha256: string
      /**
       * Title
       * @default
       */
      title: string
    }
    /** StudyConceptCreate */
    StudyConceptCreate: {
      /** Scope Revision */
      scope_revision?: number | null
      /** Title */
      title: string
    }
    /** StudyConceptList */
    StudyConceptList: {
      /** Items */
      items: components['schemas']['StudyConceptView'][]
    }
    /** StudyConceptProgressView */
    StudyConceptProgressView: {
      /** Concept Id */
      concept_id: string
      /** History Next Cursor */
      history_next_cursor: string | null
      /** Next Reviews */
      next_reviews: components['schemas']['StudyReviewView'][]
      /** Recent History */
      recent_history: components['schemas']['StudyHistoryView'][]
      /**
       * Source Status
       * @enum {string}
       */
      source_status: 'active' | 'revoked'
      /** Space Id */
      space_id: string
      /** States */
      states: components['schemas']['StudyConceptStateView'][]
      /** Title */
      title: string
    }
    /** StudyConceptStateView */
    StudyConceptStateView: {
      /** Assessment Set Hash */
      assessment_set_hash: string | null
      /** Due At */
      due_at: string | null
      /** Evidence Count */
      evidence_count: number
      /** Last Activity Local Date */
      last_activity_local_date: string | null
      /** Last Completion Id */
      last_completion_id: string | null
      /** Last Success Local Date */
      last_success_local_date: string | null
      /** Override Due At */
      override_due_at: string | null
      /** Paused */
      paused: boolean
      /** Revision */
      revision: number
      /** Rule Due At */
      rule_due_at: string | null
      /** Rule Version */
      rule_version: string
      /** Scope Revision */
      scope_revision: number
      /** Stage */
      stage: number
    }
    /** StudyConceptSummary */
    StudyConceptSummary: {
      /** Concept Id */
      concept_id: string
      /** Title */
      title: string
    }
    /** StudyConceptUpdate */
    StudyConceptUpdate: {
      /** Expected Revision */
      expected_revision: number
      /** Scope Revision */
      scope_revision?: number | null
      /** Title */
      title: string
    }
    /** StudyConceptView */
    StudyConceptView: {
      /** Concept Id */
      concept_id: string
      /**
       * Created At
       * Format: date-time
       */
      created_at: string
      /** Revision */
      revision: number
      /** Scope Revision */
      scope_revision: number
      /**
       * Source Status
       * @default active
       * @enum {string}
       */
      source_status: 'active' | 'revoked'
      /** Space Id */
      space_id: string
      /** Title */
      title: string
    }
    /** StudyGoalCreate */
    StudyGoalCreate: {
      /**
       * Daily Minutes
       * @default 30
       */
      daily_minutes: number
      /** Deadline */
      deadline?: string | null
      /** Scope Revision */
      scope_revision?: number | null
      /**
       * Status
       * @default planned
       * @enum {string}
       */
      status: 'planned' | 'active' | 'completed' | 'paused'
      /** Title */
      title: string
    }
    /** StudyGoalList */
    StudyGoalList: {
      /** Items */
      items: components['schemas']['StudyGoalView'][]
    }
    /** StudyGoalUpdate */
    StudyGoalUpdate: {
      /** Daily Minutes */
      daily_minutes?: number | null
      /** Deadline */
      deadline?: string | null
      /** Expected Revision */
      expected_revision: number
      /** Status */
      status?: ('planned' | 'active' | 'completed' | 'paused') | null
      /** Title */
      title?: string | null
    }
    /** StudyGoalView */
    StudyGoalView: {
      /**
       * Created At
       * Format: date-time
       */
      created_at: string
      /**
       * Daily Minutes
       * @default 30
       */
      daily_minutes: number
      /** Deadline */
      deadline?: string | null
      /** Goal Id */
      goal_id: string
      /** Revision */
      revision: number
      /** Scope Revision */
      scope_revision: number
      /**
       * Source Status
       * @default active
       * @enum {string}
       */
      source_status: 'active' | 'revoked'
      /** Space Id */
      space_id: string
      /**
       * Status
       * @default planned
       * @enum {string}
       */
      status: 'planned' | 'active' | 'completed' | 'paused'
      /** Title */
      title: string
      /**
       * Updated At
       * Format: date-time
       */
      updated_at: string
    }
    /** StudyHistoryList */
    StudyHistoryList: {
      /** Items */
      items: components['schemas']['StudyHistoryView'][]
      /** Next Cursor */
      next_cursor: string | null
    }
    /** StudyHistoryView */
    StudyHistoryView: {
      /** Assessment Set Hash */
      assessment_set_hash: string | null
      /** Attempted Count */
      attempted_count: number
      /** Completed At */
      completed_at: string | null
      /** Completion Id */
      completion_id: string | null
      /** Concepts */
      concepts: components['schemas']['StudyConceptSummary'][]
      /** Confirmed Count */
      confirmed_count: number
      /** Correct Count */
      correct_count: number
      /** Current Assessments */
      current_assessments: components['schemas']['PracticeAssessmentView'][]
      /** History Id */
      history_id: string
      /** Next Reviews */
      next_reviews: components['schemas']['StudyReviewView'][]
      /**
       * Occurred At
       * Format: date-time
       */
      occurred_at: string
      /** Origin Id */
      origin_id: string
      /**
       * Origin Kind
       * @enum {string}
       */
      origin_kind: 'quiz' | 'practice'
      /** Pending Count */
      pending_count: number
      /** Projection Revision */
      projection_revision: number | null
      /**
       * Projection Status
       * @enum {string}
       */
      projection_status: 'not_ready' | 'pending' | 'pending_assessments' | 'current' | 'failed'
      /** Question Count */
      question_count: number
      scope: components['schemas']['PublicResolvedScope'] | null
      /** Scope Revision */
      scope_revision: number | null
      /**
       * Source Status
       * @enum {string}
       */
      source_status: 'active' | 'revoked'
      /** Space Id */
      space_id: string | null
      /** Status */
      status: string
      /** Title */
      title: string
      /** Wrong Count */
      wrong_count: number
    }
    /** StudyQaPracticeContextView */
    StudyQaPracticeContextView: {
      /** Answer Id */
      answer_id: string
      /**
       * Answer Status
       * @enum {string}
       */
      answer_status: 'answered' | 'partial'
      /** Fact Blocks */
      fact_blocks: components['schemas']['AnswerBlock'][]
      /** Retrieval Query */
      retrieval_query: string
      scope: components['schemas']['PublicResolvedScope']
      /** Scope Revision */
      scope_revision: number
      /** Session Id */
      session_id: string
    }
    /** StudyQuizFromQaBody */
    StudyQuizFromQaBody: {
      /** Answer Id */
      answer_id: string
      /** Block Ids */
      block_ids: string[]
      /**
       * Difficulty
       * @default mixed
       * @enum {string}
       */
      difficulty: 'easy' | 'medium' | 'hard' | 'mixed'
      /** Objectives */
      objectives: components['schemas']['ObjectiveRef'][]
      /**
       * Question Count
       * @default 5
       */
      question_count: number
      /** Scope Revision */
      scope_revision: number
      /** Space Id */
      space_id: string
    }
    /** StudyReviewList */
    StudyReviewList: {
      /** Items */
      items: components['schemas']['StudyReviewView'][]
      /** Next Cursor */
      next_cursor: string | null
    }
    /** StudyReviewView */
    StudyReviewView: {
      /** Claimed At */
      claimed_at: string | null
      /** Completed At */
      completed_at: string | null
      /** Concept Id */
      concept_id: string
      /** Concept Title */
      concept_title: string
      /**
       * Due At
       * Format: date-time
       */
      due_at: string
      /** Is Current */
      is_current: boolean
      /** Last Error Code */
      last_error_code: string | null
      /** Origin Id */
      origin_id: string | null
      /** Origin Kind */
      origin_kind: ('quiz' | 'practice') | null
      /** Override Due At */
      override_due_at: string | null
      /** Paused */
      paused: boolean
      /** Review Task Id */
      review_task_id: string
      /** Revision */
      revision: number
      /** Rule Due At */
      rule_due_at: string | null
      /** Rule Version */
      rule_version: string
      /** Schedule Seq */
      schedule_seq: number
      /** Scope Revision */
      scope_revision: number
      /**
       * Source Status
       * @enum {string}
       */
      source_status: 'active' | 'revoked'
      /** Space Id */
      space_id: string
      /** Space Title */
      space_title: string
      /**
       * Status
       * @enum {string}
       */
      status: 'scheduled' | 'claimed' | 'running' | 'completed' | 'failed' | 'cancelled'
      /** Task Id */
      task_id: string | null
      /** Timezone */
      timezone: string
    }
    /** StudyScopeUpdate */
    StudyScopeUpdate: {
      /** Expected Revision */
      expected_revision: number
      scope: components['schemas']['RequestedScope']
    }
    /** StudyScopeView */
    StudyScopeView: {
      scope: components['schemas']['PublicResolvedScope']
      /** Scope Revision */
      scope_revision: number
      /** Space Id */
      space_id: string
    }
    /** StudySpaceCreate */
    StudySpaceCreate: {
      /** Answer Id */
      answer_id?: string | null
      scope?: components['schemas']['RequestedScope'] | null
      /**
       * Timezone
       * @default Asia/Shanghai
       */
      timezone: string
      /** Title */
      title: string
    }
    /** StudySpaceList */
    StudySpaceList: {
      /** Items */
      items: components['schemas']['StudySpaceView'][]
      /** Page */
      page: number
      /** Page Size */
      page_size: number
      /** Total */
      total: number
    }
    /** StudySpaceUpdate */
    StudySpaceUpdate: {
      /** Expected Revision */
      expected_revision: number
      /** Status */
      status?: ('active' | 'archived') | null
      /** Timezone */
      timezone?: string | null
      /** Title */
      title?: string | null
    }
    /** StudySpaceView */
    StudySpaceView: {
      /**
       * Created At
       * Format: date-time
       */
      created_at: string
      /** Revision */
      revision: number
      scope?: components['schemas']['PublicResolvedScope'] | null
      /** Scope Revision */
      scope_revision: number
      /**
       * Source Status
       * @default active
       * @enum {string}
       */
      source_status: 'active' | 'revoked'
      /** Space Id */
      space_id: string
      /**
       * Status
       * @enum {string}
       */
      status: 'active' | 'archived'
      /** Timezone */
      timezone: string
      /** Title */
      title: string
      /**
       * Updated At
       * Format: date-time
       */
      updated_at: string
    }
    /** StudyUnitCreate */
    StudyUnitCreate: {
      /** Position */
      position: number
      scope: components['schemas']['RequestedScope']
      /** Scope Revision */
      scope_revision: number
      /**
       * Status
       * @default planned
       * @enum {string}
       */
      status: 'planned' | 'active' | 'completed' | 'paused'
      /** Title */
      title: string
    }
    /** StudyUnitList */
    StudyUnitList: {
      /** Goal Revision */
      goal_revision: number
      /** Items */
      items: components['schemas']['StudyUnitView'][]
    }
    /** StudyUnitReorder */
    StudyUnitReorder: {
      /** Expected Revision */
      expected_revision: number
      /** Unit Ids */
      unit_ids: string[]
    }
    /** StudyUnitUpdate */
    StudyUnitUpdate: {
      /** Expected Revision */
      expected_revision: number
      /** Status */
      status?: ('planned' | 'active' | 'completed' | 'paused') | null
      /** Title */
      title?: string | null
    }
    /** StudyUnitView */
    StudyUnitView: {
      /**
       * Created At
       * Format: date-time
       */
      created_at: string
      /** Goal Id */
      goal_id: string
      /** Position */
      position: number
      /** Revision */
      revision: number
      scope: components['schemas']['RequestedScope'] | null
      /** Scope Revision */
      scope_revision: number
      /**
       * Source Status
       * @default active
       * @enum {string}
       */
      source_status: 'active' | 'revoked'
      /** Space Id */
      space_id: string
      /**
       * Status
       * @default planned
       * @enum {string}
       */
      status: 'planned' | 'active' | 'completed' | 'paused'
      /** Title */
      title: string
      /** Unit Id */
      unit_id: string
      /**
       * Updated At
       * Format: date-time
       */
      updated_at: string
    }
    /** StudyWrongQuestionList */
    StudyWrongQuestionList: {
      /** Items */
      items: components['schemas']['StudyWrongQuestionView'][]
      /** Next Cursor */
      next_cursor: string | null
    }
    /** StudyWrongQuestionView */
    StudyWrongQuestionView: {
      answer?: components['schemas']['JsonValue']
      /**
       * Association Status
       * @enum {string}
       */
      association_status: 'linked' | 'unlinked'
      /** Attempt Id */
      attempt_id: string | null
      /** Concepts */
      concepts: components['schemas']['StudyConceptSummary'][]
      /** Correct Answers */
      correct_answers: string[]
      current_assessment: components['schemas']['PracticeAssessmentView'] | null
      /**
       * Feedback
       * @default
       */
      feedback: string
      /**
       * Help Usage
       * @enum {string}
       */
      help_usage: 'none' | 'hints' | 'unknown'
      /** Item Id */
      item_id: string
      /** Next Reviews */
      next_reviews: components['schemas']['StudyReviewView'][]
      /**
       * Occurred At
       * Format: date-time
       */
      occurred_at: string
      /** Origin Id */
      origin_id: string
      /**
       * Origin Kind
       * @enum {string}
       */
      origin_kind: 'quiz' | 'practice'
      /**
       * Projection Status
       * @enum {string}
       */
      projection_status: 'not_ready' | 'pending' | 'pending_assessments' | 'current' | 'failed'
      /** Question */
      question:
        | components['schemas']['QuestionView']
        | (
            | components['schemas']['PublicClozeQuestion']
            | components['schemas']['PublicNumericQuestion']
            | components['schemas']['PublicShortAnswerQuestion']
          )
        | null
      /** Question Id */
      question_id: string
      /**
       * Question Type
       * @enum {string}
       */
      question_type: 'single' | 'multiple' | 'judge' | 'cloze' | 'numeric' | 'short_answer'
      /** Question Version */
      question_version: string | null
      /**
       * Result Status
       * @enum {string}
       */
      result_status: 'wrong' | 'partial'
      /** Scope Revision */
      scope_revision: number | null
      /**
       * Source Status
       * @enum {string}
       */
      source_status: 'active' | 'revoked'
      /** Space Id */
      space_id: string | null
    }
    /** TaskView */
    TaskView: {
      /** Error Code */
      error_code?: string | null
      /** Error Message */
      error_message?: string | null
      /** Quiz Id */
      quiz_id?: string | null
      result?: components['schemas']['QuizView'] | null
      /**
       * Stage
       * @default queued
       */
      stage: string
      /**
       * Status
       * @enum {string}
       */
      status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
      /** Task Id */
      task_id: string
    }
    /** UpdateProfileRequest */
    UpdateProfileRequest: {
      /** Avatar Url */
      avatar_url?: string | null
      /** Nickname */
      nickname?: string | null
    }
    /** Usage */
    Usage: {
      /**
       * Cost Status
       * @default unreported
       * @enum {string}
       */
      cost_status: 'unreported' | 'estimated' | 'reported'
      /**
       * Cost Usd
       * @default null
       */
      cost_usd: number | null
      /**
       * Embedding Calls
       * @default 0
       */
      embedding_calls: number
      /**
       * Embedding Tokens
       * @default 0
       */
      embedding_tokens: number
      /**
       * Fetch Calls
       * @default 0
       */
      fetch_calls: number
      /**
       * Input Tokens
       * @default 0
       */
      input_tokens: number
      /**
       * Llm Calls
       * @default 0
       */
      llm_calls: number
      /**
       * Output Tokens
       * @default 0
       */
      output_tokens: number
      /**
       * Reranker Calls
       * @default 0
       */
      reranker_calls: number
      /**
       * Search Calls
       * @default 0
       */
      search_calls: number
      /** Stage Ms */
      stage_ms?: {
        [key: string]: number
      }
      /**
       * Token Count Method
       * @default provider-reported-or-utf8-upper-bound-v1
       */
      token_count_method: string
    }
    /** UserBrief */
    UserBrief: {
      /** Avatar Url */
      avatar_url: string
      /** Id */
      id: number
      /** Nickname */
      nickname: string
      /** Total Xp */
      total_xp: number
    }
    /** UserProfile */
    UserProfile: {
      /** Avatar Url */
      avatar_url: string
      /** Average Accuracy */
      average_accuracy: number
      /** Correct Count */
      correct_count: number
      /** Id */
      id: number
      /** Nickname */
      nickname: string
      /** Quiz Count */
      quiz_count: number
      /** Total Xp */
      total_xp: number
    }
    /** UserView */
    UserView: {
      /** Avatar Url */
      avatar_url: string
      /** Id */
      id: number
      /** Nickname */
      nickname: string
      /**
       * Role
       * @default learner
       */
      role: string
      /** Total Xp */
      total_xp: number
    }
    /** ValidationError */
    ValidationError: {
      /** Context */
      ctx?: Record<string, never>
      /** Input */
      input?: unknown
      /** Location */
      loc: (string | number)[]
      /** Message */
      msg: string
      /** Error Type */
      type: string
    }
    /** ValidationResult */
    ValidationResult: {
      /** Errors */
      errors?: string[]
      /** Passed */
      passed: boolean
      /** @default null */
      provider_usage: components['schemas']['Usage'] | null
      /** Semantic Details */
      semantic_details?: {
        [key: string]: unknown
      }
      /**
       * Semantic Status
       * @default not_evaluated
       * @enum {string}
       */
      semantic_status: 'passed' | 'failed' | 'not_evaluated'
    }
    /** WebEvidence */
    WebEvidence: {
      /** Evidence Id */
      evidence_id: string
      /** Excerpt */
      excerpt: string
      /**
       * Fetched At
       * Format: date-time
       */
      fetched_at: string
      locator: components['schemas']['WebLocator']
      /** Namespace */
      namespace: string
      /** Owner Id */
      owner_id: number
      /** Retrieval Scores */
      retrieval_scores?: {
        [key: string]: number
      }
      /**
       * Score
       * @default null
       */
      score: number | null
      /**
       * Snapshot Artifact Key
       * @default
       */
      snapshot_artifact_key: string
      /** Snapshot Hash */
      snapshot_hash: string
      /** Snapshot Id */
      snapshot_id: string
      /**
       * @description discriminator enum property added by openapi-typescript
       * @enum {string}
       */
      source_type: 'web'
      /** Text Hash */
      text_hash: string
      /** Title */
      title: string
      /** Url */
      url: string
    }
    /** WebLocator */
    WebLocator: {
      /** Block Id */
      block_id: string
      /** End Char */
      end_char: number
      /** Quote Hash */
      quote_hash: string
      /** Start Char */
      start_char: number
    }
    /** CompleteBody */
    app__api__v1__routes__internal_eval__CompleteBody: {
      /** Attempt */
      attempt: number
      /** Judge Calls */
      judge_calls?: {
        [key: string]: unknown
      }[]
      /** Lease Token */
      lease_token: string
      /** Metrics */
      metrics: {
        [key: string]: {
          [key: string]: unknown
        }
      }
      /**
       * Status
       * @default completed
       */
      status: string
    }
    /** CompleteBody */
    app__models__learning__CompleteBody: {
      /** Expected Revision */
      expected_revision: number
    }
  }
  responses: never
  parameters: never
  requestBodies: never
  headers: never
  pathItems: never
}
export type $defs = Record<string, never>
export interface operations {
  bind_api_v1_auth_bind_post: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody: {
      content: {
        'application/json': components['schemas']['BindBody']
      }
    }
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_SessionView_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  capabilities_api_v1_auth_capabilities_get: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_AuthCapabilitiesView_']
        }
      }
    }
  }
  change_password_api_v1_auth_change_password_post: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody: {
      content: {
        'application/json': components['schemas']['PasswordBody']
      }
    }
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_dict_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  link_code_api_v1_auth_link_code_post: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_dict_']
        }
      }
    }
  }
  login_api_v1_auth_login_post: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody: {
      content: {
        'application/json': components['schemas']['LoginBody']
      }
    }
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_SessionView_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  logout_api_v1_auth_logout_post: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_dict_']
        }
      }
    }
  }
  recover_api_v1_auth_recover_post: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody: {
      content: {
        'application/json': components['schemas']['RecoverBody']
      }
    }
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_dict_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  register_api_v1_auth_register_post: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody: {
      content: {
        'application/json': components['schemas']['RegisterBody']
      }
    }
    responses: {
      /** @description Successful Response */
      201: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_SessionView_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  session_api_v1_auth_session_get: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_SessionView_']
        }
      }
    }
  }
  compare_api_v1_eval_compare_get: {
    parameters: {
      query: {
        baseline_run_id: string
        candidate_run_id: string
        exploratory?: boolean
        group?: string
      }
      header?: never
      path?: never
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_dict_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  list_datasets_api_v1_eval_datasets_get: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_DatasetList_']
        }
      }
    }
  }
  create_dataset_api_v1_eval_datasets_post: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody: {
      content: {
        'application/json': components['schemas']['DatasetCreate']
      }
    }
    responses: {
      /** @description Successful Response */
      201: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_DatasetView_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  get_dataset_api_v1_eval_datasets__dataset_id__versions__version__get: {
    parameters: {
      query?: never
      header?: never
      path: {
        dataset_id: string
        version: number
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_DatasetView_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  revoke_dataset_api_v1_eval_datasets__dataset_id__versions__version__delete: {
    parameters: {
      query?: never
      header?: never
      path: {
        dataset_id: string
        version: number
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_dict_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  edit_dataset_api_v1_eval_datasets__dataset_id__versions__version__patch: {
    parameters: {
      query?: never
      header?: never
      path: {
        dataset_id: string
        version: number
      }
      cookie?: never
    }
    requestBody: {
      content: {
        'application/json': components['schemas']['DatasetPatch']
      }
    }
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_DatasetView_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  freeze_dataset_api_v1_eval_datasets__dataset_id__versions__version__freeze_post: {
    parameters: {
      query?: never
      header?: never
      path: {
        dataset_id: string
        version: number
      }
      cookie?: never
    }
    requestBody: {
      content: {
        'application/json': components['schemas']['FreezeBody']
      }
    }
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_DatasetView_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  review_sample_api_v1_eval_datasets__dataset_id__versions__version__samples__sample_id__review_post: {
    parameters: {
      query?: never
      header?: never
      path: {
        dataset_id: string
        version: number
        sample_id: string
      }
      cookie?: never
    }
    requestBody: {
      content: {
        'application/json': components['schemas']['DatasetReview']
      }
    }
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_DatasetView_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  eval_list_api_v1_eval_documents_get: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_DocumentList_']
        }
      }
    }
  }
  eval_upload_api_v1_eval_documents_post: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody: {
      content: {
        'multipart/form-data': components['schemas']['Body_eval_upload_api_v1_eval_documents_post']
      }
    }
    responses: {
      /** @description Successful Response */
      202: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_DocumentView_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  eval_document_api_v1_eval_documents__doc_id__get: {
    parameters: {
      query?: never
      header?: never
      path: {
        doc_id: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_DocumentView_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  eval_delete_api_v1_eval_documents__doc_id__delete: {
    parameters: {
      query?: never
      header?: never
      path: {
        doc_id: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      202: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_DocumentDeletionView_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  eval_reindex_api_v1_eval_documents__doc_id__reindex_post: {
    parameters: {
      query?: never
      header?: never
      path: {
        doc_id: string
      }
      cookie?: never
    }
    requestBody: {
      content: {
        'application/json': components['schemas']['ReindexBody']
      }
    }
    responses: {
      /** @description Successful Response */
      202: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_DocumentView_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  eval_source_api_v1_eval_documents__doc_id__source_get: {
    parameters: {
      query: {
        version_id: string
        parse_artifact_id: string
        block_id?: string | null
        start_char?: number | null
        end_char?: number | null
      }
      header?: never
      path: {
        doc_id: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_SourceExcerptView_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  list_feedback_api_v1_eval_feedback_get: {
    parameters: {
      query?: {
        page?: number
        page_size?: number
      }
      header?: never
      path?: never
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_FeedbackList_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  promote_api_v1_eval_feedback__feedback_id__promote_post: {
    parameters: {
      query?: never
      header?: never
      path: {
        feedback_id: string
      }
      cookie?: never
    }
    requestBody: {
      content: {
        'application/json': components['schemas']['FeedbackPromote']
      }
    }
    responses: {
      /** @description Successful Response */
      202: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_PromotionView_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  review_api_v1_eval_feedback__feedback_id__review_put: {
    parameters: {
      query?: never
      header?: never
      path: {
        feedback_id: string
      }
      cookie?: never
    }
    requestBody: {
      content: {
        'application/json': components['schemas']['FeedbackReview']
      }
    }
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_FeedbackView_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  judges_api_v1_eval_judges_get: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_JudgeProfileList_']
        }
      }
    }
  }
  pipelines_api_v1_eval_pipelines_get: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_dict_']
        }
      }
    }
  }
  list_runs_api_v1_eval_runs_get: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_RunList_']
        }
      }
    }
  }
  create_run_api_v1_eval_runs_post: {
    parameters: {
      query?: never
      header: {
        'idempotency-key': string
      }
      path?: never
      cookie?: never
    }
    requestBody: {
      content: {
        'application/json': components['schemas']['RunCreate']
      }
    }
    responses: {
      /** @description Successful Response */
      202: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_RunView_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  estimate_run_api_v1_eval_runs_estimate_get: {
    parameters: {
      query: {
        dataset_id: string
        dataset_version: number
        pipeline_id: string
        repeat_count?: number
        judge_profile_id?: 'deterministic-v1' | 'ragas-faithfulness-v1'
      }
      header?: never
      path?: never
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_RunCostPreview_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  get_run_api_v1_eval_runs__run_id__get: {
    parameters: {
      query?: never
      header?: never
      path: {
        run_id: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_RunView_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  cancel_run_api_v1_eval_runs__run_id__cancel_post: {
    parameters: {
      query?: never
      header?: never
      path: {
        run_id: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_RunView_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  export_run_api_v1_eval_runs__run_id__export_get: {
    parameters: {
      query?: {
        format?: string
      }
      header?: never
      path: {
        run_id: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': unknown
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  get_results_api_v1_eval_runs__run_id__results_get: {
    parameters: {
      query?: never
      header?: never
      path: {
        run_id: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_ResultList_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  review_result_api_v1_eval_runs__run_id__results__result_id__review_put: {
    parameters: {
      query?: never
      header?: never
      path: {
        run_id: string
        result_id: string
      }
      cookie?: never
    }
    requestBody: {
      content: {
        'application/json': components['schemas']['ResultReview']
      }
    }
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_dict_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  resume_run_api_v1_eval_runs__run_id__resume_post: {
    parameters: {
      query?: never
      header?: never
      path: {
        run_id: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_RunView_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  health_check_api_v1_health_get: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': unknown
        }
      }
    }
  }
  claim_api_v1_internal_eval_scoring_claim_post: {
    parameters: {
      query?: never
      header?: {
        authorization?: string | null
      }
      path?: never
      cookie?: never
    }
    requestBody: {
      content: {
        'application/json': components['schemas']['ClaimBody']
      }
    }
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': unknown
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  calls_api_v1_internal_eval_scoring__result_id__calls_post: {
    parameters: {
      query?: never
      header?: {
        authorization?: string | null
      }
      path: {
        result_id: string
      }
      cookie?: never
    }
    requestBody: {
      content: {
        'application/json': components['schemas']['CallBody']
      }
    }
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': unknown
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  complete_api_v1_internal_eval_scoring__result_id__complete_post: {
    parameters: {
      query?: never
      header?: {
        authorization?: string | null
      }
      path: {
        result_id: string
      }
      cookie?: never
    }
    requestBody: {
      content: {
        'application/json': components['schemas']['app__api__v1__routes__internal_eval__CompleteBody']
      }
    }
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': unknown
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  fail_api_v1_internal_eval_scoring__result_id__fail_post: {
    parameters: {
      query?: never
      header?: {
        authorization?: string | null
      }
      path: {
        result_id: string
      }
      cookie?: never
    }
    requestBody: {
      content: {
        'application/json': components['schemas']['FailBody']
      }
    }
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': unknown
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  heartbeat_api_v1_internal_eval_scoring__result_id__heartbeat_post: {
    parameters: {
      query?: never
      header?: {
        authorization?: string | null
      }
      path: {
        result_id: string
      }
      cookie?: never
    }
    requestBody: {
      content: {
        'application/json': components['schemas']['HeartbeatBody']
      }
    }
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': unknown
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  listing_api_v1_knowledge_documents_get: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_DocumentList_']
        }
      }
    }
  }
  upload_api_v1_knowledge_documents_post: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody: {
      content: {
        'multipart/form-data': components['schemas']['Body_upload_api_v1_knowledge_documents_post']
      }
    }
    responses: {
      /** @description Successful Response */
      202: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_DocumentView_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  get_document_api_v1_knowledge_documents__doc_id__get: {
    parameters: {
      query?: never
      header?: never
      path: {
        doc_id: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_DocumentView_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  delete_api_v1_knowledge_documents__doc_id__delete: {
    parameters: {
      query?: never
      header?: never
      path: {
        doc_id: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      202: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_DocumentDeletionView_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  reindex_api_v1_knowledge_documents__doc_id__reindex_post: {
    parameters: {
      query?: never
      header?: never
      path: {
        doc_id: string
      }
      cookie?: never
    }
    requestBody: {
      content: {
        'application/json': components['schemas']['ReindexBody']
      }
    }
    responses: {
      /** @description Successful Response */
      202: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_DocumentView_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  source_api_v1_knowledge_documents__doc_id__source_get: {
    parameters: {
      query: {
        version_id: string
        parse_artifact_id: string
        block_id?: string | null
        start_char?: number | null
        end_char?: number | null
      }
      header?: never
      path: {
        doc_id: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_SourceExcerptView_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  version_api_v1_knowledge_documents__doc_id__versions_post: {
    parameters: {
      query?: never
      header?: never
      path: {
        doc_id: string
      }
      cookie?: never
    }
    requestBody: {
      content: {
        'multipart/form-data': components['schemas']['Body_version_api_v1_knowledge_documents__doc_id__versions_post']
      }
    }
    responses: {
      /** @description Successful Response */
      202: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_DocumentView_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  attempt_api_v1_practice_attempts__attempt_id__get: {
    parameters: {
      query?: never
      header?: never
      path: {
        attempt_id: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_PracticeAttemptView_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  retry_grading_api_v1_practice_attempts__attempt_id__retry_grading_post: {
    parameters: {
      query?: never
      header: {
        'idempotency-key': string
      }
      path: {
        attempt_id: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      202: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_PracticeTaskView_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  review_api_v1_practice_attempts__attempt_id__review_post: {
    parameters: {
      query?: never
      header: {
        'idempotency-key': string
      }
      path: {
        attempt_id: string
      }
      cookie?: never
    }
    requestBody: {
      content: {
        'application/json': components['schemas']['PracticeReviewBody']
      }
    }
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_AssessmentRef_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  review_context_api_v1_practice_attempts__attempt_id__review_context_get: {
    parameters: {
      query?: never
      header?: never
      path: {
        attempt_id: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_PracticeReviewContext_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  self_review_api_v1_practice_attempts__attempt_id__self_review_post: {
    parameters: {
      query?: never
      header: {
        'idempotency-key': string
      }
      path: {
        attempt_id: string
      }
      cookie?: never
    }
    requestBody: {
      content: {
        'application/json': components['schemas']['PracticeSelfReviewBody']
      }
    }
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_PracticeSelfReviewReceipt_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  cost_preview_api_v1_practice_cost_preview_post: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody: {
      content: {
        'application/json': components['schemas']['PracticeSpec']
      }
    }
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_PracticeCostPreview_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  generate_api_v1_practice_generate_async_post: {
    parameters: {
      query?: never
      header: {
        'idempotency-key': string
      }
      path?: never
      cookie?: never
    }
    requestBody: {
      content: {
        'application/json': components['schemas']['PracticeSpec']
      }
    }
    responses: {
      /** @description Successful Response */
      202: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_PracticeTaskView_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  review_job_api_v1_practice_review_jobs_post: {
    parameters: {
      query?: never
      header: {
        'idempotency-key': string
      }
      path?: never
      cookie?: never
    }
    requestBody: {
      content: {
        'application/json': components['schemas']['ReviewPracticeBody']
      }
    }
    responses: {
      /** @description Successful Response */
      202: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_PracticeTaskView_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  task_api_v1_practice_tasks__task_id__get: {
    parameters: {
      query?: never
      header?: never
      path: {
        task_id: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_PracticeTaskView_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  cancel_api_v1_practice_tasks__task_id__cancel_post: {
    parameters: {
      query?: never
      header?: never
      path: {
        task_id: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_PracticeTaskView_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  practice_api_v1_practice__practice_id__get: {
    parameters: {
      query?: never
      header?: never
      path: {
        practice_id: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_PracticeView_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  complete_api_v1_practice__practice_id__complete_post: {
    parameters: {
      query?: never
      header?: never
      path: {
        practice_id: string
      }
      cookie?: never
    }
    requestBody: {
      content: {
        'application/json': components['schemas']['PracticeCompleteBody']
      }
    }
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_PracticeCompletionReceipt_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  submit_answer_api_v1_practice__practice_id__questions__question_id__attempts_post: {
    parameters: {
      query?: never
      header: {
        'idempotency-key': string
      }
      path: {
        practice_id: string
        question_id: string
      }
      cookie?: never
    }
    requestBody: {
      content: {
        'application/json': components['schemas']['PracticeAnswerBody']
      }
    }
    responses: {
      /** @description Successful Response */
      201: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_PracticeSubmissionReceipt_']
        }
      }
      /** @description Accepted */
      202: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_PracticeSubmissionReceipt_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  evidence_api_v1_practice__practice_id__questions__question_id__evidence__evidence_id__get: {
    parameters: {
      query?: never
      header?: never
      path: {
        practice_id: string
        question_id: string
        evidence_id: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_PublicPracticeEvidence_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  help_used_api_v1_practice__practice_id__questions__question_id__help_post: {
    parameters: {
      query?: never
      header?: never
      path: {
        practice_id: string
        question_id: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_PracticeHelpView_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  evidence_api_v1_qa_answers__answer_id__evidence__evidence_id__get: {
    parameters: {
      query?: never
      header?: never
      path: {
        answer_id: string
        evidence_id: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_DocumentEvidence_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  feedback_api_v1_qa_answers__answer_id__feedback_post: {
    parameters: {
      query?: never
      header?: never
      path: {
        answer_id: string
      }
      cookie?: never
    }
    requestBody: {
      content: {
        'application/json': components['schemas']['QaFeedbackBody']
      }
    }
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_QaFeedbackView_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  sessions_api_v1_qa_sessions_get: {
    parameters: {
      query?: {
        page?: number
        page_size?: number
      }
      header?: never
      path?: never
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_QaSessionList_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  create_session_api_v1_qa_sessions_post: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody: {
      content: {
        'application/json': components['schemas']['QaSessionCreate']
      }
    }
    responses: {
      /** @description Successful Response */
      201: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_QaSessionView_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  session_api_v1_qa_sessions__session_id__get: {
    parameters: {
      query?: never
      header?: never
      path: {
        session_id: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_QaSessionView_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  messages_api_v1_qa_sessions__session_id__messages_get: {
    parameters: {
      query?: {
        before_sequence?: number | null
        page_size?: number
      }
      header?: never
      path: {
        session_id: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_QaMessageList_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  create_message_api_v1_qa_sessions__session_id__messages_post: {
    parameters: {
      query?: never
      header: {
        'idempotency-key': string
      }
      path: {
        session_id: string
      }
      cookie?: never
    }
    requestBody: {
      content: {
        'application/json': components['schemas']['QaMessageCreate']
      }
    }
    responses: {
      /** @description Successful Response */
      202: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_QaTaskView_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  scope_api_v1_qa_sessions__session_id__scope_patch: {
    parameters: {
      query?: never
      header?: never
      path: {
        session_id: string
      }
      cookie?: never
    }
    requestBody: {
      content: {
        'application/json': components['schemas']['QaScopeUpdate']
      }
    }
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_QaSessionView_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  task_api_v1_qa_tasks__task_id__get: {
    parameters: {
      query?: never
      header?: never
      path: {
        task_id: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_QaTaskView_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  cancel_api_v1_qa_tasks__task_id__cancel_post: {
    parameters: {
      query?: never
      header?: never
      path: {
        task_id: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_QaTaskView_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  legacy_generate_api_v1_quiz_generate_post: {
    parameters: {
      query?: never
      header: {
        'idempotency-key': string
      }
      path?: never
      cookie?: never
    }
    requestBody: {
      content: {
        'application/json': components['schemas']['GenerateBody']
      }
    }
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_Union_QuizView__TaskView__']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  create_api_v1_quiz_generate_async_post: {
    parameters: {
      query?: never
      header: {
        'idempotency-key': string
      }
      path?: never
      cookie?: never
    }
    requestBody: {
      content: {
        'application/json': components['schemas']['GenerateBody']
      }
    }
    responses: {
      /** @description Successful Response */
      202: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_TaskView_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  get_task_api_v1_quiz_task__task_id__get: {
    parameters: {
      query?: never
      header?: never
      path: {
        task_id: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_TaskView_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  cancel_task_api_v1_quiz_task__task_id__cancel_post: {
    parameters: {
      query?: never
      header?: never
      path: {
        task_id: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_TaskView_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  answer_api_v1_quiz__quiz_id__answers__question_id__put: {
    parameters: {
      query?: never
      header?: never
      path: {
        quiz_id: string
        question_id: string
      }
      cookie?: never
    }
    requestBody: {
      content: {
        'application/json': components['schemas']['AnswerBody']
      }
    }
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_AnswerReceipt_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  complete_api_v1_quiz__quiz_id__complete_post: {
    parameters: {
      query?: never
      header?: never
      path: {
        quiz_id: string
      }
      cookie?: never
    }
    requestBody: {
      content: {
        'application/json': components['schemas']['app__models__learning__CompleteBody']
      }
    }
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_CompletionReceipt_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  evidence_api_v1_quiz__quiz_id__evidence__evidence_id__get: {
    parameters: {
      query?: never
      header?: never
      path: {
        quiz_id: string
        evidence_id: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_Union_DocumentEvidence__PublicWebEvidence__']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  create_api_v1_quiz__quiz_id__feedback_post: {
    parameters: {
      query?: never
      header?: never
      path: {
        quiz_id: string
      }
      cookie?: never
    }
    requestBody: {
      content: {
        'application/json': components['schemas']['FeedbackCreate']
      }
    }
    responses: {
      /** @description Successful Response */
      201: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_FeedbackView_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  readiness_api_v1_ready_get: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': unknown
        }
      }
    }
  }
  legacy_report_api_v1_report_generate_post: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody: {
      content: {
        'application/json': components['schemas']['ReportGenerateRequest']
      }
    }
    responses: {
      /** @description Successful Response */
      202: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_ReportView_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  get_report_api_v1_report__quiz_id__get: {
    parameters: {
      query?: never
      header?: never
      path: {
        quiz_id: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_ReportView_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  retry_api_v1_report__quiz_id__retry_post: {
    parameters: {
      query?: never
      header?: {
        'idempotency-key'?: string | null
      }
      path: {
        quiz_id: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      202: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_ReportRetryView_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  update_concept_api_v1_study_concepts__concept_id__patch: {
    parameters: {
      query?: never
      header?: never
      path: {
        concept_id: string
      }
      cookie?: never
    }
    requestBody: {
      content: {
        'application/json': components['schemas']['StudyConceptUpdate']
      }
    }
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_StudyConceptView_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  concept_progress_api_v1_study_concepts__concept_id__progress_get: {
    parameters: {
      query?: never
      header?: never
      path: {
        concept_id: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_StudyConceptProgressView_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  update_goal_api_v1_study_goals__goal_id__patch: {
    parameters: {
      query?: never
      header?: never
      path: {
        goal_id: string
      }
      cookie?: never
    }
    requestBody: {
      content: {
        'application/json': components['schemas']['StudyGoalUpdate']
      }
    }
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_StudyGoalView_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  list_units_api_v1_study_goals__goal_id__units_get: {
    parameters: {
      query?: never
      header?: never
      path: {
        goal_id: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_StudyUnitList_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  create_unit_api_v1_study_goals__goal_id__units_post: {
    parameters: {
      query?: never
      header?: never
      path: {
        goal_id: string
      }
      cookie?: never
    }
    requestBody: {
      content: {
        'application/json': components['schemas']['StudyUnitCreate']
      }
    }
    responses: {
      /** @description Successful Response */
      201: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_StudyUnitView_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  reorder_units_api_v1_study_goals__goal_id__units_order_patch: {
    parameters: {
      query?: never
      header?: never
      path: {
        goal_id: string
      }
      cookie?: never
    }
    requestBody: {
      content: {
        'application/json': components['schemas']['StudyUnitReorder']
      }
    }
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_StudyUnitList_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  learning_history_api_v1_study_history_get: {
    parameters: {
      query?: {
        space_id?: string | null
        concept_id?: string | null
        scope_revision?: number | null
        status?: string | null
        origin_kind?: ('quiz' | 'practice') | null
        cursor?: string | null
        limit?: number
      }
      header?: never
      path?: never
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_StudyHistoryList_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  practice_context_api_v1_study_qa_answers__answer_id__practice_context_get: {
    parameters: {
      query?: never
      header?: never
      path: {
        answer_id: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_StudyQaPracticeContextView_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  create_quiz_from_qa_api_v1_study_quiz_jobs_from_qa_post: {
    parameters: {
      query?: never
      header: {
        'idempotency-key': string
      }
      path?: never
      cookie?: never
    }
    requestBody: {
      content: {
        'application/json': components['schemas']['StudyQuizFromQaBody']
      }
    }
    responses: {
      /** @description Successful Response */
      202: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_TaskView_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  start_review_quiz_api_v1_study_review_quiz_jobs_post: {
    parameters: {
      query?: never
      header: {
        'idempotency-key': string
      }
      path?: never
      cookie?: never
    }
    requestBody: {
      content: {
        'application/json': components['schemas']['ReviewQuizBody']
      }
    }
    responses: {
      /** @description Successful Response */
      202: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_TaskView_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  due_reviews_api_v1_study_reviews_get: {
    parameters: {
      query?: {
        space_id?: string | null
        concept_id?: string | null
        due_before?: string | null
        status?: ('scheduled' | 'claimed' | 'running' | 'failed' | 'cancelled') | null
        paused?: boolean
        cursor?: string | null
        limit?: number
      }
      header?: never
      path?: never
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_StudyReviewList_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  update_review_api_v1_study_reviews__review_id__patch: {
    parameters: {
      query?: never
      header?: never
      path: {
        review_id: string
      }
      cookie?: never
    }
    requestBody: {
      content: {
        'application/json': components['schemas']['ReviewUpdateBody']
      }
    }
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_StudyReviewView_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  list_spaces_api_v1_study_spaces_get: {
    parameters: {
      query?: {
        page?: number
        page_size?: number
        status?: ('active' | 'archived') | null
      }
      header?: never
      path?: never
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_StudySpaceList_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  create_space_api_v1_study_spaces_post: {
    parameters: {
      query?: never
      header: {
        'idempotency-key': string
      }
      path?: never
      cookie?: never
    }
    requestBody: {
      content: {
        'application/json': components['schemas']['StudySpaceCreate']
      }
    }
    responses: {
      /** @description Successful Response */
      201: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_StudySpaceView_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  get_space_api_v1_study_spaces__space_id__get: {
    parameters: {
      query?: never
      header?: never
      path: {
        space_id: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_StudySpaceView_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  update_space_api_v1_study_spaces__space_id__patch: {
    parameters: {
      query?: never
      header?: never
      path: {
        space_id: string
      }
      cookie?: never
    }
    requestBody: {
      content: {
        'application/json': components['schemas']['StudySpaceUpdate']
      }
    }
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_StudySpaceView_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  list_concepts_api_v1_study_spaces__space_id__concepts_get: {
    parameters: {
      query?: never
      header?: never
      path: {
        space_id: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_StudyConceptList_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  create_concept_api_v1_study_spaces__space_id__concepts_post: {
    parameters: {
      query?: never
      header?: never
      path: {
        space_id: string
      }
      cookie?: never
    }
    requestBody: {
      content: {
        'application/json': components['schemas']['StudyConceptCreate']
      }
    }
    responses: {
      /** @description Successful Response */
      201: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_StudyConceptView_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  list_goals_api_v1_study_spaces__space_id__goals_get: {
    parameters: {
      query?: never
      header?: never
      path: {
        space_id: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_StudyGoalList_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  create_goal_api_v1_study_spaces__space_id__goals_post: {
    parameters: {
      query?: never
      header?: never
      path: {
        space_id: string
      }
      cookie?: never
    }
    requestBody: {
      content: {
        'application/json': components['schemas']['StudyGoalCreate']
      }
    }
    responses: {
      /** @description Successful Response */
      201: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_StudyGoalView_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  change_scope_api_v1_study_spaces__space_id__scope_patch: {
    parameters: {
      query?: never
      header?: never
      path: {
        space_id: string
      }
      cookie?: never
    }
    requestBody: {
      content: {
        'application/json': components['schemas']['StudyScopeUpdate']
      }
    }
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_StudySpaceView_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  get_scope_api_v1_study_spaces__space_id__scopes__scope_revision__get: {
    parameters: {
      query?: never
      header?: never
      path: {
        space_id: string
        scope_revision: number
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_StudyScopeView_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  update_unit_api_v1_study_units__unit_id__patch: {
    parameters: {
      query?: never
      header?: never
      path: {
        unit_id: string
      }
      cookie?: never
    }
    requestBody: {
      content: {
        'application/json': components['schemas']['StudyUnitUpdate']
      }
    }
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_StudyUnitView_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  wrong_questions_api_v1_study_wrong_questions_get: {
    parameters: {
      query?: {
        space_id?: string | null
        concept_id?: string | null
        question_type?:
          | ('single' | 'multiple' | 'judge' | 'cloze' | 'numeric' | 'short_answer')
          | null
        status?: ('wrong' | 'partial') | null
        association_status?: ('linked' | 'unlinked') | null
        origin_kind?: ('quiz' | 'practice') | null
        cursor?: string | null
        limit?: number
      }
      header?: never
      path?: never
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_StudyWrongQuestionList_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  get_asset_api_v1_user_assets__asset_id__get: {
    parameters: {
      query?: never
      header?: never
      path: {
        asset_id: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': unknown
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  upload_avatar_api_v1_user_avatar_post: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody: {
      content: {
        'multipart/form-data': components['schemas']['Body_upload_avatar_api_v1_user_avatar_post']
      }
    }
    responses: {
      /** @description Successful Response */
      201: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_AvatarUploadResponse_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  login_api_v1_user_login_post: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody: {
      content: {
        'application/json': components['schemas']['LoginRequest']
      }
    }
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_LoginResponse_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  get_profile_api_v1_user_profile_get: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_UserProfile_']
        }
      }
    }
  }
  update_profile_api_v1_user_profile_put: {
    parameters: {
      query?: never
      header?: never
      path?: never
      cookie?: never
    }
    requestBody: {
      content: {
        'application/json': components['schemas']['UpdateProfileRequest']
      }
    }
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_NoneType_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  get_quiz_list_api_v1_user_quizzes_get: {
    parameters: {
      query?: {
        page?: number
        page_size?: number
      }
      header?: never
      path?: never
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_QuizHistoryList_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
  get_quiz_detail_api_v1_user_quizzes__quiz_id__get: {
    parameters: {
      query?: never
      header?: never
      path: {
        quiz_id: string
      }
      cookie?: never
    }
    requestBody?: never
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['ApiResponse_QuizView_']
        }
      }
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown
        }
        content: {
          'application/json': components['schemas']['HTTPValidationError']
        }
      }
    }
  }
}
