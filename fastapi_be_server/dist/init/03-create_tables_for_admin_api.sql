USE likenovel;

-- 사이트 통계 집계용 로그 테이블
CREATE TABLE tb_site_statistics_log (
    `id` INT AUTO_INCREMENT PRIMARY KEY COMMENT '로그 고유 번호',
    `date` TIMESTAMP NOT NULL COMMENT '집계 일자',
    `type` VARCHAR(100) NOT NULL COMMENT '타입(visit, page_view, login, active)',
    `user_id` INT NOT NULL COMMENT '유저 아이디',
    `created_date` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    INDEX idx_date (`date`),
    INDEX idx_user_id (`user_id`),
    INDEX idx_type (`type`)
);

-- 사이트 통계 집계 테이블
CREATE TABLE tb_site_statistics (
    `id` INT AUTO_INCREMENT PRIMARY KEY COMMENT '통계 고유 번호',
    `date` TIMESTAMP NOT NULL COMMENT '집계 일자',
    `visitors` INT DEFAULT 0 COMMENT '방문자수',
    `page_view` INT DEFAULT 0 COMMENT '페이지뷰 수',
    `login_count` INT DEFAULT 0 COMMENT '로그인 수',
    `dau` INT DEFAULT 0 COMMENT 'DAU(일간 순수 유저 수)',
    `mau` INT DEFAULT 0 COMMENT 'MAU(월간 순수 유저 수)',
    `created_date` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    INDEX idx_date (`date`),
    UNIQUE KEY uk_date (`date`)
);

-- 결제 통계 집계용 로그 테이블
CREATE TABLE tb_payment_statistics_log (
    `id` INT AUTO_INCREMENT PRIMARY KEY COMMENT '로그 고유 번호',
    `date` TIMESTAMP NOT NULL COMMENT '집계 일자',
    `type` VARCHAR(100) NOT NULL COMMENT '타입(pay, use_coin, donation, ad)',
    `user_id` INT NOT NULL COMMENT '유저 아이디',
    `amount` INT DEFAULT 0 COMMENT '금액 또는 코인 수',
    `created_date` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    INDEX idx_date (`date`),
    INDEX idx_user_id (`user_id`),
    INDEX idx_type (`type`)
);

-- 결제 통계 집계 테이블
CREATE TABLE tb_payment_statistics (
    `id` INT AUTO_INCREMENT PRIMARY KEY COMMENT '통계 고유 번호',
    `date` DATE NOT NULL COMMENT '집계 일자',
    `pay_count` INT DEFAULT 0 COMMENT '결제 횟수',
    `pay_coin` INT DEFAULT 0 COMMENT '결제 코인 수',
    `pay_amount` INT DEFAULT 0 COMMENT '결제 금액',
    `use_coin_count` INT DEFAULT 0 COMMENT '코인 사용 횟수',
    `use_coin` INT DEFAULT 0 COMMENT '코인 사용량',
    `donation_count` INT DEFAULT 0 COMMENT '후원 횟수',
    `donation_coin` INT DEFAULT 0 COMMENT '후원 코인 수',
    `ad_revenue` INT DEFAULT 0 COMMENT '광고 수익',
    `created_date` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    UNIQUE KEY uk_date (`date`)
);

-- 회원별 결제 통계 집계 테이블
CREATE TABLE tb_payment_statistics_by_user (
    `id` INT AUTO_INCREMENT PRIMARY KEY COMMENT '통계 고유 번호',
    `date` DATE NOT NULL COMMENT '집계 일자',
    `user_id` INT NOT NULL COMMENT '유저 아이디',
    `pay_count` INT DEFAULT 0 COMMENT '결제 횟수',
    `pay_coin` INT DEFAULT 0 COMMENT '결제 코인 수',
    `pay_amount` INT DEFAULT 0 COMMENT '결제 금액',
    `use_coin_count` INT DEFAULT 0 COMMENT '코인 사용 횟수',
    `use_coin` INT DEFAULT 0 COMMENT '코인 사용량',
    `donation_count` INT DEFAULT 0 COMMENT '후원 횟수',
    `donation_coin` INT DEFAULT 0 COMMENT '후원 코인 수',
    `ad_revenue` INT DEFAULT 0 COMMENT '광고 수익',
    `created_date` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    UNIQUE KEY uk_date (`date`)
);

-- 뱃지
CREATE TABLE tb_badge (
    `id` INT AUTO_INCREMENT PRIMARY KEY COMMENT '뱃지 ID',
    `badge_name` VARCHAR(255) NULL COMMENT '뱃지명',
    `promotion_conditions` INT NOT NULL COMMENT '승급 조건',
    `created_id` INT NULL COMMENT 'row를 생성한 id',
    `created_date` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    `updated_id` INT NULL COMMENT 'row를 갱신한 id',
    `updated_date` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일'
);


-- 알고리즘 추천구좌 - 유저 테이블
CREATE TABLE tb_algorithm_recommend_user (
    `id` INT AUTO_INCREMENT PRIMARY KEY COMMENT 'PK',
    `user_id` INT NOT NULL COMMENT '사용자 id',
    `feature_basic` VARCHAR(1000) NOT NULL COMMENT 'feature_basic, 성별(male/female) + 연령(1(10대)|2(20대)|3(30대)|4(40대)|5(50대이상))',
    `feature_1` VARCHAR(1000) NOT NULL COMMENT 'feature_1',
    `feature_2` VARCHAR(1000) NOT NULL COMMENT 'feature_2',
    `feature_3` VARCHAR(1000) NOT NULL COMMENT 'feature_3',
    `feature_4` VARCHAR(1000) NOT NULL COMMENT 'feature_4',
    `feature_5` VARCHAR(1000) NOT NULL COMMENT 'feature_5',
    `feature_6` VARCHAR(1000) NOT NULL COMMENT 'feature_6',
    `feature_7` VARCHAR(1000) NOT NULL COMMENT 'feature_7',
    `feature_8` VARCHAR(1000) NOT NULL COMMENT 'feature_8',
    `feature_9` VARCHAR(1000) NOT NULL COMMENT 'feature_9',
    `feature_10` VARCHAR(1000) NOT NULL COMMENT 'feature_10',
    `created_id` INT NULL COMMENT 'row를 생성한 id',
    `created_date` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    `updated_id` INT NULL COMMENT 'row를 갱신한 id',
    `updated_date` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일'
);

-- 알고리즘 추천구좌 - 주제 설정 테이블
CREATE TABLE tb_algorithm_recommend_set_topic (
    `id` INT AUTO_INCREMENT PRIMARY KEY COMMENT 'PK',
    `feature` VARCHAR(1000) NOT NULL COMMENT 'feature',
    `target` VARCHAR(1000) NOT NULL COMMENT 'target, 성별(male/female) + 연령(1(10대)|2(20대)|3(30대)|4(40대)|5(50대이상))',
    `title` VARCHAR(1000) NOT NULL COMMENT '타이틀',
    `novel_list` VARCHAR(1000) NOT NULL COMMENT '작품 id - json 배열 형태',
    `created_id` INT NULL COMMENT 'row를 생성한 id',
    `created_date` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    `updated_id` INT NULL COMMENT 'row를 갱신한 id',
    `updated_date` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일'
);

-- 알고리즘 추천구좌 - 추천 섹션
CREATE TABLE tb_algorithm_recommend_section (
    `id` INT AUTO_INCREMENT PRIMARY KEY COMMENT 'PK',
    `position` VARCHAR(1000) NOT NULL COMMENT '위치',
    `feature` VARCHAR(1000) NOT NULL COMMENT 'feature, default_1~4|feature_basic|feature_1~10',
    `created_id` INT NULL COMMENT 'row를 생성한 id',
    `created_date` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    `updated_id` INT NULL COMMENT 'row를 갱신한 id',
    `updated_date` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일'
);

-- 알고리즘 추천구좌 - 추천1 내용비슷, 추천2 장르비슷, 추천3 장바구니
CREATE TABLE tb_algorithm_recommend_similar (
    `id` INT AUTO_INCREMENT PRIMARY KEY COMMENT 'PK',
    `type` VARCHAR(1000) NOT NULL COMMENT '내용비슷(content) | 장르비슷(genre) | 장바구니(cart)',
    `product_id` INT NULL COMMENT '작품 id',
    `similar_subject_ids` VARCHAR(1000) NOT NULL COMMENT 'similar_subject_ids - json 배열 형태',
    `created_id` INT NULL COMMENT 'row를 생성한 id',
    `created_date` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    `updated_id` INT NULL COMMENT 'row를 갱신한 id',
    `updated_date` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일'
);

-- 직접 추천구좌
CREATE TABLE tb_direct_recommend (
    `id` INT AUTO_INCREMENT PRIMARY KEY COMMENT '추천구좌 ID',
    `name` VARCHAR(1000) NOT NULL COMMENT '추천구좌명',
    `order` INT NOT NULL COMMENT '노출 순서',
    `product_ids` VARCHAR(1000) NOT NULL COMMENT '노출 작품 - json 배열 형태',
    `exposure_start_date` TIMESTAMP NOT NULL COMMENT '노출 기간 시작일',
    `exposure_end_date` TIMESTAMP NOT NULL COMMENT '노출 기간 종료일',
    `exposure_start_time_weekday` VARCHAR(1000) NOT NULL COMMENT '노출 시간 주중 시작 시간',
    `exposure_end_time_weekday` VARCHAR(1000) NOT NULL COMMENT '노출 시간 주중 종료 시간',
    `exposure_start_time_weekend` VARCHAR(1000) NOT NULL COMMENT '노출 시간 주말 시작 시간',
    `exposure_end_time_weekend` VARCHAR(1000) NOT NULL COMMENT '노출 시간 주말 종료 시간',
    `created_id` INT NULL COMMENT 'row를 생성한 id',
    `created_date` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일시',
    `updated_id` INT NULL COMMENT 'row를 갱신한 id',
    `updated_date` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일시'
);

-- 직접 프로모션
CREATE TABLE tb_direct_promotion (
    `id` INT AUTO_INCREMENT PRIMARY KEY COMMENT '기본키',
    `product_id` INT NOT NULL COMMENT '작품 id',
    `start_date` TIMESTAMP NOT NULL COMMENT '시작일',
    `type` VARCHAR(1000) NOT NULL COMMENT '프로모션 종류, 첫방문자 무료 (free-for-first) | 선작 독자 (reader-of-prev)',
    `status` VARCHAR(1000) NOT NULL COMMENT '상태, 진행중 (ing) | 중지 (stop)',
    `num_of_ticket_per_person` INT NOT NULL COMMENT '명당 증정 대여권 수',
    `created_id` INT NULL COMMENT 'row를 생성한 id',
    `created_date` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일시',
    `updated_id` INT NULL COMMENT 'row를 갱신한 id',
    `updated_date` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일시'
);

-- 신청 프로모션
CREATE TABLE tb_applied_promotion (
    `id` INT AUTO_INCREMENT PRIMARY KEY COMMENT '신청 프로모션 ID',
    `product_id` INT NOT NULL COMMENT '작품 id',
    `type` VARCHAR(1000) NOT NULL COMMENT '프로모션 종류, 기다리면 무료 (waiting-for-free) | 6-9 패스 (6-9-path)',
    `status` VARCHAR(1000) NOT NULL COMMENT '상태, 진행중 (ing) | 신청 (apply) | 철회 (cancel) | 종료 (end) | 반려 (deny)',
    `start_date` TIMESTAMP NOT NULL COMMENT '시작일',
    `end_date` TIMESTAMP NULL COMMENT '종료일',
    `num_of_ticket_per_person` INT NOT NULL COMMENT '명당 증정 대여권 수',
    `created_id` INT NULL COMMENT 'row를 생성한 id',
    `created_date` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일시',
    `updated_id` INT NULL COMMENT 'row를 갱신한 id',
    `updated_date` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일시'
);

-- 메시지 내역
CREATE TABLE tb_messages_between_users (
    `id` INT AUTO_INCREMENT PRIMARY KEY COMMENT '메시지 ID',
    `key` VARCHAR(255) NOT NULL COMMENT '대화방 key',
    `sender` INT NOT NULL COMMENT '발신인 profile_id',
    `receiver` INT NOT NULL COMMENT '수신인 profile_id',
    `content` TEXT NOT NULL COMMENT '내용',
    `created_id` INT NULL COMMENT 'row를 생성한 id',
    `created_date` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일시',
    `updated_id` INT NULL COMMENT 'row를 갱신한 id',
    `updated_date` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일시',
    INDEX idx_key (`key`),
    INDEX idx_sender (`sender`),
    INDEX idx_receiver (`receiver`),
    INDEX idx_created_date (`created_date`)
);

-- 푸시 메시지 템플릿
CREATE TABLE tb_push_message_templates (
    `id` INT AUTO_INCREMENT PRIMARY KEY COMMENT '고유 번호',
    `use_yn` VARCHAR(1) NOT NULL DEFAULT 'Y' COMMENT '사용 여부',
    `name` VARCHAR(1000) NOT NULL COMMENT '템플릿명',
    `condition` VARCHAR(1000) NOT NULL COMMENT '발송 조건',
    `landing_page` VARCHAR(1000) NOT NULL COMMENT '랜딩 페이지',
    `image_id` INT NULL COMMENT '이미지 파일',
    `contents` VARCHAR(1000) NULL COMMENT '본문',
    `created_id` INT NULL COMMENT 'row를 생성한 id',
    `created_date` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일시',
    `updated_id` INT NULL COMMENT 'row를 갱신한 id',
    `updated_date` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일시'
);

-- 이벤트
CREATE TABLE tb_event_v2 (
    `id` INT AUTO_INCREMENT PRIMARY KEY COMMENT '고유 번호',
    `title` VARCHAR(1000) NOT NULL COMMENT '이벤트명',
    `start_date` TIMESTAMP NOT NULL COMMENT '이벤트 기간 (시작일)',
    `end_date` TIMESTAMP NOT NULL COMMENT '이벤트 기간 (종료일)',
    `type` VARCHAR(1000) NOT NULL COMMENT '이벤트 종류,  3화 감상 (view-3-times) | 댓글 등록 (add-comment) | 작품 등록 (add-product) | 그 외 (etc)',
    `target_product_ids` VARCHAR(1000) NULL COMMENT '이벤트 작품 등록, 3화 감상, 댓글 등록인 경우의 대상 작품들의 id - json 배열 형태',
    `reward_type` VARCHAR(10) NULL COMMENT '이벤트 보상 (type이 etc인 경우 null) - 보상 종류, 이벤트 대여권 (ticket) | 캐시 (cash)',
    `reward_amount` INT NULL COMMENT '이벤트 보상 (type이 etc인 경우 null) - 증정 갯수',
    `reward_max_people` INT NULL COMMENT '이벤트 보상 (type이 etc인 경우 null) - 최대 인원',
    `show_yn_thumbnail_img` VARCHAR(1) NOT NULL DEFAULT 'Y' COMMENT '노출 여부 - 썸네일 이미지',
    `show_yn_detail_img` VARCHAR(1) NOT NULL DEFAULT 'Y' COMMENT '노출 여부 - 상세 이미지',
    `show_yn_product` VARCHAR(1) NOT NULL DEFAULT 'Y' COMMENT '노출 여부 - 작품 구좌',
    `show_yn_information` VARCHAR(1) NOT NULL DEFAULT 'Y' COMMENT '노출 여부 - 안내 문구',
    `thumbnail_image_id` INT NOT NULL COMMENT '썸네일 이미지 파일',
    `detail_image_id` INT NOT NULL COMMENT '상세 이미지 파일',
    `account_name` VARCHAR(1000) NOT NULL COMMENT '구좌명',
    `product_ids` VARCHAR(1000) NOT NULL COMMENT '노출 구좌에 노출될 잘품들의 id - json 배열 형태',
    `information` VARCHAR(1000) NOT NULL COMMENT '안내 문구',
    `created_id` INT NULL COMMENT 'row를 생성한 id',
    `created_date` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일시',
    `updated_id` INT NULL COMMENT 'row를 갱신한 id',
    `updated_date` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일시'
);

-- 이벤트 보상 수령인
CREATE TABLE tb_event_v2_reward_recipient (
    `id` INT AUTO_INCREMENT PRIMARY KEY COMMENT '고유 번호',
    `event_id` INT NOT NULL COMMENT '이벤트 id',
    `user_id` INT NOT NULL COMMENT '수령인 id',
    `created_id` INT NULL COMMENT 'row를 생성한 id',
    `created_date` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    `updated_id` INT NULL COMMENT 'row를 갱신한 id',
    `updated_date` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일'
);
