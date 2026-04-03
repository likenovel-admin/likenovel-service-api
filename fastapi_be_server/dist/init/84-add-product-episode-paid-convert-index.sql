ALTER TABLE tb_product_episode
ADD INDEX idx_product_episode_paid_convert (product_id, use_yn, price_type, episode_no);
