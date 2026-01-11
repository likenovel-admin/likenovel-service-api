-- 29-migration_update_withdrawn_user_emails.sql
-- 탈퇴한 유저 이메일 형식 통일
--
-- 목적:
-- 1. use_yn = 'N'인 탈퇴 유저 중 이메일이 'outed;' 형식이 아닌 경우 형식 변경
-- 2. 형식: outed;{updated_date의 timestamp};{원래 이메일}
-- 3. tb_algorithm_recommend_user 레코드도 삭제 (이미 삭제되지 않은 경우)
--
-- 실행 일시: 2025-11-21
-- 작성자: Claude Code

-- 1. 탈퇴 유저의 이메일을 outed 형식으로 업데이트
UPDATE tb_user
SET email = CONCAT(
    'outed;',
    UNIX_TIMESTAMP(updated_date),
    ';',
    email
)
WHERE use_yn = 'N'
  AND email NOT LIKE 'outed;%'
  AND email IS NOT NULL
  AND email != '';

-- 2. 탈퇴 유저의 tb_algorithm_recommend_user 레코드 삭제 (아직 삭제되지 않은 경우)
DELETE FROM tb_algorithm_recommend_user
WHERE user_id IN (
    SELECT user_id
    FROM tb_user
    WHERE use_yn = 'N'
);

-- 마이그레이션 결과 확인 쿼리 (선택사항)
-- SELECT
--     COUNT(*) AS total_withdrawn_users,
--     SUM(CASE WHEN email LIKE 'outed;%' THEN 1 ELSE 0 END) AS correctly_formatted,
--     SUM(CASE WHEN email NOT LIKE 'outed;%' THEN 1 ELSE 0 END) AS incorrectly_formatted
-- FROM tb_user
-- WHERE use_yn = 'N';
