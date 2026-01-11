ALTER TABLE likenovel.tb_user_profile_apply
    DROP COLUMN attach_file_1st,
    DROP COLUMN attach_file_2nd;

ALTER TABLE likenovel.tb_user_profile_apply
    ADD COLUMN attach_file_id_1st INT COMMENT '첨부파일1 아이디',
    ADD COLUMN attach_file_id_2nd INT COMMENT '첨부파일2 아이디';
