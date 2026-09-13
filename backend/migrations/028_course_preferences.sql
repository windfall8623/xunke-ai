-- Personal learning preferences and course review adjustments (B05).
CREATE TABLE IF NOT EXISTS learning_user_preferences (
 owner_id BIGINT UNSIGNED PRIMARY KEY,
 daily_minutes INT NOT NULL,
 daily_review_limit INT NOT NULL,
 difficulty VARCHAR(16) NOT NULL,
 timezone VARCHAR(64) NOT NULL,
 revision INT NOT NULL DEFAULT 1,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
 FOREIGN KEY (owner_id) REFERENCES users(id),
 CONSTRAINT ck_user_pref_minutes CHECK (daily_minutes BETWEEN 5 AND 120),
 CONSTRAINT ck_user_pref_review_limit CHECK (daily_review_limit BETWEEN 0 AND 3),
 CONSTRAINT ck_user_pref_difficulty CHECK (difficulty IN ('easy','medium','hard','mixed')),
 CONSTRAINT ck_user_pref_revision CHECK (revision>=1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- 原规则时间与用户覆盖时间分开保存；effective = COALESCE(override, rule)。
ALTER TABLE learning_course_reviews ADD COLUMN rule_due_at DATETIME(6) NULL;
ALTER TABLE learning_course_reviews ADD COLUMN override_due_at DATETIME(6) NULL;
ALTER TABLE learning_course_reviews ADD COLUMN paused BOOLEAN NOT NULL DEFAULT FALSE;
UPDATE learning_course_reviews SET rule_due_at=due_at WHERE rule_due_at IS NULL;

CREATE TABLE IF NOT EXISTS learning_course_review_adjustments (
 adjustment_id VARCHAR(64) PRIMARY KEY,
 review_id VARCHAR(64) NOT NULL,
 owner_id BIGINT UNSIGNED NOT NULL,
 action VARCHAR(16) NOT NULL,
 due_at DATETIME(6) NULL,
 expected_revision INT NOT NULL,
 idempotency_key VARCHAR(128) NOT NULL,
 request_hash CHAR(64) NOT NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 UNIQUE KEY uk_course_review_adjustment_owner (adjustment_id,owner_id),
 UNIQUE KEY uk_course_review_adjustment_key (owner_id,idempotency_key),
 KEY idx_course_review_adjustment_review (review_id,owner_id,created_at),
 FOREIGN KEY (review_id,owner_id) REFERENCES learning_course_reviews(review_id,owner_id),
 CONSTRAINT ck_course_review_adjustment_action CHECK (action IN ('pause','resume','reschedule')),
 CONSTRAINT ck_course_review_adjustment_revision CHECK (expected_revision>=1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
