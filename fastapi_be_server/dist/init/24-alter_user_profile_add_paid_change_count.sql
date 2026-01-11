-- tb_user_profile 테이블에 유료 닉네임 변경권 횟수 컬럼 추가
ALTER TABLE tb_user_profile
    ADD COLUMN paid_change_count INT DEFAULT 0 COMMENT '구매한 닉네임 변경권 횟수' AFTER nickname_change_count;
