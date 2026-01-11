USE likenovel;

ALTER TABLE tb_user_report
CHANGE COLUMN `episode_id` `episode_id` INT NULL COMMENT '회차 아이디',
CHANGE COLUMN `comment_id` `comment_id` INT NULL COMMENT '댓글 아이디';
