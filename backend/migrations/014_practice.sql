-- Published artifacts and question/rubric identities are immutable in services.
CREATE TABLE IF NOT EXISTS practice_sessions (
 practice_id VARCHAR(64) PRIMARY KEY,
 owner_id BIGINT UNSIGNED NOT NULL,
 space_id VARCHAR(64) NOT NULL,
 scope_revision INT NOT NULL,
 generation_task_id VARCHAR(64) COLLATE utf8mb4_unicode_ci NOT NULL,
 generation_request_json JSON NOT NULL,
 source_scope_json JSON NOT NULL,
 status VARCHAR(24) NOT NULL DEFAULT 'generating',
 revision INT NOT NULL DEFAULT 0,
 artifact_json JSON NULL,
 artifact_hash CHAR(64) NULL,
 completion_json JSON NULL,
 help_usage_json JSON NULL,
 error_code VARCHAR(64) NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 completed_at DATETIME(6) NULL,
 UNIQUE KEY uk_practice_owner (practice_id,owner_id),
 UNIQUE KEY uk_practice_generation (generation_task_id),
 KEY idx_practice_space (owner_id,space_id,created_at),
 FOREIGN KEY (owner_id) REFERENCES users(id),
 FOREIGN KEY (space_id,scope_revision,owner_id)
   REFERENCES learning_scope_revisions(space_id,revision,owner_id),
 FOREIGN KEY (generation_task_id,owner_id) REFERENCES quiz_tasks(task_id,user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS practice_questions (
 practice_id VARCHAR(64) NOT NULL,
 question_id VARCHAR(64) NOT NULL,
 owner_id BIGINT UNSIGNED NOT NULL,
 question_version CHAR(64) NOT NULL,
 rubric_version VARCHAR(64) NOT NULL,
 rubric_hash CHAR(64) NOT NULL,
 PRIMARY KEY (practice_id,question_id),
 UNIQUE KEY uk_practice_question_owner_version
   (practice_id,question_id,question_version,owner_id),
 FOREIGN KEY (practice_id,owner_id)
   REFERENCES practice_sessions(practice_id,owner_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- The sole answer payload remains in the shared learning_attempts record.
CREATE TABLE IF NOT EXISTS practice_submissions (
 attempt_id VARCHAR(64) PRIMARY KEY,
 owner_id BIGINT UNSIGNED NOT NULL,
 practice_id VARCHAR(64) NOT NULL,
 question_id VARCHAR(64) NOT NULL,
 question_version CHAR(64) NOT NULL,
 idempotency_key VARCHAR(128) NOT NULL,
 request_hash CHAR(64) NOT NULL,
 receipt_json JSON NOT NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 UNIQUE KEY uk_practice_question (practice_id,question_id),
 UNIQUE KEY uk_practice_answer_key (owner_id,idempotency_key),
 FOREIGN KEY (practice_id,owner_id)
   REFERENCES practice_sessions(practice_id,owner_id),
 FOREIGN KEY (practice_id,question_id,question_version,owner_id)
   REFERENCES practice_questions(practice_id,question_id,question_version,owner_id),
 FOREIGN KEY (attempt_id,owner_id) REFERENCES learning_attempts(attempt_id,owner_id),
 UNIQUE KEY uk_practice_submission_owner (attempt_id,owner_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS practice_grading_requests (
 grading_request_id VARCHAR(64) PRIMARY KEY,
 owner_id BIGINT UNSIGNED NOT NULL,
 attempt_id VARCHAR(64) NOT NULL,
 request_hash CHAR(64) NOT NULL,
 request_json JSON NOT NULL,
 active_task_id VARCHAR(64) COLLATE utf8mb4_unicode_ci NULL,
 status VARCHAR(24) NOT NULL DEFAULT 'pending',
 revision INT NOT NULL DEFAULT 0,
 latest_assessment_id VARCHAR(64) NULL,
 artifact_json JSON NULL,
 error_code VARCHAR(64) NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 UNIQUE KEY uk_practice_grade_attempt (attempt_id),
 FOREIGN KEY (attempt_id,owner_id) REFERENCES practice_submissions(attempt_id,owner_id),
 FOREIGN KEY (active_task_id,owner_id) REFERENCES quiz_tasks(task_id,user_id),
 FOREIGN KEY (latest_assessment_id,attempt_id,owner_id)
   REFERENCES assessment_records(assessment_id,attempt_id,owner_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
