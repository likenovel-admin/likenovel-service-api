ALTER TABLE tb_product
  ADD COLUMN blind_yn VARCHAR(1) NOT NULL DEFAULT 'N' COMMENT '관리자 블라인드 여부'
  AFTER open_yn;
