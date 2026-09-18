-- Rest-day preferences only (C02)
-- Learning days recompute from existing facts each read, nothing else persists.
CREATE TABLE IF NOT EXISTS learning_habit_rest_preferences (
 owner_id BIGINT UNSIGNED PRIMARY KEY,
 weekly_rest_days JSON NOT NULL,
 effective_from DATE NOT NULL,
 revision INT NOT NULL DEFAULT 1,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
 FOREIGN KEY (owner_id) REFERENCES users(id),
 CONSTRAINT ck_habit_rest_revision CHECK (revision>=1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
