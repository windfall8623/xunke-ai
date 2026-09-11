-- @index answer_records fk_history_answer_owner
ALTER TABLE answer_records ADD CONSTRAINT fk_history_answer_owner
 FOREIGN KEY (quiz_id,user_id) REFERENCES quiz_sessions(quiz_id,user_id);
-- @index reports fk_history_report_owner
ALTER TABLE reports ADD CONSTRAINT fk_history_report_owner
 FOREIGN KEY (quiz_id,user_id) REFERENCES quiz_sessions(quiz_id,user_id);
