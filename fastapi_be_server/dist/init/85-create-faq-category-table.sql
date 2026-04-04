-- FAQ 카테고리 테이블 생성 + 초기 데이터
SET @tbl_exists = (SELECT COUNT(*) FROM information_schema.tables
    WHERE table_schema = DATABASE() AND table_name = 'tb_faq_category');

SET @sql = IF(@tbl_exists = 0,
    'CREATE TABLE tb_faq_category (
        code VARCHAR(20) NOT NULL PRIMARY KEY,
        name VARCHAR(50) NOT NULL,
        sort_order INT NOT NULL DEFAULT 0
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4',
    'SELECT 1');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- 초기 데이터 seed
INSERT IGNORE INTO tb_faq_category (code, name, sort_order) VALUES
    ('common',  '공통',              0),
    ('member',  '회원문의',          1),
    ('use',     '이용문의',          2),
    ('payment', '결제 및 환불',      3),
    ('site',    '사이트 이용 문의',  4),
    ('service', '서비스 이용 문의',  5);
