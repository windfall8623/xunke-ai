-- Course goals, objective assessment links and separate text application attempts.
-- Both application kinds exceed the original 24-character job kind column.
ALTER TABLE quiz_tasks MODIFY kind VARCHAR(40) NOT NULL DEFAULT 'quiz';

-- @column learning_courses criteria_revision
ALTER TABLE learning_courses ADD criteria_revision INT NOT NULL DEFAULT 1;

CREATE TABLE IF NOT EXISTS learning_course_criteria (
 course_criterion_id VARCHAR(64) NOT NULL, criteria_revision INT NOT NULL,
 course_id VARCHAR(64) NOT NULL, owner_id BIGINT UNSIGNED NOT NULL,
 course_criterion_ref VARCHAR(80) NOT NULL, position INT NOT NULL,
 description TEXT NULL, evidence_type VARCHAR(24) NOT NULL, expectation TEXT NULL,
 definition_hash CHAR(64) NOT NULL, lesson_ids_json JSON NOT NULL,
 requirements_json JSON NOT NULL, origin VARCHAR(24) NOT NULL,
 revoked_at DATETIME(6) NULL, created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 PRIMARY KEY (course_criterion_id,criteria_revision),
 UNIQUE KEY uk_course_criterion_owner (course_criterion_id,criteria_revision,course_id,owner_id),
 UNIQUE KEY uk_course_criterion_ref (course_id,criteria_revision,course_criterion_ref),
 KEY idx_course_criteria_current (course_id,owner_id,criteria_revision,position),
 FOREIGN KEY (course_id,owner_id) REFERENCES learning_courses(course_id,owner_id),
 CONSTRAINT ck_course_criterion_revision CHECK (criteria_revision>=1 AND position>=0),
 CONSTRAINT ck_course_criterion_type CHECK (evidence_type IN ('recognition','recall','application','explanation','creation')),
 CONSTRAINT ck_course_criterion_origin CHECK (origin IN ('generated_v2','legacy_unmapped'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS learning_course_assessments (
 course_assessment_id VARCHAR(64) PRIMARY KEY, course_id VARCHAR(64) NOT NULL,
 owner_id BIGINT UNSIGNED NOT NULL, criteria_revision INT NOT NULL,
 course_revision INT NOT NULL, source_policy VARCHAR(24) NOT NULL,
 scope_json JSON NULL, scope_fingerprint CHAR(64) NOT NULL, snapshot_json JSON NULL,
 task_id VARCHAR(64) COLLATE utf8mb4_unicode_ci NOT NULL,
 quiz_id VARCHAR(64) COLLATE utf8mb4_unicode_ci NULL,
 application_generation_task_id VARCHAR(64) COLLATE utf8mb4_unicode_ci NULL,
 status VARCHAR(24) NOT NULL DEFAULT 'generating', revision INT NOT NULL DEFAULT 1,
 idempotency_key VARCHAR(128) NOT NULL, request_hash CHAR(64) NOT NULL,
 completion_key VARCHAR(128) NULL, completion_hash CHAR(64) NULL,
 completion_json JSON NULL, completed_at DATETIME(6) NULL, revoked_at DATETIME(6) NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 UNIQUE KEY uk_course_assessment_owner (course_assessment_id,course_id,owner_id),
 UNIQUE KEY uk_course_assessment_key (owner_id,idempotency_key),
 UNIQUE KEY uk_course_assessment_completion_key (owner_id,completion_key),
 UNIQUE KEY uk_course_assessment_task (task_id,owner_id),
 UNIQUE KEY uk_course_assessment_quiz (quiz_id,owner_id),
 KEY idx_course_assessment_history (course_id,owner_id,created_at),
 FOREIGN KEY (course_id,owner_id) REFERENCES learning_courses(course_id,owner_id),
 FOREIGN KEY (task_id,owner_id) REFERENCES quiz_tasks(task_id,user_id),
 FOREIGN KEY (quiz_id,owner_id) REFERENCES quiz_sessions(quiz_id,user_id),
 FOREIGN KEY (application_generation_task_id,owner_id) REFERENCES quiz_tasks(task_id,user_id),
 CONSTRAINT ck_course_assessment_revision CHECK (criteria_revision>=1 AND course_revision>=1 AND revision>=1),
 CONSTRAINT ck_course_assessment_status CHECK (status IN ('generating','ready','in_progress','completed','failed','cancelled','source_revoked')),
 CONSTRAINT ck_course_assessment_policy CHECK (source_policy IN ('topic','strict_docs'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS learning_course_assessment_questions (
 course_assessment_id VARCHAR(64) NOT NULL, course_id VARCHAR(64) NOT NULL,
 owner_id BIGINT UNSIGNED NOT NULL,
 quiz_id VARCHAR(64) COLLATE utf8mb4_unicode_ci NOT NULL,
 question_id VARCHAR(64) COLLATE utf8mb4_unicode_ci NOT NULL,
 question_version CHAR(64) NOT NULL, course_criterion_id VARCHAR(64) NOT NULL,
 criteria_revision INT NOT NULL, evidence_type VARCHAR(24) NOT NULL DEFAULT 'recognition',
 settlement_json JSON NULL, settled_at DATETIME(6) NULL,
 PRIMARY KEY (course_assessment_id,question_id,course_criterion_id),
 KEY idx_course_assessment_question_quiz (quiz_id,owner_id,question_id),
 FOREIGN KEY (course_assessment_id,course_id,owner_id)
  REFERENCES learning_course_assessments(course_assessment_id,course_id,owner_id),
 FOREIGN KEY (course_criterion_id,criteria_revision,course_id,owner_id)
  REFERENCES learning_course_criteria(course_criterion_id,criteria_revision,course_id,owner_id),
 FOREIGN KEY (quiz_id,owner_id) REFERENCES quiz_sessions(quiz_id,user_id),
 CONSTRAINT ck_course_assessment_question_type CHECK (evidence_type='recognition')
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS learning_course_application_tasks (
 application_task_id VARCHAR(64) PRIMARY KEY,
 course_assessment_id VARCHAR(64) NOT NULL, course_id VARCHAR(64) NOT NULL,
 owner_id BIGINT UNSIGNED NOT NULL,
 generation_task_id VARCHAR(64) COLLATE utf8mb4_unicode_ci NOT NULL,
 application_ref VARCHAR(80) NOT NULL, position INT NOT NULL, revision INT NOT NULL DEFAULT 1,
 question_version CHAR(64) NOT NULL, draft_json JSON NULL, evidence_json JSON NULL,
 course_criterion_ids_json JSON NOT NULL, revoked_at DATETIME(6) NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 UNIQUE KEY uk_course_application_owner (application_task_id,course_assessment_id,course_id,owner_id),
 UNIQUE KEY uk_course_application_ref (generation_task_id,application_ref),
 KEY idx_course_application_session (course_assessment_id,owner_id,position),
 FOREIGN KEY (course_assessment_id,course_id,owner_id)
  REFERENCES learning_course_assessments(course_assessment_id,course_id,owner_id),
 FOREIGN KEY (generation_task_id,owner_id) REFERENCES quiz_tasks(task_id,user_id),
 CONSTRAINT ck_course_application_position CHECK (position>=0 AND position<2 AND revision>=1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS learning_course_application_attempts (
 attempt_id VARCHAR(64) PRIMARY KEY, application_task_id VARCHAR(64) NOT NULL,
 course_assessment_id VARCHAR(64) NOT NULL, course_id VARCHAR(64) NOT NULL,
 owner_id BIGINT UNSIGNED NOT NULL, question_version CHAR(64) NOT NULL,
 answer_text TEXT NULL, help_usage VARCHAR(16) NOT NULL DEFAULT 'unknown',
 help_usage_source VARCHAR(24) NOT NULL DEFAULT 'unknown', revision INT NOT NULL DEFAULT 1,
 feedback_task_id VARCHAR(64) COLLATE utf8mb4_unicode_ci NULL,
 active_task_id VARCHAR(64) COLLATE utf8mb4_unicode_ci NULL,
 latest_assessment_id VARCHAR(64) NULL,
 idempotency_key VARCHAR(128) NOT NULL, request_hash CHAR(64) NOT NULL,
 revoked_at DATETIME(6) NULL, saved_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 UNIQUE KEY uk_course_application_attempt_owner (attempt_id,course_assessment_id,course_id,owner_id),
 UNIQUE KEY uk_course_application_attempt_grade (attempt_id,owner_id),
 UNIQUE KEY uk_course_application_attempt_key (owner_id,idempotency_key),
 KEY idx_course_application_attempt_history (application_task_id,owner_id,saved_at),
 FOREIGN KEY (application_task_id,course_assessment_id,course_id,owner_id)
  REFERENCES learning_course_application_tasks(application_task_id,course_assessment_id,course_id,owner_id),
 FOREIGN KEY (feedback_task_id,owner_id) REFERENCES quiz_tasks(task_id,user_id),
 FOREIGN KEY (active_task_id,owner_id) REFERENCES quiz_tasks(task_id,user_id),
 CONSTRAINT ck_course_application_attempt_help CHECK (help_usage IN ('none','hints','unknown')),
 CONSTRAINT ck_course_application_attempt_help_source CHECK (help_usage_source IN ('learner_declaration','unknown')),
 CONSTRAINT ck_course_application_attempt_revision CHECK (revision>=1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS learning_course_application_assessments (
 assessment_id VARCHAR(64) PRIMARY KEY, attempt_id VARCHAR(64) NOT NULL,
 course_assessment_id VARCHAR(64) NOT NULL, course_id VARCHAR(64) NOT NULL,
 owner_id BIGINT UNSIGNED NOT NULL,
 origin_task_id VARCHAR(64) COLLATE utf8mb4_unicode_ci NULL,
 question_version CHAR(64) NOT NULL, rubric_hash CHAR(64) NOT NULL,
 status VARCHAR(24) NOT NULL, confirmation VARCHAR(24) NOT NULL,
 source VARCHAR(24) NOT NULL DEFAULT 'model', score DECIMAL(8,6) NULL,
 feedback_json JSON NULL, independent_eligible BOOLEAN NOT NULL DEFAULT FALSE,
 supersedes_assessment_id VARCHAR(64) NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 UNIQUE KEY uk_course_application_assessment_owner (assessment_id,attempt_id,owner_id),
 UNIQUE KEY uk_course_application_assessment_task (origin_task_id,owner_id),
 UNIQUE KEY uk_course_application_assessment_supersedes (supersedes_assessment_id),
 KEY idx_course_application_assessment_chain (attempt_id,owner_id,created_at),
 FOREIGN KEY (attempt_id,course_assessment_id,course_id,owner_id)
  REFERENCES learning_course_application_attempts(attempt_id,course_assessment_id,course_id,owner_id),
 FOREIGN KEY (origin_task_id,owner_id) REFERENCES quiz_tasks(task_id,user_id),
 FOREIGN KEY (supersedes_assessment_id,attempt_id,owner_id)
  REFERENCES learning_course_application_assessments(assessment_id,attempt_id,owner_id),
 CONSTRAINT ck_course_application_assessment_status CHECK (status IN ('graded','needs_review','failed','cancelled')),
 CONSTRAINT ck_course_application_assessment_confirmation CHECK (confirmation IN ('confirmed','provisional')),
 CONSTRAINT ck_course_application_assessment_source CHECK (source IN ('model','deterministic','human')),
 CONSTRAINT ck_course_application_assessment_score CHECK (score IS NULL OR (score>=0 AND score<=1)),
 CONSTRAINT ck_course_application_confirmation CHECK (confirmation<>'confirmed' OR status='graded')
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- @index learning_course_application_attempts fk_course_application_latest_assessment
ALTER TABLE learning_course_application_attempts ADD CONSTRAINT fk_course_application_latest_assessment
 FOREIGN KEY (latest_assessment_id,attempt_id,owner_id)
 REFERENCES learning_course_application_assessments(assessment_id,attempt_id,owner_id);
