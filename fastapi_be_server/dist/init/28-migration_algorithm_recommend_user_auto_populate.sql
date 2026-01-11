-- 28-migration_algorithm_recommend_user_auto_populate.sql
-- 알고리즘 추천구좌 관리 - 기존 가입 유저 자동 채우기
--
-- 목적:
-- 1. tb_user에는 존재하지만 tb_algorithm_recommend_user에 없는 모든 유저 레코드를 자동 생성
-- 2. user_id, email(조인), role_type(조인), gender, age는 tb_user에서 자동으로 가져옴
-- 3. feature_basic과 feature_1~10은 CSV 업로드 전까지 빈 문자열('')로 설정
--
-- 실행 일시: 2025-11-21
-- 작성자: Claude Code

-- 기존 유저 중 tb_algorithm_recommend_user에 없는 유저들을 자동으로 추가
INSERT INTO tb_algorithm_recommend_user (
    user_id,
    feature_basic,
    feature_1,
    feature_2,
    feature_3,
    feature_4,
    feature_5,
    feature_6,
    feature_7,
    feature_8,
    feature_9,
    feature_10,
    created_id,
    created_date,
    updated_id,
    updated_date
)
SELECT
    u.user_id,
    '' AS feature_basic,  -- CSV 업로드 전까지 빈 문자열
    '' AS feature_1,
    '' AS feature_2,
    '' AS feature_3,
    '' AS feature_4,
    '' AS feature_5,
    '' AS feature_6,
    '' AS feature_7,
    '' AS feature_8,
    '' AS feature_9,
    '' AS feature_10,
    0 AS created_id,      -- DB_DML_DEFAULT_ID
    NOW() AS created_date,
    0 AS updated_id,      -- DB_DML_DEFAULT_ID
    NOW() AS updated_date
FROM tb_user u
LEFT JOIN tb_algorithm_recommend_user aru ON u.user_id = aru.user_id
WHERE aru.user_id IS NULL  -- tb_algorithm_recommend_user에 없는 유저만
;

-- 마이그레이션 결과 확인 쿼리 (선택사항)
-- SELECT
--     COUNT(*) AS total_users,
--     SUM(CASE WHEN aru.user_id IS NOT NULL THEN 1 ELSE 0 END) AS users_in_algorithm_table,
--     SUM(CASE WHEN aru.user_id IS NULL THEN 1 ELSE 0 END) AS users_not_in_algorithm_table
-- FROM tb_user u
-- LEFT JOIN tb_algorithm_recommend_user aru ON u.user_id = aru.user_id;
