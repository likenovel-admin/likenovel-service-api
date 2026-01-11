
-- 배치 작업내역
create table `tb_cms_batch_job_process` (
  `id` int not null auto_increment,
  `job_file_id` varchar(50) not null comment '배치 파일명',
  `job_group_id` int not null default '0' comment '작업 그룹',
  `job_order` int not null default '0' comment '그룹 내 작업 순서',
  `completed_yn` varchar(1) not null default 'N' comment '작업 완료 여부',
  `job_list` varchar(200) not null comment '배치 목록',
  `created_id` int DEFAULT NULL COMMENT 'row를 생성한 id',
  `created_date` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_id` int DEFAULT NULL COMMENT 'row를 갱신한 id',
  `updated_date` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  primary key (`id`),
  key `job_file_id` (`job_file_id`)
) ENGINE=InnoDB AUTO_INCREMENT=0 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;


drop table tb_batch_daily_sales_summary;
drop table tb_batch_daily_refund_summary;
drop table tb_batch_daily_product_count_summary;
drop table tb_batch_daily_product_episode_count_summary;
drop table tb_batch_daily_product_info_summary;
drop table tb_batch_daily_product_episode_info_summary;
drop table tb_ptn_product_episode_sales;
drop table tb_ptn_ticket_usage;
drop table tb_ptn_sponsorship_recodes;
drop table tb_ptn_income_recodes;
drop table tb_ptn_product_statistics;
drop table tb_ptn_product_episode_statistics;
drop table tb_ptn_product_discovery_statistics;
drop table tb_ptn_product_sales_temp_summary;
drop table tb_ptn_income_settlement_temp_summary;
drop table tb_cms_product_evaluation;
drop table tb_ptn_product_sales;
drop table tb_cms_product_settlement;
drop table tb_ptn_product_settlement;
drop table tb_ptn_product_contract_offer_deduction;
drop table tb_ptn_income_settlement;


-- 일별 집계(매출)
create table `tb_batch_daily_sales_summary` (
  `id` int not null auto_increment,
  `item_type` varchar(20) not null comment '소장, 대여, 후원',
  `item_name` varchar(200) not null comment '상품명',
  `item_price` int not null default '0' comment '단가',
  `quantity` int not null default '0' comment '수량',
  `device_type` varchar(20) not null comment '웹, 스토어',
  `user_id` int NOT NULL COMMENT '유저 id',
  `order_date` timestamp NOT NULL COMMENT '주문일자',
  `product_id` int NOT NULL COMMENT '작품 id',
  `episode_id` int NOT NULL COMMENT '회차 id',
  `pay_type` varchar(20) not null comment '캐시, 닉네임변경권',
  `created_id` int DEFAULT NULL COMMENT 'row를 생성한 id',
  `created_date` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_id` int DEFAULT NULL COMMENT 'row를 갱신한 id',
  `updated_date` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  primary key (`id`),
  key `user_id` (`user_id`),
  key `product_id` (`product_id`),
  key `episode_id` (`episode_id`)
) ENGINE=InnoDB AUTO_INCREMENT=0 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;

-- 일별 집계(환불)
create table `tb_batch_daily_refund_summary` (
  `id` int not null auto_increment,
  `item_type` varchar(20) not null comment '소장, 대여, 후원',
  `item_name` varchar(200) not null comment '상품명',
  `refund_type` varchar(20) not null comment '환불 타입',
  `refund_price` int not null default '0' comment '환불액',
  `device_type` varchar(20) not null comment '웹, 스토어',
  `user_id` int NOT NULL COMMENT '유저 id',
  `order_date` timestamp NOT NULL COMMENT '주문일자',
  `product_id` int NOT NULL COMMENT '작품 id',
  `episode_id` int NOT NULL COMMENT '회차 id',
  `pay_type` varchar(20) not null comment '캐시, 닉네임변경권',
  `created_id` int DEFAULT NULL COMMENT 'row를 생성한 id',
  `created_date` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_id` int DEFAULT NULL COMMENT 'row를 갱신한 id',
  `updated_date` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  primary key (`id`),
  key `user_id` (`user_id`),
  key `product_id` (`product_id`),
  key `episode_id` (`episode_id`)
) ENGINE=InnoDB AUTO_INCREMENT=0 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;

-- 작품 일별 집계(조회수)
create table `tb_batch_daily_product_count_summary` (
  `id` int not null auto_increment,
  `product_id` int NOT NULL COMMENT '작품 id',
  `current_count_hit` int NOT NULL default '0' COMMENT '현재 조회수',
  `privious_count_hit` int NOT NULL default '0' COMMENT '전날 조회수',
  `current_count_recommend` int NOT NULL default '0' COMMENT '현재 추천수',
  `privious_count_recommend` int NOT NULL default '0' COMMENT '전날 추천수',
  `current_count_bookmark` int NOT NULL default '0' COMMENT '현재 선작수',
  `privious_count_bookmark` int NOT NULL default '0' COMMENT '전날 선작수',
  `current_count_unbookmark` int NOT NULL default '0' COMMENT '현재 선작해제수',
  `privious_count_unbookmark` int NOT NULL default '0' COMMENT '전날 선작해제수',
  `current_count_cp_hit` int NOT NULL default '0' COMMENT '현재 cp 조회수',
  `privious_count_cp_hit` int NOT NULL default '0' COMMENT '전날 cp 조회수',
  `current_reading_rate` double NOT NULL default '0' COMMENT '현재 연독률',
  `privious_reading_rate` double NOT NULL default '0' COMMENT '전날 연독률',
  `current_count_interest` int NOT NULL default '0' COMMENT '현재 누적관심수',
  `privious_count_interest` int NOT NULL default '0' COMMENT '전날 누적관심수',
  `current_count_interest_sustain` int NOT NULL default '0' COMMENT '현재 관심유지수',
  `privious_count_interest_sustain` int NOT NULL default '0' COMMENT '전날 관심유지수',
  `current_count_interest_loss` int NOT NULL default '0' COMMENT '현재 관심이탈수',
  `privious_count_interest_loss` int NOT NULL default '0' COMMENT '전날 관심이탈수',
  `created_id` int DEFAULT NULL COMMENT 'row를 생성한 id',
  `created_date` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_id` int DEFAULT NULL COMMENT 'row를 갱신한 id',
  `updated_date` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  primary key (`id`),
  key `product_id` (`product_id`)
) ENGINE=InnoDB AUTO_INCREMENT=0 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;

-- 회차 일별 집계(조회수)
create table `tb_batch_daily_product_episode_count_summary` (
  `id` int not null auto_increment,
  `product_id` int NOT NULL COMMENT '작품 id',
  `episode_id` int NOT NULL COMMENT '회차 id',
  `episode_no` int NOT NULL default '0' COMMENT '회차수',
  `current_count_hit` int NOT NULL default '0' COMMENT '현재 조회수',
  `privious_count_hit` int NOT NULL default '0' COMMENT '전날 조회수',
  `current_count_recommend` int NOT NULL default '0' COMMENT '현재 추천수',
  `privious_count_recommend` int NOT NULL default '0' COMMENT '전날 추천수',
  `current_count_comment` int NOT NULL default '0' COMMENT '현재 댓글수',
  `privious_count_comment` int NOT NULL default '0' COMMENT '전날 댓글수',
  `current_count_evaluation` int NOT NULL default '0' COMMENT '현재 평가수',
  `privious_count_evaluation` int NOT NULL default '0' COMMENT '전날 평가수',
  `current_count_hit_in_24h` int NOT NULL default '0' COMMENT '현재 24시간 내 조회수',
  `privious_count_hit_in_24h` int NOT NULL default '0' COMMENT '전날 24시간 내 조회수',
  `created_id` int DEFAULT NULL COMMENT 'row를 생성한 id',
  `created_date` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_id` int DEFAULT NULL COMMENT 'row를 갱신한 id',
  `updated_date` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  primary key (`id`),
  key `product_id` (`product_id`),
  key `episode_id` (`episode_id`)
) ENGINE=InnoDB AUTO_INCREMENT=0 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;

-- 작품 일별 집계(정보)
create table `tb_batch_daily_product_info_summary` (
  `id` int not null auto_increment,
  `product_id` int NOT NULL COMMENT '작품 id',
  `title` varchar(100) NOT NULL COMMENT '작품명',
  `author_nickname` varchar(200) NOT NULL COMMENT '작가 닉네임',
  `count_episode` int NOT NULL default '0' COMMENT '회차수',
  `count_evaluation` int NOT NULL default '0' COMMENT '평가수',
  `count_read_user` int NOT NULL default '0' COMMENT '독자수',
  `contract_type` varchar(20) NULL COMMENT 'cp, 일반, 기타(null)',
  `cp_company_name` varchar(200) NULL COMMENT '담당cp 회사명',
  `publish_date` timestamp NOT NULL COMMENT '작품등록일',
  `paid_open_date` timestamp NULL COMMENT '판매시작일',
  `isbn` varchar(20) NULL COMMENT 'ISBN 코드',
  `uci` varchar(20) NULL COMMENT 'UCI 코드',
  `status_code` varchar(20) NOT NULL COMMENT '연재상태',
  `ratings_code` varchar(20) NOT NULL COMMENT '연령등급',
  `paid_yn` varchar(1) NOT NULL default 'N' COMMENT '유료여부',
  `primary_genre` varchar(200) NULL COMMENT '1차 장르',
  `sub_genre` varchar(200) NULL COMMENT '2차 장르',
  `single_regular_price` int NOT NULL default '0' COMMENT '단행본 가격',
  `series_regular_price` int NOT NULL default '0' COMMENT '연재 가격',
  `sale_price` int NOT NULL default '0' COMMENT '판매가',
  `primary_reader_group1` varchar(200) NULL COMMENT '주요 독자층1',
  `primary_reader_group2` varchar(200) NULL COMMENT '주요 독자층2',
  `created_id` int DEFAULT NULL COMMENT 'row를 생성한 id',
  `created_date` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_id` int DEFAULT NULL COMMENT 'row를 갱신한 id',
  `updated_date` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  primary key (`id`),
  key `product_id` (`product_id`)
) ENGINE=InnoDB AUTO_INCREMENT=0 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;

-- 회차 일별 집계(정보)
create table `tb_batch_daily_product_episode_info_summary` (
  `id` int not null auto_increment,
  `product_id` int NOT NULL COMMENT '작품 id',
  `episode_id` int NOT NULL COMMENT '회차 id',
  `episode_no` int NOT NULL default '0' COMMENT '회차수',
  `paid_yn` varchar(1) NOT NULL default 'N' COMMENT '유료여부',
  `current_count_hit_in_24h` int NOT NULL default '0' COMMENT '현재 24시간 내 조회수',
  `created_id` int DEFAULT NULL COMMENT 'row를 생성한 id',
  `created_date` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_id` int DEFAULT NULL COMMENT 'row를 갱신한 id',
  `updated_date` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  primary key (`id`),
  key `product_id` (`product_id`),
  key `episode_id` (`episode_id`)
) ENGINE=InnoDB AUTO_INCREMENT=0 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;

-- 회차별 매출
create table `tb_ptn_product_episode_sales` (
  `id` int not null auto_increment,
  `product_id` int NOT NULL COMMENT '작품 id',
  `episode_id` int NOT NULL COMMENT '회차 id',
  `title` varchar(100) NOT NULL COMMENT '작품명',
  `author_nickname` varchar(200) NOT NULL COMMENT '작가 닉네임',
  `episode_no` int NOT NULL default '0' COMMENT '회차수',
  `contract_type` varchar(20) NULL COMMENT 'cp, 일반, 기타(null)',
  `cp_company_name` varchar(200) NULL COMMENT '담당cp 회사명',
  `paid_open_date` timestamp NULL COMMENT '판매시작일',
  `count_total_sales` int NOT NULL default '0' COMMENT '총 판매 건수',
  `sum_total_sales_price` int NOT NULL default '0' COMMENT '총 판매 총액',
  `count_normal_sales` int NOT NULL default '0' COMMENT '일반판매 건수',
  `sum_normal_price` int NOT NULL default '0' COMMENT '일반판매 총액',
  `count_discount_sales` int NOT NULL default '0' COMMENT '할인판매 건수',
  `sum_discount_price` int NOT NULL default '0' COMMENT '할인판매 총액',
  `count_paid_ticket_sales` int NOT NULL default '0' COMMENT '구입 대여권 건수',
  `sum_paid_ticket_price` int NOT NULL default '0' COMMENT '구입 대여권 총액',
  `count_comped_ticket_sales` int NOT NULL default '0' COMMENT '무상 대여권 건수',
  `sum_comped_ticket_price` int NOT NULL default '0' COMMENT '무상 대여권 총액',
  `count_free_ticket_sales` int NOT NULL default '0' COMMENT '무료 대여권 건수',
  `sum_free_ticket_price` int NOT NULL default '0' COMMENT '무료 대여권 총액',
  `count_total_refund` int NOT NULL default '0' COMMENT '구매취소 건수',
  `sum_total_refund_price` int NOT NULL default '0' COMMENT '구매취소 총액',
  `created_id` int DEFAULT NULL COMMENT 'row를 생성한 id',
  `created_date` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_id` int DEFAULT NULL COMMENT 'row를 갱신한 id',
  `updated_date` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  primary key (`id`),
  key `product_id` (`product_id`),
  key `episode_id` (`episode_id`),
  key `episode_no` (`episode_no`)
) ENGINE=InnoDB AUTO_INCREMENT=0 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;

-- 일별 이용권 상세
create table `tb_ptn_ticket_usage` (
  `id` int not null auto_increment,
  `product_id` int NOT NULL COMMENT '작품 id',
  `title` varchar(100) NOT NULL COMMENT '작품명',
  `author_nickname` varchar(200) NOT NULL COMMENT '작가 닉네임',
  `contract_type` varchar(20) NULL COMMENT 'cp, 일반, 기타(null)',
  `cp_company_name` varchar(200) NULL COMMENT '담당cp 회사명',
  `paid_open_date` timestamp NULL COMMENT '판매시작일',
  `isbn` varchar(20) NULL COMMENT 'ISBN 코드',
  `uci` varchar(20) NULL COMMENT 'UCI 코드',
  `episode_no` int NOT NULL default '0' COMMENT '회차수',
  `item_name` varchar(200) NOT NULL COMMENT '상품명',
  `count_ticket_usage` int NOT NULL default '0' COMMENT '대여권 건수',
  `created_id` int DEFAULT NULL COMMENT 'row를 생성한 id',
  `created_date` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_id` int DEFAULT NULL COMMENT 'row를 갱신한 id',
  `updated_date` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  primary key (`id`),
  key `product_id` (`product_id`)
) ENGINE=InnoDB AUTO_INCREMENT=0 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;

-- 후원 내역
create table `tb_ptn_sponsorship_recodes` (
  `id` int not null auto_increment,
  `product_id` int NOT NULL COMMENT '작품 id',
  `title` varchar(100) NOT NULL COMMENT '작품명',
  `author_nickname` varchar(200) NOT NULL COMMENT '작가 닉네임',
  `user_name` varchar(200) NOT NULL COMMENT '후원자',
  `donation_price` int NOT NULL default '0' COMMENT '후원금액',
  `created_id` int DEFAULT NULL COMMENT 'row를 생성한 id',
  `created_date` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_id` int DEFAULT NULL COMMENT 'row를 갱신한 id',
  `updated_date` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  primary key (`id`),
  key `product_id` (`product_id`)
) ENGINE=InnoDB AUTO_INCREMENT=0 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;

-- 기타 수익 내역
create table `tb_ptn_income_recodes` (
  `id` int not null auto_increment,
  `product_id` int NOT NULL COMMENT '작품 id',
  `title` varchar(100) NOT NULL COMMENT '작품명',
  `author_nickname` varchar(200) NOT NULL COMMENT '작가 닉네임',
  `item_type` varchar(20) NOT NULL COMMENT '수익내역',
  `sum_income_price` int NOT NULL default '0' COMMENT '금액',
  `created_id` int DEFAULT NULL COMMENT 'row를 생성한 id',
  `created_date` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_id` int DEFAULT NULL COMMENT 'row를 갱신한 id',
  `updated_date` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  primary key (`id`),
  key `product_id` (`product_id`)
) ENGINE=InnoDB AUTO_INCREMENT=0 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;

-- 작품별 통계
create table `tb_ptn_product_statistics` (
  `id` int not null auto_increment,
  `product_id` int NOT NULL COMMENT '작품 id',
  `title` varchar(100) NOT NULL COMMENT '작품명',
  `author_nickname` varchar(200) NOT NULL COMMENT '작가 닉네임',
  `count_episode` int NOT NULL default '0' COMMENT '회차수',
  `paid_yn` varchar(1) NOT NULL default 'N' COMMENT '유료여부',
  `count_hit` int NOT NULL default '0' COMMENT '조회수',
  `count_bookmark` int NOT NULL default '0' COMMENT '선호작 수',
  `count_unbookmark` int NOT NULL default '0' COMMENT '선호 해제 수',
  `count_recommend` int NOT NULL default '0' COMMENT '추천수',
  `count_evaluation` int NOT NULL default '0' COMMENT '평가자 수',
  `count_total_sales` int NOT NULL default '0' COMMENT '총 결제건수',
  `sum_total_sales_price` int NOT NULL default '0' COMMENT '총 수익',
  `sales_price_per_count_hit` double NOT NULL default '0' COMMENT '조회수당 수익',
  `count_cp_hit` int NOT NULL default '0' COMMENT 'cp조회수',
  `reading_rate` double NOT NULL default '0' COMMENT '연독률',
  `created_id` int DEFAULT NULL COMMENT 'row를 생성한 id',
  `created_date` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_id` int DEFAULT NULL COMMENT 'row를 갱신한 id',
  `updated_date` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  primary key (`id`),
  key `product_id` (`product_id`)
) ENGINE=InnoDB AUTO_INCREMENT=0 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;

-- 회차별 통계
create table `tb_ptn_product_episode_statistics` (
  `id` int not null auto_increment,
  `product_id` int NOT NULL COMMENT '작품 id',
  `title` varchar(100) NOT NULL COMMENT '작품명',
  `author_nickname` varchar(200) NOT NULL COMMENT '작가 닉네임',
  `episode_no` int NOT NULL default '0' COMMENT '회차수',
  `paid_yn` varchar(1) NOT NULL default 'N' COMMENT '유료여부',
  `count_hit` int NOT NULL default '0' COMMENT '조회수',
  `count_recommend` int NOT NULL default '0' COMMENT '추천수',
  `count_evaluation` int NOT NULL default '0' COMMENT '평가자 수',
  `count_total_sales` int NOT NULL default '0' COMMENT '총 결제건수',
  `sum_total_sales_price` int NOT NULL default '0' COMMENT '총 수익',
  `sales_price_per_count_hit` double NOT NULL default '0' COMMENT '조회수당 수익',
  `count_hit_in_24h` int NOT NULL default '0' COMMENT '24시간 이내 조회수',
  `created_id` int DEFAULT NULL COMMENT 'row를 생성한 id',
  `created_date` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_id` int DEFAULT NULL COMMENT 'row를 갱신한 id',
  `updated_date` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  primary key (`id`),
  key `product_id` (`product_id`),
  key `episode_no` (`episode_no`)
) ENGINE=InnoDB AUTO_INCREMENT=0 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;

-- 발굴통계
create table `tb_ptn_product_discovery_statistics` (
  `id` int not null auto_increment,
  `product_id` int NOT NULL COMMENT '작품 id',
  `title` varchar(100) NOT NULL COMMENT '작품명',
  `author_nickname` varchar(200) NOT NULL COMMENT '작가 닉네임',
  `count_episode` int NOT NULL default '0' COMMENT '회차수',
  `count_hit` int NOT NULL default '0' COMMENT '조회수',
  `count_hit_per_episode` double NOT NULL default '0' COMMENT '회차당 조회수',
  `count_read_user` int NOT NULL default '0' COMMENT '독자수',
  `count_bookmark` int NOT NULL default '0' COMMENT '선호작 수',
  `count_unbookmark` int NOT NULL default '0' COMMENT '선호 해제 수',
  `count_recommend` int NOT NULL default '0' COMMENT '추천수',
  `count_evaluation` int NOT NULL default '0' COMMENT '평가자 수',
  `count_cp_hit` int NOT NULL default '0' COMMENT 'cp조회수',
  `reading_rate` double NOT NULL default '0' COMMENT '연독률',
  `writing_count_per_week` double NOT NULL default '0' COMMENT '주평균 연재횟수',
  `count_interest_sustain` int NOT NULL default '0' COMMENT '관심유지수',
  `count_interest_loss` int NOT NULL default '0' COMMENT '관심 탈락수',
  `primary_reader_group1` varchar(200) NULL COMMENT '주요 독자층1',
  `primary_reader_group2` varchar(200) NULL COMMENT '주요 독자층2',
  `primary_genre` varchar(200) NULL COMMENT '1차 장르',
  `sub_genre` varchar(200) NULL COMMENT '2차 장르',
  `score1` int default '0' COMMENT '라이크노벨 평가1',
  `score2` int default '0' COMMENT '라이크노벨 평가2',
  `score3` int default '0' COMMENT '라이크노벨 평가3',
  `created_id` int DEFAULT NULL COMMENT 'row를 생성한 id',
  `created_date` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_id` int DEFAULT NULL COMMENT 'row를 갱신한 id',
  `updated_date` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  primary key (`id`),
  KEY `product_id` (`product_id`)
) ENGINE=InnoDB AUTO_INCREMENT=0 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;

-- 작품별 월매출 및 월별 정산용 임시 합산
create table `tb_ptn_product_sales_temp_summary` (
  `id` int not null auto_increment,
  `product_id` int NOT NULL COMMENT '작품 id',
  `sum_normal_price_web` int NOT NULL default '0' COMMENT '일반구매(웹)',
  `sum_normal_price_playstore` int NOT NULL default '0' COMMENT '일반구매(구글)',
  `sum_normal_price_ios` int NOT NULL default '0' COMMENT '일반구매(애플)',
  `sum_normal_price_onestore` int NOT NULL default '0' COMMENT '일반구매(원스토어)',
  `sum_discount_price_web` int NOT NULL default '0' COMMENT '할인구매(웹)',
  `sum_discount_price_playstore` int NOT NULL default '0' COMMENT '할인구매(구글)',
  `sum_discount_price_ios` int NOT NULL default '0' COMMENT '할인구매(애플)',
  `sum_discount_price_onestore` int NOT NULL default '0' COMMENT '할인구매(원스토어)',
  `sum_paid_ticket_price_web` int NOT NULL default '0' COMMENT '유상 대여권(웹)',
  `sum_paid_ticket_price_playstore` int NOT NULL default '0' COMMENT '유상 대여권(구글)',
  `sum_paid_ticket_price_ios` int NOT NULL default '0' COMMENT '유상 대여권(애플)',
  `sum_paid_ticket_price_onestore` int NOT NULL default '0' COMMENT '유상 대여권(원스토어)',
  `sum_comped_ticket_price_web` int NOT NULL default '0' COMMENT '무상 대여권(웹)',
  `sum_comped_ticket_price_playstore` int NOT NULL default '0' COMMENT '무상 대여권(구글)',
  `sum_comped_ticket_price_ios` int NOT NULL default '0' COMMENT '무상 대여권(애플)',
  `sum_comped_ticket_price_onestore` int NOT NULL default '0' COMMENT '무상 대여권(원스토어)',
  `sum_free_ticket_price_web` int NOT NULL default '0' COMMENT '무료 대여권(웹)',
  `sum_free_ticket_price_playstore` int NOT NULL default '0' COMMENT '무료 대여권(구글)',
  `sum_free_ticket_price_ios` int NOT NULL default '0' COMMENT '무료 대여권(애플)',
  `sum_free_ticket_price_onestore` int NOT NULL default '0' COMMENT '무료 대여권(원스토어)',
  `sum_refund_normal_price_web` int NOT NULL default '0' COMMENT '일반구매 취소액(웹)',
  `sum_refund_normal_price_playstore` int NOT NULL default '0' COMMENT '일반구매 취소액(구글)',
  `sum_refund_normal_price_ios` int NOT NULL default '0' COMMENT '일반구매 취소액(애플)',
  `sum_refund_normal_price_onestore` int NOT NULL default '0' COMMENT '일반구매 취소액(원스토어)',
  `sum_refund_discount_price_web` int NOT NULL default '0' COMMENT '할인구매 취소액(웹)',
  `sum_refund_discount_price_playstore` int NOT NULL default '0' COMMENT '할인구매 취소액(구글)',
  `sum_refund_discount_price_ios` int NOT NULL default '0' COMMENT '할인구매 취소액(애플)',
  `sum_refund_discount_price_onestore` int NOT NULL default '0' COMMENT '할인구매 취소액(원스토어)',
  `sum_refund_paid_ticket_price_web` int NOT NULL default '0' COMMENT '유상 대여권 취소액(웹)',
  `sum_refund_paid_ticket_price_playstore` int NOT NULL default '0' COMMENT '유상 대여권 취소액(구글)',
  `sum_refund_paid_ticket_price_ios` int NOT NULL default '0' COMMENT '유상 대여권 취소액(애플)',
  `sum_refund_paid_ticket_price_onestore` int NOT NULL default '0' COMMENT '유상 대여권 취소액(원스토어)',
  `sum_refund_comped_ticket_price_web` int NOT NULL default '0' COMMENT '무상 대여권 취소액(웹)',
  `sum_refund_comped_ticket_price_playstore` int NOT NULL default '0' COMMENT '무상 대여권 취소액(구글)',
  `sum_refund_comped_ticket_price_ios` int NOT NULL default '0' COMMENT '무상 대여권 취소액(애플)',
  `sum_refund_comped_ticket_price_onestore` int NOT NULL default '0' COMMENT '무상 대여권 취소액(원스토어)',
  `sum_refund_free_ticket_price_web` int NOT NULL default '0' COMMENT '무료 대여권 취소액(웹)',
  `sum_refund_free_ticket_price_playstore` int NOT NULL default '0' COMMENT '무료 대여권 취소액(구글)',
  `sum_refund_free_ticket_price_ios` int NOT NULL default '0' COMMENT '무료 대여권 취소액(애플)',
  `sum_refund_free_ticket_price_onestore` int NOT NULL default '0' COMMENT '무료 대여권 취소액(원스토어)',
  `created_id` int DEFAULT NULL COMMENT 'row를 생성한 id',
  `created_date` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_id` int DEFAULT NULL COMMENT 'row를 갱신한 id',
  `updated_date` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  primary key (`id`),
  key `product_id` (`product_id`)
) ENGINE=InnoDB AUTO_INCREMENT=0 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;

-- 후원 및 기타 정산용 임시 합산
create table `tb_ptn_income_settlement_temp_summary` (
  `id` int not null auto_increment,
  `product_id` int NOT NULL COMMENT '작품 id',
  `item_type` varchar(20) not null comment '소장, 대여, 후원',
  `device_type` varchar(20) not null comment '웹, 스토어',
  `sum_income_price` int NOT NULL default '0' COMMENT '기타수익금액',
  `created_id` int DEFAULT NULL COMMENT 'row를 생성한 id',
  `created_date` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_id` int DEFAULT NULL COMMENT 'row를 갱신한 id',
  `updated_date` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  primary key (`id`),
  key `product_id` (`product_id`)
) ENGINE=InnoDB AUTO_INCREMENT=0 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;

-- 작품 평가 관리(cms) // 랭킹, 발굴통계
create table `tb_cms_product_evaluation` (
  `id` int not null auto_increment,
  `product_id` int not null comment '작품 id',
  `weight_count_hit` double not null default '0' comment '가중치(조회수)',
  `weight_evaluation_score` double not null default '0' comment '가중치(평가점수)',
  `evaluation_score` int not null default '0' comment '평가점수',
  `score1` int default '0' comment '평가1',
  `score2` int default '0' comment '평가2',
  `score3` int default '0' comment '평가3',
  `evaluation_yn` varchar(1) not null default 'N' comment '평가여부',
  `created_id` int DEFAULT NULL COMMENT 'row를 생성한 id',
  `created_date` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_id` int DEFAULT NULL COMMENT 'row를 갱신한 id',
  `updated_date` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  primary key (`id`),
  key `product_id` (`product_id`)
) ENGINE=InnoDB AUTO_INCREMENT=0 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;

-- 작품별 월매출
create table `tb_ptn_product_sales` (
  `id` int not null auto_increment,
  `product_id` int NOT NULL COMMENT '작품 id',
  `title` varchar(100) NOT NULL COMMENT '작품명',
  `author_nickname` varchar(200) NOT NULL COMMENT '작가 닉네임',
  `contract_type` varchar(20) NULL COMMENT 'cp, 일반, 기타(null)',
  `cp_company_name` varchar(200) NULL COMMENT '담당cp 회사명',
  `paid_open_date` timestamp NULL COMMENT '판매시작일',
  `isbn` varchar(20) NULL COMMENT 'ISBN 코드',
  `uci` varchar(20) NULL COMMENT 'UCI 코드',
  `series_regular_price` int NOT NULL default '0' COMMENT '연재 가격',
  `sale_price` int NOT NULL default '0' COMMENT '판매가',
  `sum_normal_price_web` int NOT NULL default '0' COMMENT '일반구매(웹). 할인 포함',
  `sum_normal_price_playstore` int NOT NULL default '0' COMMENT '일반구매(구글). 할인 포함',
  `sum_normal_price_ios` int NOT NULL default '0' COMMENT '일반구매(애플). 할인 포함',
  `sum_normal_price_onestore` int NOT NULL default '0' COMMENT '일반구매(원스토어). 할인 포함',
  `sum_ticket_price_web` int NOT NULL default '0' COMMENT '대여권(웹). 무상 대여권 외',
  `sum_ticket_price_playstore` int NOT NULL default '0' COMMENT '대여권(구글). 무상 대여권 외',
  `sum_ticket_price_ios` int NOT NULL default '0' COMMENT '대여권(애플). 무상 대여권 외',
  `sum_ticket_price_onestore` int NOT NULL default '0' COMMENT '대여권(원스토어). 무상 대여권 외',
  `sum_comped_ticket_price` int NOT NULL default '0' COMMENT '무상 대여권 대여권',
  `fee_web` double NOT NULL default '0' COMMENT '결제수수료(웹)',
  `fee_playstore` double NOT NULL default '0' COMMENT '결제수수료(구글)',
  `fee_ios` double NOT NULL default '0' COMMENT '결제수수료(애플)',
  `fee_onestore` double NOT NULL default '0' COMMENT '결제수수료(원스토어)',
  `fee_comped_ticket` double NOT NULL default '0' COMMENT '무상 대여권 결제수수료',
  `sum_refund_price_web` int NOT NULL default '0' COMMENT '취소액(웹)',
  `sum_refund_price_playstore` int NOT NULL default '0' COMMENT '취소액(구글)',
  `sum_refund_price_ios` int NOT NULL default '0' COMMENT '취소액(애플)',
  `sum_refund_price_onestore` int NOT NULL default '0' COMMENT '취소액(원스토어)',
  `sum_refund_comped_ticket_price` int NOT NULL default '0' COMMENT '무상 대여권 취소액',
  `settlement_rate_web` double NOT NULL default '0' COMMENT '정산율(웹)',
  `settlement_rate_playstore` double NOT NULL default '0' COMMENT '정산율(구글)',
  `settlement_rate_ios` double NOT NULL default '0' COMMENT '정산율(애플)',
  `settlement_rate_onestore` double NOT NULL default '0' COMMENT '정산율(원스토어)',
  `settlement_rate_comped_ticket` double NOT NULL default '0' COMMENT '무상 대여권 정산율',
  `sum_settlement_price_web` int NOT NULL default '0' COMMENT '정산액(유상)',
  `sum_settlement_comped_ticket_price` int NOT NULL default '0' COMMENT '정산액(무상)',
  `tax_price` int NOT NULL default '0' COMMENT '세액',
  `total_price` int NOT NULL default '0' COMMENT '합계',
  `created_id` int DEFAULT NULL COMMENT 'row를 생성한 id',
  `created_date` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_id` int DEFAULT NULL COMMENT 'row를 갱신한 id',
  `updated_date` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  primary key (`id`),
  key `product_id` (`product_id`)
) ENGINE=InnoDB AUTO_INCREMENT=0 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;

-- 작품 정산 관리(cms)
create table `tb_cms_product_settlement` (
  `id` int not null auto_increment,
  `product_id` int NOT NULL COMMENT '작품 id',
  `item_type` varchar(20) not null comment '소장, 대여, 후원',
  `device_type` varchar(20) not null comment '웹, 스토어',
  `fee` double NOT NULL default '0' COMMENT '결제수수료', -- 고정치
  `settlement_rate` double NOT NULL default '0' COMMENT '정산율', -- 가변치
  `created_id` int DEFAULT NULL COMMENT 'row를 생성한 id',
  `created_date` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_id` int DEFAULT NULL COMMENT 'row를 갱신한 id',
  `updated_date` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  primary key (`id`),
  key `product_id` (`product_id`)
) ENGINE=InnoDB AUTO_INCREMENT=0 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;

-- 월별 정산
create table `tb_ptn_product_settlement` (
  `id` int not null auto_increment,
  `product_id` int NOT NULL COMMENT '작품 id',
  `item_type` varchar(20) not null comment '소장, 대여, 후원',
  `device_type` varchar(20) not null comment '웹, 스토어',
  `sum_total_sales_price` int NOT NULL default '0' COMMENT '매출액',
  `fee` double NOT NULL default '0' COMMENT '결제수수료',
  `net_sales_price` int NOT NULL default '0' COMMENT '순매출액(매출액 - 결제수수료)',
  `taxable_price` int NOT NULL default '0' COMMENT '공급가액(순매출액 - 플랫폼수익)',
  `vat_price` int NOT NULL default '0' COMMENT '부가세액(정산액 - 공급가액). 현재 0 고정',
  `settlement_price` int NOT NULL default '0' COMMENT '정산액(공급가액 / 1.1)',
  `platform_revenue` int NOT NULL default '0' COMMENT '플랫폼수익(라이크노벨 수익)',
  `privious_offer_amount` int NOT NULL default '0' COMMENT '당월 선계약금잔액',
  `current_offer_amount` int NOT NULL default '0' COMMENT '잔여계약금(정산후 잔액)',
  `final_settlement_price` int NOT NULL default '0' COMMENT '최종정산액',
  `created_id` int DEFAULT NULL COMMENT 'row를 생성한 id',
  `created_date` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_id` int DEFAULT NULL COMMENT 'row를 갱신한 id',
  `updated_date` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  primary key (`id`),
  key `product_id` (`product_id`)
) ENGINE=InnoDB AUTO_INCREMENT=0 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;

-- 선계약금 차감 조회
create table `tb_ptn_product_contract_offer_deduction` (
  `id` int not null auto_increment,
  `product_id` int NOT NULL COMMENT '작품 id',
  `title` varchar(100) NOT NULL COMMENT '작품명',
  `author_nickname` varchar(200) NOT NULL COMMENT '작가 닉네임',
  `contract_type` varchar(20) NULL COMMENT 'cp, 일반, 기타(null)',
  `cp_company_name` varchar(200) NULL COMMENT '담당cp 회사명',
  `offer_amount` int NOT NULL default '0' COMMENT '발행계약금',
  `privious_offer_amount` int NOT NULL default '0' COMMENT '당월 계약금 잔액',
  `settlement_price` int NOT NULL default '0' COMMENT '정산액',
  `current_offer_amount` int NOT NULL default '0' COMMENT '정산 후 잔액',
  `created_id` int DEFAULT NULL COMMENT 'row를 생성한 id',
  `created_date` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_id` int DEFAULT NULL COMMENT 'row를 갱신한 id',
  `updated_date` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  primary key (`id`),
  key `product_id` (`product_id`)
) ENGINE=InnoDB AUTO_INCREMENT=0 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;

-- 후원 및 기타 정산
create table `tb_ptn_income_settlement` (
  `id` int not null auto_increment,
  `product_id` int NOT NULL COMMENT '작품 id',
  `item_type` varchar(20) not null comment '소장, 대여, 후원',
  `device_type` varchar(20) not null comment '웹, 스토어',
  `sum_income_price` int NOT NULL default '0' COMMENT '금액',
  `total_fee_rate` double NOT NULL default '0' COMMENT '결제수수료 및 플랫폼수수료',
  `sum_income_price_exclude_fee` int NOT NULL default '0' COMMENT '제외후 금액',
  `withholding_tax_rate` double NOT NULL default '0' COMMENT '원천징수세금',
  `sum_income_price_final` int NOT NULL default '0' COMMENT '최종정산액',
  `created_id` int DEFAULT NULL COMMENT 'row를 생성한 id',
  `created_date` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_id` int DEFAULT NULL COMMENT 'row를 갱신한 id',
  `updated_date` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  primary key (`id`),
  key `product_id` (`product_id`)
) ENGINE=InnoDB AUTO_INCREMENT=0 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
;


//////


-- 작품 리스트 조회용 쿼리
with tmp_product_episode_summary as (
    select product_id
         , count(1) as count_episode
         , sum(current_count_evaluation) as count_evaluation
      from tb_batch_daily_product_episode_count_summary
     group by product_id
),
tmp_contract_offer_summary as (
    select z.product_id
         , y.company_name as cp_company_name
      from tb_product_contract_offer z
     inner join tb_user_profile_apply y on z.offer_user_id = y.user_id -- TODO: cp 계약, cp 부여 모듈 구현 후 수정 및 최종 테스트 필(초안 개발 완료. 신규유저 아이디 컬럼 추가 혹은 회사명 컬럼 추가 필)
       and y.apply_type = 'cp'
       and y.approval_date is not null
     where z.use_yn = 'Y'
       and z.author_accept_yn = 'Y'
)
select a.product_id
     , a.title
     , a.author_name as author_nickname
     , coalesce(b.count_episode, 0) as count_episode -- 회차수
     , case when d.cp_company_name is null then null
            when d.cp_company_name = '라이크노벨' then '일반'
            else 'cp'
       end as contract_type -- 계약유형
     , d.cp_company_name -- 담당CP
     , a.created_date -- 작품등록일
     , a.paid_open_date -- 유료시작일(판매시작일)
     , a.isbn -- isbn
     , a.uci -- uci
     , a.status_code -- 연재상태
     , a.ratings_code -- 연령등급
     , case when a.price_type = 'paid' then 'Y'
            else 'N'
       end as paid_yn -- 유료여부
     , (select z.keyword_name from tb_standard_keyword z
         where z.use_yn = 'Y'
           and z.major_genre_yn = 'Y'
           and a.primary_genre_id = z.keyword_id) as primary_genre -- 1차 장르
     , (select z.keyword_name from tb_standard_keyword z
         where z.use_yn = 'Y'
           and z.major_genre_yn = 'Y'
           and a.sub_genre_id = z.keyword_id) as sub_genre -- 2차 장르
     , a.single_regular_price -- 단행본
     , a.series_regular_price -- 연재
  from tb_product a
  left join tmp_product_episode_summary b on a.product_id = b.product_id
  left join tmp_contract_offer_summary d on a.product_id = d.product_id
;

