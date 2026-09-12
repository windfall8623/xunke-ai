CREATE TABLE IF NOT EXISTS learning_course_check_attempts (
 attempt_id VARCHAR(64) PRIMARY KEY,
 course_id VARCHAR(64) NOT NULL, lesson_id VARCHAR(64) NOT NULL,
 owner_id BIGINT UNSIGNED NOT NULL, content_version INT NOT NULL,
 check_ref VARCHAR(128) NOT NULL, answer_json JSON NULL,
 idempotency_key VARCHAR(128) NOT NULL, request_hash CHAR(64) NOT NULL,
 revoked_at DATETIME(6) NULL,
 saved_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 UNIQUE KEY uk_course_check_idempotency (owner_id,idempotency_key),
 UNIQUE KEY uk_course_check_lesson_version (attempt_id,lesson_id,course_id,owner_id,content_version),
 KEY idx_course_check_history (owner_id,lesson_id,content_version,saved_at),
 FOREIGN KEY (course_id,owner_id) REFERENCES learning_courses(course_id,owner_id),
 FOREIGN KEY (lesson_id,course_id,owner_id) REFERENCES learning_course_lessons(lesson_id,course_id,owner_id),
 CONSTRAINT ck_course_check_version CHECK (content_version >= 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- @index learning_course_tutor_turns fk_course_tutor_check_attempt
ALTER TABLE learning_course_tutor_turns ADD CONSTRAINT fk_course_tutor_check_attempt
 FOREIGN KEY (check_attempt_id,lesson_id,course_id,owner_id,content_version)
 REFERENCES learning_course_check_attempts(attempt_id,lesson_id,course_id,owner_id,content_version);
