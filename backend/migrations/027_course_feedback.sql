-- Course feedback issues, append-only corrections and authorized regrade chain (B03).
CREATE TABLE IF NOT EXISTS learning_course_feedback (
 feedback_id VARCHAR(64) PRIMARY KEY,
 course_id VARCHAR(64) NOT NULL,
 owner_id BIGINT UNSIGNED NOT NULL,
 issue_kind VARCHAR(24) NOT NULL,
 target_kind VARCHAR(24) NOT NULL,
 lesson_id VARCHAR(64) NULL,
 content_version INT NULL,
 block_index INT NULL,
 check_attempt_id VARCHAR(64) NULL,
 quiz_id VARCHAR(64) NULL,
 question_id VARCHAR(64) NULL,
 course_assessment_id VARCHAR(64) NULL,
 attempt_id VARCHAR(64) NULL,
 comment TEXT NOT NULL,
 allow_evaluation_use BOOLEAN NOT NULL DEFAULT FALSE,
 status VARCHAR(16) NOT NULL DEFAULT 'open',
 revision INT NOT NULL DEFAULT 1,
 tutor_turn_id VARCHAR(64) NULL,
 quiz_feedback_id VARCHAR(64) NULL,
 idempotency_key VARCHAR(128) NOT NULL,
 request_hash CHAR(64) NOT NULL,
 revoked_at DATETIME(6) NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
 UNIQUE KEY uk_course_feedback_owner (feedback_id,course_id,owner_id),
 UNIQUE KEY uk_course_feedback_idempotency (owner_id,idempotency_key),
 KEY idx_course_feedback_list (owner_id,course_id,created_at),
 KEY idx_course_feedback_target (owner_id,lesson_id,content_version),
 FOREIGN KEY (course_id,owner_id) REFERENCES learning_courses(course_id,owner_id),
 CONSTRAINT ck_course_feedback_issue CHECK (issue_kind IN ('confusion','content_error','grading_review')),
 CONSTRAINT ck_course_feedback_target CHECK (target_kind IN ('lesson','self_check','quiz','course_assessment')),
 CONSTRAINT ck_course_feedback_status CHECK (status IN ('open','resolved','rejected')),
 CONSTRAINT ck_course_feedback_revision CHECK (revision>=1),
 CONSTRAINT ck_course_feedback_block CHECK (block_index IS NULL OR block_index>=0),
 CONSTRAINT ck_course_feedback_version CHECK (content_version IS NULL OR content_version>=1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS learning_course_corrections (
 correction_id VARCHAR(64) PRIMARY KEY,
 feedback_id VARCHAR(64) NOT NULL,
 course_id VARCHAR(64) NOT NULL,
 owner_id BIGINT UNSIGNED NOT NULL,
 supersedes_correction_id VARCHAR(64) NULL,
 body TEXT NOT NULL,
 source_refs JSON NULL,
 provenance VARCHAR(24) NOT NULL,
 confirmation VARCHAR(16) NOT NULL,
 request_hash CHAR(64) NOT NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 UNIQUE KEY uk_course_correction_owner (correction_id,feedback_id,course_id,owner_id),
 KEY idx_course_correction_chain (feedback_id,owner_id,created_at),
 KEY idx_course_correction_idempotency (owner_id,request_hash),
 FOREIGN KEY (feedback_id,course_id,owner_id)
  REFERENCES learning_course_feedback(feedback_id,course_id,owner_id),
 CONSTRAINT ck_course_correction_provenance CHECK (provenance IN ('learner_note','model_proposal','human_reviewer')),
 CONSTRAINT ck_course_correction_confirmation CHECK (confirmation IN ('provisional','confirmed'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- @index learning_course_corrections fk_course_correction_supersedes
ALTER TABLE learning_course_corrections ADD CONSTRAINT fk_course_correction_supersedes
 FOREIGN KEY (supersedes_correction_id,feedback_id,course_id,owner_id)
 REFERENCES learning_course_corrections(correction_id,feedback_id,course_id,owner_id);
