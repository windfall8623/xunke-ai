-- Public idempotency receipts only. Answers and judgments stay in shared facts.
CREATE TABLE IF NOT EXISTS practice_review_receipts (
 owner_id BIGINT UNSIGNED NOT NULL,
 idempotency_key VARCHAR(128) NOT NULL,
 attempt_id VARCHAR(64) NOT NULL,
 assessment_id VARCHAR(64) NOT NULL,
 request_hash CHAR(64) NOT NULL,
 receipt_json JSON NOT NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 PRIMARY KEY (owner_id,idempotency_key),
 FOREIGN KEY (attempt_id,owner_id) REFERENCES practice_submissions(attempt_id,owner_id),
 FOREIGN KEY (assessment_id,attempt_id,owner_id)
   REFERENCES assessment_records(assessment_id,attempt_id,owner_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
