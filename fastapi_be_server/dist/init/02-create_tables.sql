-- LikeNovel 전체 테이블 생성 SQL (샘플)
-- settings: VARCHAR_COMM_SIZE=300, VARCHAR_CODE_SIZE=20, VARCHAR_ID_SIZE=30, VARCHAR_YN_SIZE=1

USE likenovel;

-- tb_user
CREATE TABLE tb_user (
    user_id INT AUTO_INCREMENT PRIMARY KEY,
    kc_user_id VARCHAR(36) NOT NULL UNIQUE COMMENT '키클록 user_entity pk',
    email VARCHAR(100) COMMENT '이메일(sns 로그인 연동은 서비스 제공자에 등록된 값 그대로 활용)',
    gender VARCHAR(1) COMMENT '성별',
    birthdate VARCHAR(10) COMMENT '생년월일',
    user_name VARCHAR(100) COMMENT '실명',
    mobile_no VARCHAR(100) COMMENT '휴대폰번호',
    identity_yn VARCHAR(1) DEFAULT 'N' COMMENT '본인인증 여부',
    agree_terms_yn VARCHAR(1) DEFAULT 'Y' COMMENT '이용약관 동의 여부',
    agree_privacy_yn VARCHAR(1) DEFAULT 'Y' COMMENT '개인정보 동의 여부',
    agree_age_limit_yn VARCHAR(1) DEFAULT 'Y' COMMENT '만14세이상 여부',
    stay_signed_yn VARCHAR(1) DEFAULT 'N' COMMENT '로그인유지 여부',
    latest_signed_date TIMESTAMP NULL COMMENT '최근 로그인한 일자',
    latest_signed_type VARCHAR(20) NOT NULL COMMENT '최근 로그인 타입(자체, 네이버, 구글, 카카오, 애플)',
    use_yn VARCHAR(1) DEFAULT 'Y' COMMENT '사용 여부',
    role_type VARCHAR(20) DEFAULT 'normal' NOT NULL COMMENT '권한 - 일반 사용자, 관리자',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일'
);

-- tb_user_notification
CREATE TABLE tb_user_notification (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL COMMENT '유저 아이디',
    noti_type VARCHAR(20) NOT NULL COMMENT '알림 동의 여부 - 혜택정보, 댓글, 시스템, 이벤트',
    noti_yn VARCHAR(1) DEFAULT 'N' COMMENT '알림 여부',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_user_id (user_id),
    INDEX idx_noti_type (noti_type)
);

-- tb_user_notification_item
CREATE TABLE tb_user_notification_item (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL COMMENT '유저 아이디',
    noti_type VARCHAR(20) NOT NULL COMMENT '알림 타입',
    read_yn VARCHAR(1) DEFAULT 'N' COMMENT '읽음 여부',
    title VARCHAR(300) NOT NULL COMMENT '제목',
    content VARCHAR(300) NOT NULL COMMENT '내용',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_user_id (user_id),
    INDEX idx_noti_type (noti_type)
);

-- tb_product
CREATE TABLE tb_product (
    product_id INT AUTO_INCREMENT PRIMARY KEY,
    title VARCHAR(100) NOT NULL COMMENT '작품 제목',
    price_type VARCHAR(20) NOT NULL COMMENT '가격구분(무료-free, 유료-paid)',
    product_type VARCHAR(20) COMMENT '구분(자유, 일반)',
    status_code VARCHAR(20) NOT NULL COMMENT '상태코드(연재중-ongoing, 휴재중-rest, 완결-end, 연재중지-stop)',
    ratings_code VARCHAR(20) NOT NULL COMMENT '연령등급(전체-all, 성인-adult)',
    synopsis_text VARCHAR(3000) COMMENT '작품 소개',
    user_id INT NOT NULL COMMENT '유저 아이디',
    author_id INT NOT NULL COMMENT '작가 아이디',
    author_name VARCHAR(100) COMMENT '작가 이름',
    illustrator_id INT COMMENT '그림작가 아이디',
    illustrator_name VARCHAR(100) COMMENT '그림작가 이름',
    publish_regular_yn VARCHAR(1) DEFAULT 'N' COMMENT '정기 여부 - 비정기 체크 시 Y',
    publish_days VARCHAR(300) NOT NULL COMMENT '연재 요일',
    thumbnail_file_id INT COMMENT '표지 이미지 파일',
    primary_genre_id INT NOT NULL COMMENT '1차 장르',
    sub_genre_id INT COMMENT '2차 장르',
    count_hit INT DEFAULT 0 COMMENT '조회수',
    count_cp_hit INT DEFAULT 0 COMMENT 'cp 조회수',
    count_recommend INT DEFAULT 0 COMMENT '추천수',
    count_bookmark INT DEFAULT 0 COMMENT '북마크수',
    count_unbookmark INT DEFAULT 0 COMMENT '북마크 해제수',
    open_yn VARCHAR(1) DEFAULT 'N' COMMENT '공개 여부',
    approval_yn VARCHAR(1) DEFAULT 'N' COMMENT '유료 승인 여부',
    monopoly_yn VARCHAR(1) DEFAULT 'N' COMMENT '독점 여부',
    contract_yn VARCHAR(1) DEFAULT 'N' COMMENT '계약 여부',
    paid_open_date TIMESTAMP NULL COMMENT '유료회차 시작 일시',
    paid_episode_no INT COMMENT '유료시작 회차(episode)',
    last_episode_date TIMESTAMP NULL COMMENT '최근 회차 일자',
    isbn VARCHAR(20) COMMENT 'isbn 코드',
    uci VARCHAR(20) COMMENT 'uci 코드',
    single_regular_price INT DEFAULT 0 COMMENT '단행본 가격',
    series_regular_price INT DEFAULT 0 COMMENT '연재 가격',
    sale_price INT DEFAULT 0 COMMENT '판매가',
    apply_date TIMESTAMP NULL COMMENT '승급 신청 승인 일시',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일'
);

-- tb_store_order
CREATE TABLE tb_store_order (
    order_id INT AUTO_INCREMENT PRIMARY KEY,
    device_type VARCHAR(20) NOT NULL COMMENT '웹, 앱',
    order_no INT DEFAULT 0 COMMENT '주문 번호',
    user_id INT NOT NULL COMMENT '유저 아이디',
    order_date TIMESTAMP NULL COMMENT '주문 일자',
    order_status VARCHAR(20) NOT NULL COMMENT '주문 상태',
    total_price INT DEFAULT 0 COMMENT '총 가격',
    cancel_yn VARCHAR(1) DEFAULT 'N' COMMENT '취소 여부',
    invoice_no INT NULL COMMENT 'invoice_no',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일'
);

-- tb_store_order_item
CREATE TABLE tb_store_order_item (
    id INT AUTO_INCREMENT PRIMARY KEY,
    order_id INT NOT NULL COMMENT '주문 아이디',
    item_id INT NOT NULL COMMENT '아이템 아이디',
    item_name VARCHAR(200) COMMENT '아이템 이름',
    item_price INT DEFAULT 0 COMMENT '아이템 가격',
    cancel_yn VARCHAR(1) DEFAULT 'N' COMMENT '취소 여부',
    quantity INT DEFAULT 0 COMMENT '수량',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_order_id (order_id),
    INDEX idx_item_id (item_id)
);

-- tb_store_payment
CREATE TABLE tb_store_payment (
    id INT AUTO_INCREMENT PRIMARY KEY,
    order_id INT NOT NULL COMMENT '주문 아이디',
    total_price INT DEFAULT 0 COMMENT '총 수량',
    pg_name VARCHAR(50) NOT NULL COMMENT 'PG회사(PORTNAME…)',
    pg_payment_id VARCHAR(50) COMMENT 'PG 결제 아이디',
    pg_tx_id VARCHAR(50) COMMENT 'PG 거래 아이디',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_order_id (order_id)
);

-- tb_store_payment_info
CREATE TABLE tb_store_payment_info (
    payment_info_id INT AUTO_INCREMENT PRIMARY KEY,
    payment_id INT NOT NULL COMMENT '결제 아이디',
    pay_type VARCHAR(20) NOT NULL COMMENT '결제 타입',
    price INT DEFAULT 0 COMMENT '수량',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_payment_id (payment_id),
    INDEX idx_pay_type (pay_type)
);

-- tb_store_refund
CREATE TABLE tb_store_refund (
    id INT AUTO_INCREMENT PRIMARY KEY,
    refund_type VARCHAR(20) NOT NULL COMMENT '환불 타입',
    order_item_id INT NOT NULL COMMENT '주문 아이템 아이디',
    payment_info_id INT NOT NULL COMMENT '결제 정보 아이디',
    order_id INT NOT NULL COMMENT '주문 아이디',
    refund_price INT DEFAULT 0 COMMENT '환불금',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_order_item_id (order_item_id),
    INDEX idx_payment_info_id (payment_info_id),
    INDEX idx_order_id (order_id)
);

-- tb_store_item
CREATE TABLE tb_store_item (
    item_id INT AUTO_INCREMENT PRIMARY KEY,
    item_type VARCHAR(20) NOT NULL COMMENT '아이템 타입',
    item_name VARCHAR(200) COMMENT '아이템 이름',
    tax_free_yn VARCHAR(1) DEFAULT 'N' COMMENT '면세 여부',
    price INT DEFAULT 0 COMMENT '캐시금액',
    use_yn VARCHAR(1) DEFAULT 'Y' COMMENT '사용 여부',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_item_type (item_type)
);

-- tb_event
CREATE TABLE tb_event (
    id INT AUTO_INCREMENT PRIMARY KEY,
    event_type VARCHAR(20) NOT NULL COMMENT '상시진행, 기간진행',
    banner_file_id INT COMMENT '배너 이미지 파일 아이디',
    subject VARCHAR(300) COMMENT '이벤트 제목',
    content TEXT COMMENT '이벤트 내용',
    begin_date TIMESTAMP NULL COMMENT '이벤트 시작일',
    end_date TIMESTAMP NULL COMMENT '이벤트 종료일',
    close_yn VARCHAR(1) DEFAULT 'N' COMMENT '종료 여부',
    use_yn VARCHAR(1) DEFAULT 'Y' COMMENT '사용 여부',
    link_url VARCHAR(300) COMMENT '링크 url',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_event_type (event_type)
);

-- tb_notice
CREATE TABLE tb_notice (
    id INT AUTO_INCREMENT PRIMARY KEY,
    subject VARCHAR(300) COMMENT '공지 제목',
    content TEXT COMMENT '공지 내용',
    primary_yn VARCHAR(1) DEFAULT 'N' COMMENT '우선순위 여부',
    use_yn VARCHAR(1) DEFAULT 'Y' COMMENT '사용 여부',
    view_count INT DEFAULT 0 COMMENT '조회수',
    file_id INT COMMENT '파일 id',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일'
);

-- tb_faq
CREATE TABLE tb_faq (
    id INT AUTO_INCREMENT PRIMARY KEY,
    faq_type VARCHAR(20) NOT NULL COMMENT 'FAQ 타입',
    subject VARCHAR(300) COMMENT 'FAQ 제목',
    content TEXT COMMENT 'FAQ 내용',
    primary_yn VARCHAR(1) DEFAULT 'N' COMMENT '우선순위 여부',
    use_yn VARCHAR(1) DEFAULT 'Y' COMMENT '사용 여부',
    view_count INT DEFAULT 0 COMMENT '조회수',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_faq_type (faq_type)
);

-- tb_qna
CREATE TABLE tb_qna (
    id INT AUTO_INCREMENT PRIMARY KEY,
    category VARCHAR(20) NOT NULL COMMENT '분류',
    subject VARCHAR(300) COMMENT 'QnA 제목',
    content TEXT COMMENT 'QnA 내용',
    email VARCHAR(100) COMMENT '회신받을 이메일',
    user_id INT NOT NULL COMMENT '유저 아이디',
    attach_file_id INT COMMENT '첨부파일',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_category (category),
    INDEX idx_user_id (user_id)
);

-- tb_promotion
CREATE TABLE tb_promotion (
    promotion_id INT AUTO_INCREMENT PRIMARY KEY,
    promotion_type VARCHAR(20) NOT NULL COMMENT '프로모션 구분 - 직접, 신청',
    promotion_name VARCHAR(300) COMMENT '프로모션 이름',
    from_date TIMESTAMP NULL COMMENT '프로모션 시작 일시',
    to_date TIMESTAMP NULL COMMENT '프로모션 종료 일시',
    use_yn VARCHAR(1) DEFAULT 'Y' COMMENT '사용 여부',
    apply_type VARCHAR(20) COMMENT '신청구분 - 요일, 날짜',
    apply_status VARCHAR(20) COMMENT '신청 상태 - 신청, 승인, 철회',
    available_apply_date TIMESTAMP NULL COMMENT '신청 가능 일자',
    interval_apply_days INT DEFAULT 0 COMMENT '신청 가능 일자에 더해지는 term',
    max_seat_count INT DEFAULT 0 COMMENT '최대 신청 가능 수',
    item_type VARCHAR(20) COMMENT '아이템 구분 - 대여권(ticket) 등등',
    item_id INT COMMENT '아이템 아이디',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_promotion_type (promotion_type),
    INDEX idx_apply_type (apply_type),
    INDEX idx_apply_status (apply_status),
    INDEX idx_item_type (item_type)
);

-- tb_comm_code
CREATE TABLE tb_comm_code (
    code_id INT AUTO_INCREMENT PRIMARY KEY,
    code_type VARCHAR(20) NOT NULL COMMENT '코드 타입',
    code_value VARCHAR(100) NOT NULL COMMENT '코드 값',
    code_name VARCHAR(300) NOT NULL COMMENT '코드명',
    sort_order INT DEFAULT 0 COMMENT '정렬순서',
    use_yn VARCHAR(1) DEFAULT 'Y' COMMENT '사용 여부',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_code_type (code_type),
    INDEX idx_code_value (code_value)
);

-- tb_event_vote_round
CREATE TABLE tb_event_vote_round (
    round_product_id INT AUTO_INCREMENT PRIMARY KEY,
    round_no INT DEFAULT 0 COMMENT '투표 회차',
    use_yn VARCHAR(1) DEFAULT 'Y' COMMENT '사용 여부',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일'
);

-- tb_quest
CREATE TABLE tb_quest (
    quest_id INT AUTO_INCREMENT PRIMARY KEY,
    title VARCHAR(200) COMMENT '퀘스트명',
    reward_id INT NOT NULL COMMENT '보상 아이디',
    end_date TIMESTAMP NULL COMMENT '퀘스트 완료일',
    goal_stage INT DEFAULT 0 COMMENT '목표 단계',
    use_yn VARCHAR(1) DEFAULT 'Y' COMMENT '사용 여부',
    renewal VARCHAR(1000) COMMENT '갱신 주기 (각 요일별 갱신 여부 Y|N)',
    step1 VARCHAR(1000) COMMENT '1단계',
    step2 VARCHAR(1000) COMMENT '2단계',
    step3 VARCHAR(1000) COMMENT '3단계',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_reward_id (reward_id)
);

-- tb_event_vote
CREATE TABLE tb_event_vote (
    id INT AUTO_INCREMENT PRIMARY KEY,
    round_product_id INT NOT NULL COMMENT '투표 작품 아이디',
    product_id INT NOT NULL COMMENT '작품 아이디',
    round_no INT DEFAULT 0 COMMENT '투표 회차',
    from_date TIMESTAMP NULL COMMENT '투표 시작일',
    to_date TIMESTAMP NULL COMMENT '투표 종료일',
    use_yn VARCHAR(1) DEFAULT 'Y' COMMENT '사용 여부',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_round_product_id (round_product_id),
    INDEX idx_product_id (product_id)
);

-- tb_event_vote_winner
CREATE TABLE tb_event_vote_winner (
    id INT AUTO_INCREMENT PRIMARY KEY,
    round_product_id INT NOT NULL COMMENT '투표 작품 아이디',
    rank_no INT DEFAULT 0 COMMENT '순위',
    user_id INT NOT NULL COMMENT '유저 아이디',
    use_yn VARCHAR(1) DEFAULT 'Y' COMMENT '사용 여부',
    round_no INT DEFAULT 0 COMMENT '투표 회차',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_round_product_id (round_product_id),
    INDEX idx_user_id (user_id)
);

-- tb_event_vote_user_req
CREATE TABLE tb_event_vote_user_req (
    id INT AUTO_INCREMENT PRIMARY KEY,
    round_product_id INT NOT NULL COMMENT '투표 작품 아이디',
    round_no INT DEFAULT 0 COMMENT '투표 회차',
    user_id INT NOT NULL COMMENT '유저 아이디',
    product_id INT NOT NULL COMMENT '작품 아이디',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_round_product_id (round_product_id),
    INDEX idx_user_id (user_id),
    INDEX idx_product_id (product_id)
);

-- tb_event_vote_product_item
CREATE TABLE tb_event_vote_product_item (
    id INT AUTO_INCREMENT PRIMARY KEY,
    round_product_id INT NOT NULL COMMENT '투표 작품 아이디',
    round_no INT DEFAULT 0 COMMENT '투표 회차',
    product_id INT NOT NULL COMMENT '작품 아이디',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_round_product_id (round_product_id),
    INDEX idx_product_id (product_id)
);

-- tb_event_vote_round_answer
CREATE TABLE tb_event_vote_round_answer (
    id INT AUTO_INCREMENT PRIMARY KEY,
    round_product_id INT NOT NULL COMMENT '투표 작품 아이디',
    round_no INT DEFAULT 0 COMMENT '투표 회차',
    product_id INT NOT NULL COMMENT '작품 아이디',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_round_product_id (round_product_id),
    INDEX idx_product_id (product_id)
);

-- tb_quest_user
CREATE TABLE tb_quest_user (
    id INT AUTO_INCREMENT PRIMARY KEY,
    quest_id INT NOT NULL COMMENT '퀘스트 아이디',
    user_id INT NOT NULL COMMENT '유저 아이디',
    achieve_yn VARCHAR(1) DEFAULT 'N' COMMENT '달성 여부',
    reward_own_yn VARCHAR(1) DEFAULT 'N' COMMENT '보상 소유 여부',
    current_stage INT DEFAULT 0 COMMENT '현재 진행단계',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_quest_id (quest_id),
    INDEX idx_user_id (user_id)
);

-- tb_quest_reward
CREATE TABLE tb_quest_reward (
    reward_id INT AUTO_INCREMENT PRIMARY KEY,
    quest_id INT NOT NULL COMMENT '퀘스트 아이디',
    item_id INT NOT NULL COMMENT '아이템 아이디',
    item_type VARCHAR(20) NOT NULL COMMENT '보상 아이템 타입',
    item_name VARCHAR(200) COMMENT '보상 아이템 이름',
    goal_stage INT DEFAULT 0 COMMENT '보상 목표 단계',
    quantity INT DEFAULT 0 COMMENT '수량',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_quest_id (quest_id),
    INDEX idx_item_id (item_id),
    INDEX idx_item_type (item_type)
);

-- tb_carousel_banner
CREATE TABLE tb_carousel_banner (
    id INT AUTO_INCREMENT PRIMARY KEY,
    position VARCHAR(50) NOT NULL COMMENT '노출 위치',
    division VARCHAR(50) NULL COMMENT '노출 위치 - position이 main인 경우 세부 위치',
    title VARCHAR(1000) NOT NULL COMMENT '배너명',
    show_start_date TIMESTAMP NOT NULL COMMENT '노출 기간 시작일',
    show_end_date TIMESTAMP NOT NULL COMMENT '노출 기간 종료일',
    show_order INT NOT NULL COMMENT '노출 순서',
    `url` VARCHAR(1000) NOT NULL COMMENT '링크 url',
    image_id INT NOT NULL COMMENT '이미지 id',
    mobile_image_id INT NOT NULL COMMENT '모바일 이미지 id',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일'
);

-- tb_publisher_promotion
CREATE TABLE tb_publisher_promotion (
    id INT AUTO_INCREMENT PRIMARY KEY,
    product_id INT NOT NULL COMMENT '작품 아이디',
    show_order INT NOT NULL COMMENT '노출 순서',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일'
);

-- tb_comm_message
CREATE TABLE tb_comm_message (
    message_id INT AUTO_INCREMENT PRIMARY KEY,
    message_type VARCHAR(20) NOT NULL COMMENT '메시지 타입',
    message_title VARCHAR(300) COMMENT '메시지 제목',
    message_content TEXT COMMENT '메시지 내용',
    use_yn VARCHAR(1) DEFAULT 'Y' COMMENT '사용 여부',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_message_type (message_type)
);

-- tb_comm_banner
CREATE TABLE tb_comm_banner (
    banner_id INT AUTO_INCREMENT PRIMARY KEY,
    banner_type VARCHAR(20) NOT NULL COMMENT '배너 타입',
    banner_title VARCHAR(300) COMMENT '배너 제목',
    banner_image VARCHAR(300) COMMENT '배너 이미지',
    link_url VARCHAR(300) COMMENT '배너 링크',
    use_yn VARCHAR(1) DEFAULT 'Y' COMMENT '사용 여부',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_banner_type (banner_type)
);

-- tb_comm_file
CREATE TABLE tb_comm_file (
    file_id INT AUTO_INCREMENT PRIMARY KEY,
    file_type VARCHAR(20) NOT NULL COMMENT '파일 타입',
    file_name VARCHAR(300) NOT NULL COMMENT '파일명',
    file_path VARCHAR(300) NOT NULL COMMENT '파일 경로',
    file_size INT DEFAULT 0 COMMENT '파일 크기',
    use_yn VARCHAR(1) DEFAULT 'Y' COMMENT '사용 여부',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_file_type (file_type)
);

-- tb_common_file
CREATE TABLE tb_common_file (
    file_group_id INT AUTO_INCREMENT PRIMARY KEY,
    group_type VARCHAR(20) NOT NULL COMMENT '그룹 타입',
    use_yn VARCHAR(1) DEFAULT 'Y' COMMENT '사용 여부',
    created_id INT NULL COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_id INT NULL COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_group_type (group_type)
);

-- tb_common_file_item
CREATE TABLE tb_common_file_item (
    file_id INT AUTO_INCREMENT PRIMARY KEY,
    file_group_id INT NOT NULL COMMENT '파일 그룹 아이디',
    file_name VARCHAR(255) NULL COMMENT 'uuid 파일명',
    file_org_name VARCHAR(255) NULL COMMENT '원본 파일명',
    file_size INT DEFAULT 0 COMMENT '파일 사이즈',
    file_path VARCHAR(255) NULL COMMENT '파일 경로',
    use_yn VARCHAR(1) DEFAULT 'Y' COMMENT '사용 여부',
    created_id INT NULL COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_id INT NULL COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_file_group_id (file_group_id)
);

-- tb_comm_log
CREATE TABLE tb_comm_log (
    log_id INT AUTO_INCREMENT PRIMARY KEY,
    log_type VARCHAR(20) NOT NULL COMMENT '로그 타입',
    log_content TEXT COMMENT '로그 내용',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_log_type (log_type)
);

-- tb_comm_alarm
CREATE TABLE tb_comm_alarm (
    alarm_id INT AUTO_INCREMENT PRIMARY KEY,
    alarm_type VARCHAR(20) NOT NULL COMMENT '알람 타입',
    alarm_title VARCHAR(300) COMMENT '알람 제목',
    alarm_content TEXT COMMENT '알람 내용',
    use_yn VARCHAR(1) DEFAULT 'Y' COMMENT '사용 여부',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_alarm_type (alarm_type)
);

-- tb_comm_terms
CREATE TABLE tb_comm_terms (
    terms_id INT AUTO_INCREMENT PRIMARY KEY,
    terms_type VARCHAR(20) NOT NULL COMMENT '약관 타입',
    terms_title VARCHAR(300) COMMENT '약관 제목',
    terms_content TEXT COMMENT '약관 내용',
    use_yn VARCHAR(1) DEFAULT 'Y' COMMENT '사용 여부',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_terms_type (terms_type)
);

-- tb_comm_popup
CREATE TABLE tb_comm_popup (
    id INT AUTO_INCREMENT PRIMARY KEY,
    title VARCHAR(300) COMMENT '팝업 제목',
    content TEXT COMMENT '팝업 내용',
    image_id INT COMMENT '이미지 id',
    start_date DATETIME NOT NULL COMMENT '노출 시작일',
    end_date DATETIME NOT NULL COMMENT '노출 종료일',
    use_yn VARCHAR(1) DEFAULT 'Y' COMMENT '사용 여부',
    url TEXT COMMENT 'url',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_popup_type (popup_type)
);

-- tb_comm_faq
CREATE TABLE tb_comm_faq (
    faq_id INT AUTO_INCREMENT PRIMARY KEY,
    faq_type VARCHAR(20) NOT NULL COMMENT 'FAQ 타입',
    faq_title VARCHAR(300) COMMENT 'FAQ 제목',
    faq_content TEXT COMMENT 'FAQ 내용',
    use_yn VARCHAR(1) DEFAULT 'Y' COMMENT '사용 여부',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_faq_type (faq_type)
);

-- tb_comm_qna
CREATE TABLE tb_comm_qna (
    qna_id INT AUTO_INCREMENT PRIMARY KEY,
    qna_type VARCHAR(20) NOT NULL COMMENT 'QnA 타입',
    qna_title VARCHAR(300) COMMENT 'QnA 제목',
    qna_content TEXT COMMENT 'QnA 내용',
    use_yn VARCHAR(1) DEFAULT 'Y' COMMENT '사용 여부',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_qna_type (qna_type)
);

-- tb_comm_notice
CREATE TABLE tb_comm_notice (
    notice_id INT AUTO_INCREMENT PRIMARY KEY,
    notice_type VARCHAR(20) NOT NULL COMMENT '공지 타입',
    notice_title VARCHAR(300) COMMENT '공지 제목',
    notice_content TEXT COMMENT '공지 내용',
    use_yn VARCHAR(1) DEFAULT 'Y' COMMENT '사용 여부',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_notice_type (notice_type)
);

-- tb_comm_event
CREATE TABLE tb_comm_event (
    event_id INT AUTO_INCREMENT PRIMARY KEY,
    event_type VARCHAR(20) NOT NULL COMMENT '이벤트 타입',
    event_title VARCHAR(300) COMMENT '이벤트 제목',
    event_content TEXT COMMENT '이벤트 내용',
    use_yn VARCHAR(1) DEFAULT 'Y' COMMENT '사용 여부',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_event_type (event_type)
);

-- tb_comm_policy
CREATE TABLE tb_comm_policy (
    policy_id INT AUTO_INCREMENT PRIMARY KEY,
    policy_type VARCHAR(20) NOT NULL COMMENT '정책 타입',
    policy_title VARCHAR(300) COMMENT '정책 제목',
    policy_content TEXT COMMENT '정책 내용',
    use_yn VARCHAR(1) DEFAULT 'Y' COMMENT '사용 여부',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_policy_type (policy_type)
);

-- tb_comm_survey
CREATE TABLE tb_comm_survey (
    survey_id INT AUTO_INCREMENT PRIMARY KEY,
    survey_type VARCHAR(20) NOT NULL COMMENT '설문 타입',
    survey_title VARCHAR(300) COMMENT '설문 제목',
    survey_content TEXT COMMENT '설문 내용',
    use_yn VARCHAR(1) DEFAULT 'Y' COMMENT '사용 여부',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_survey_type (survey_type)
);

-- tb_comm_advertise
CREATE TABLE tb_comm_advertise (
    advertise_id INT AUTO_INCREMENT PRIMARY KEY,
    advertise_type VARCHAR(20) NOT NULL COMMENT '광고 타입',
    advertise_title VARCHAR(300) COMMENT '광고 제목',
    advertise_content TEXT COMMENT '광고 내용',
    use_yn VARCHAR(1) DEFAULT 'Y' COMMENT '사용 여부',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_advertise_type (advertise_type)
);

-- tb_comm_feedback
CREATE TABLE tb_comm_feedback (
    feedback_id INT AUTO_INCREMENT PRIMARY KEY,
    feedback_type VARCHAR(20) NOT NULL COMMENT '피드백 타입',
    feedback_title VARCHAR(300) COMMENT '피드백 제목',
    feedback_content TEXT COMMENT '피드백 내용',
    use_yn VARCHAR(1) DEFAULT 'Y' COMMENT '사용 여부',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_feedback_type (feedback_type)
);

-- tb_comm_help
CREATE TABLE tb_comm_help (
    help_id INT AUTO_INCREMENT PRIMARY KEY,
    help_type VARCHAR(20) NOT NULL COMMENT '도움말 타입',
    help_title VARCHAR(300) COMMENT '도움말 제목',
    help_content TEXT COMMENT '도움말 내용',
    use_yn VARCHAR(1) DEFAULT 'Y' COMMENT '사용 여부',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_help_type (help_type)
);

-- tb_comm_guide
CREATE TABLE tb_comm_guide (
    guide_id INT AUTO_INCREMENT PRIMARY KEY,
    guide_type VARCHAR(20) NOT NULL COMMENT '가이드 타입',
    guide_title VARCHAR(300) COMMENT '가이드 제목',
    guide_content TEXT COMMENT '가이드 내용',
    use_yn VARCHAR(1) DEFAULT 'Y' COMMENT '사용 여부',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_guide_type (guide_type)
);

-- tb_comm_report
CREATE TABLE tb_comm_report (
    report_id INT AUTO_INCREMENT PRIMARY KEY,
    report_type VARCHAR(20) NOT NULL COMMENT '신고 타입',
    report_title VARCHAR(300) COMMENT '신고 제목',
    report_content TEXT COMMENT '신고 내용',
    use_yn VARCHAR(1) DEFAULT 'Y' COMMENT '사용 여부',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_report_type (report_type)
);

-- tb_comm_sitemap
CREATE TABLE tb_comm_sitemap (
    sitemap_id INT AUTO_INCREMENT PRIMARY KEY,
    sitemap_type VARCHAR(20) NOT NULL COMMENT '사이트맵 타입',
    sitemap_title VARCHAR(300) COMMENT '사이트맵 제목',
    sitemap_content TEXT COMMENT '사이트맵 내용',
    use_yn VARCHAR(1) DEFAULT 'Y' COMMENT '사용 여부',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_sitemap_type (sitemap_type)
);

-- tb_comm_version
CREATE TABLE tb_comm_version (
    version_id INT AUTO_INCREMENT PRIMARY KEY,
    version_type VARCHAR(20) NOT NULL COMMENT '버전 타입',
    version_title VARCHAR(300) COMMENT '버전 제목',
    version_content TEXT COMMENT '버전 내용',
    use_yn VARCHAR(1) DEFAULT 'Y' COMMENT '사용 여부',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_version_type (version_type)
);

-- tb_user_block
CREATE TABLE tb_user_block (
    id INT AUTO_INCREMENT PRIMARY KEY,
    product_id INT NOT NULL COMMENT '작품 아이디',
    episode_id INT NOT NULL COMMENT '회차 아이디',
    comment_id INT NOT NULL COMMENT '댓글 아이디',
    user_id INT NOT NULL COMMENT '유저 아이디',
    off_user_id INT NOT NULL COMMENT '차단한 유저 아이디',
    off_yn VARCHAR(1) DEFAULT 'Y' COMMENT '차단 여부',
    use_yn VARCHAR(1) DEFAULT 'Y' COMMENT '사용 여부',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_product_id (product_id),
    INDEX idx_episode_id (episode_id),
    INDEX idx_comment_id (comment_id),
    INDEX idx_user_id (user_id),
    INDEX idx_off_user_id (off_user_id)
);

-- tb_user_report
CREATE TABLE tb_user_report (
    id INT AUTO_INCREMENT PRIMARY KEY,
    product_id INT NOT NULL COMMENT '작품 아이디',
    episode_id INT NOT NULL COMMENT '회차 아이디',
    comment_id INT NOT NULL COMMENT '댓글 아이디',
    user_id INT NOT NULL COMMENT '유저 아이디',
    reported_user_id INT NOT NULL COMMENT '신고된 유저 아이디',
    report_type VARCHAR(20) COMMENT '신고 타입',
    content VARCHAR(300) COMMENT '신고 내용',
    use_yn VARCHAR(1) DEFAULT 'Y' COMMENT '사용 여부',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_product_id (product_id),
    INDEX idx_episode_id (episode_id),
    INDEX idx_comment_id (comment_id),
    INDEX idx_user_id (user_id),
    INDEX idx_reported_user_id (reported_user_id),
    INDEX idx_report_type (report_type)
);

-- tb_user_alarm
CREATE TABLE tb_user_alarm (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL COMMENT '유저 아이디',
    title VARCHAR(300) COMMENT '제목',
    content VARCHAR(300) COMMENT '내용',
    read_yn VARCHAR(1) DEFAULT 'N' COMMENT '읽음 여부',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_user_id (user_id)
);

-- tb_user_cashbook
CREATE TABLE tb_user_cashbook (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL COMMENT '유저 아이디',
    balance INT DEFAULT 0 COMMENT '잔액',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_user_id (user_id)
);

-- tb_user_cashbook_transaction
CREATE TABLE tb_user_cashbook_transaction (
    id INT AUTO_INCREMENT PRIMARY KEY,
    from_user_id INT NOT NULL COMMENT '송신한 유저 아이디',
    to_user_id INT NOT NULL COMMENT '수신한 유저 아이디',
    amount INT DEFAULT 0 COMMENT '수량',
    use_yn VARCHAR(1) DEFAULT 'Y' COMMENT '사용 여부',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_from_user_id (from_user_id),
    INDEX idx_to_user_id (to_user_id)
);

-- tb_user_giftbook
CREATE TABLE tb_user_giftbook (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL COMMENT '유저 아이디',
    ticket_item_id INT NOT NULL COMMENT '대여권 아이디',
    read_yn VARCHAR(1) DEFAULT 'N' COMMENT '읽음 여부',
    received_yn VARCHAR(1) DEFAULT 'N' COMMENT '선물받기 여부',
    received_date TIMESTAMP NULL COMMENT '선물받기한 날짜'
    reason VARCHAR(300) DEFAULT '' COMMENT '대여권 지급 사유',
    amount INT DEFAULT 1 COMMENT '대여권 장수',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_user_id (user_id),
    INDEX idx_item_id (ticket_item_id)
);

-- tb_user_gift_transaction
CREATE TABLE tb_user_gift_transaction (
    id INT AUTO_INCREMENT PRIMARY KEY,
    created_id VARCHAR(30) COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id VARCHAR(30) COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일'
);

-- tb_user_ticketbook
CREATE TABLE tb_user_ticketbook (
    id INT AUTO_INCREMENT PRIMARY KEY,
    ticket_type VARCHAR(20) NOT NULL COMMENT '대여권타입',
    user_id INT NOT NULL COMMENT '유저 아이디',
    product_id INT NOT NULL COMMENT '작품 아이디',
    use_expired_date TIMESTAMP NULL COMMENT '대여권 만료일자',
    use_yn VARCHAR(1) DEFAULT 'Y' COMMENT '사용 여부',
    created_id VARCHAR(30) COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id VARCHAR(30) COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_ticket_type (ticket_type),
    INDEX idx_user_id (user_id),
    INDEX idx_product_id (product_id)
);

-- tb_user_ticket_transaction
CREATE TABLE tb_user_ticket_transaction (
    id INT AUTO_INCREMENT PRIMARY KEY,
    created_id VARCHAR(30) COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id VARCHAR(30) COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일'
);

-- tb_user_productbook
CREATE TABLE tb_user_productbook (
    id INT AUTO_INCREMENT PRIMARY KEY,
    own_type VARCHAR(20) NOT NULL COMMENT '보유 타입(소장, 대여)',
    user_id INT NOT NULL COMMENT '유저 아이디',
    profile_id INT NOT NULL COMMENT '프로필 아이디',
    product_id INT NOT NULL COMMENT '작품 아이디',
    episode_id INT NOT NULL COMMENT '회차 아이디',
    ticket_type VARCHAR(20) NOT NULL COMMENT '대여권타입',
    rental_expired_date TIMESTAMP NULL COMMENT '대여권 만료일자',
    use_yn VARCHAR(1) DEFAULT 'Y' COMMENT '사용 여부',
    use_date TIMESTAMP COMMENT '사용한 날짜',
    created_id VARCHAR(30) COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id VARCHAR(30) COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_own_type (own_type),
    INDEX idx_user_id (user_id),
    INDEX idx_profile_id (profile_id),
    INDEX idx_product_id (product_id),
    INDEX idx_episode_id (episode_id)
);

-- tb_user_product_transaction
CREATE TABLE tb_user_product_transaction (
    id INT AUTO_INCREMENT PRIMARY KEY,
    created_id VARCHAR(30) COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id VARCHAR(30) COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일'
);

-- tb_user_suggest
CREATE TABLE tb_user_suggest (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL COMMENT '유저 아이디',
    feature INT COMMENT 'feature',
    target VARCHAR(100) COMMENT '타겟(성별+연령 형식 ex - male20)',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_user_id (user_id),
    INDEX idx_feature (feature),
    INDEX idx_target (target)
);

-- tb_user_profile_apply
CREATE TABLE tb_user_profile_apply (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL COMMENT '유저 아이디',
    apply_type VARCHAR(20) NOT NULL COMMENT '권한 타입',
    company_name VARCHAR(300) COMMENT '회사이름',
    email VARCHAR(100) COMMENT '연락받을 이메일',
    attach_file_id_1st INT COMMENT '첨부파일1 아이디',
    attach_file_id_2nd INT COMMENT '첨부파일2 아이디',
    approval_code VARCHAR(20) NOT NULL COMMENT '승인 코드',
    approval_message VARCHAR(500) COMMENT '승인 메시지',
    approval_id INT COMMENT '승인한 아이디',
    approval_date TIMESTAMP COMMENT '승인 일자',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_user_id (user_id),
    INDEX idx_apply_type (apply_type),
    INDEX idx_approval_code (approval_code),
    INDEX idx_approval_id (approval_id)
);

-- tb_user_profile
CREATE TABLE tb_user_profile (
    profile_id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL COMMENT '유저 아이디',
    nickname VARCHAR(300) NOT NULL UNIQUE COMMENT '닉네임',
    default_yn VARCHAR(1) DEFAULT 'N' COMMENT '프로필 선택 여부',
    role_type VARCHAR(20) NOT NULL COMMENT '권한 - 독자, 작가, CP, 편집자, 엔터사',
    profile_image_id INT COMMENT '프로필 이미지 파일',
    nickname_change_max_count INT DEFAULT 3 COMMENT '닉네임 최대 변경 가능 횟수',
    nickname_change_count INT DEFAULT 3 COMMENT '닉네임 변경 가능 횟수',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_user_id (user_id),
    INDEX idx_role_type (role_type)
);

-- tb_user_badge
CREATE TABLE tb_user_badge (
    badge_id INT AUTO_INCREMENT PRIMARY KEY,
    profile_id INT NOT NULL COMMENT '프로필 아이디',
    user_id INT NOT NULL COMMENT '유저 아이디',
    badge_type VARCHAR(20) NOT NULL COMMENT '뱃지 유형 - 이벤트, 뱃지',
    badge_level INT DEFAULT 1 COMMENT '레벨 수치',
    badge_image_id INT COMMENT '뱃지 이미지 파일',
    display_yn VARCHAR(1) DEFAULT 'N' COMMENT '뱃지 선택 여부',
    use_yn VARCHAR(1) DEFAULT 'Y' COMMENT '사용 여부',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_profile_id (profile_id),
    INDEX idx_user_id (user_id),
    INDEX idx_badge_type (badge_type)
);

-- tb_user_social
CREATE TABLE tb_user_social (
    sns_id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL COMMENT '유저 아이디',
    integrated_user_id INT COMMENT '통합 유저 아이디',
    sns_type VARCHAR(20) NOT NULL COMMENT '회원가입 경로',
    sns_link_id VARCHAR(300) NOT NULL COMMENT 'sns 로그인 연동 고유 발급 아이디',
    default_yn VARCHAR(1) DEFAULT 'N' COMMENT '최초 본인인증 여부',
    temp_issued_key VARCHAR(300) COMMENT '정보 리턴용 임시 키',
    access_token VARCHAR(3000) COMMENT '액세스 토큰',
    access_expire_in INT COMMENT '액세스 토큰 만료 시간',
    refresh_token VARCHAR(3000) COMMENT '리프레시 토큰',
    refresh_expire_in INT COMMENT '리프레시 토큰 만료 시간',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_user_id (user_id),
    INDEX idx_integrated_user_id (integrated_user_id),
    INDEX idx_sns_type (sns_type),
    INDEX idx_sns_link_id (sns_link_id),
    INDEX idx_temp_issued_key (temp_issued_key)
);

-- tb_product_episode
CREATE TABLE tb_product_episode (
    episode_id INT AUTO_INCREMENT PRIMARY KEY,
    product_id INT NOT NULL COMMENT '작품 아이디',
    price_type VARCHAR(20) COMMENT '가격구분 - 무료, 유료',
    episode_no INT DEFAULT 0 COMMENT '회차번호',
    episode_title VARCHAR(300) COMMENT '회차 제목',
    episode_text_count INT DEFAULT 0 COMMENT '회차 내용수',
    episode_content TEXT COMMENT '회차 내용',
    epub_file_id INT COMMENT 'epub 파일',
    author_comment VARCHAR(2000) COMMENT '작가의 말',
    comment_open_yn VARCHAR(1) DEFAULT 'N' COMMENT '댓글 오픈 여부',
    evaluation_open_yn VARCHAR(1) DEFAULT 'N' COMMENT '평가 오픈 여부',
    publish_reserve_date TIMESTAMP COMMENT '예약 설정',
    open_yn VARCHAR(1) DEFAULT 'N' COMMENT '회차 공개 여부',
    count_hit INT DEFAULT 0 COMMENT '회차 조회수',
    count_recommend INT DEFAULT 0 COMMENT '회차 좋아요수',
    count_comment INT DEFAULT 0 COMMENT '회차 댓글수',
    count_evaluation INT DEFAULT 0 COMMENT '회차 사용자 평가수',
    use_yn VARCHAR(1) DEFAULT 'Y' COMMENT '사용 여부',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_product_id (product_id),
    INDEX idx_price_type (price_type)
);

-- tb_product_comment
CREATE TABLE tb_product_comment (
    comment_id INT AUTO_INCREMENT PRIMARY KEY,
    product_id INT NOT NULL COMMENT '작품 아이디',
    episode_id INT NOT NULL COMMENT '회차 아이디',
    user_id INT NOT NULL COMMENT '유저 아이디',
    profile_id INT NOT NULL COMMENT '프로필 아이디',
    author_recommend_yn VARCHAR(1) DEFAULT 'N' COMMENT '작가 추천 여부',
    content TEXT COMMENT '댓글 내용',
    count_recommend INT DEFAULT 0 COMMENT '추천수',
    count_not_recommend INT DEFAULT 0 COMMENT '비추천수',
    use_yn VARCHAR(1) DEFAULT 'Y' COMMENT '사용 여부',
    open_yn VARCHAR(1) DEFAULT 'Y' COMMENT '공개 여부',
    display_top_yn VARCHAR(1) DEFAULT 'N' COMMENT '코멘트 상단 고정 여부',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_product_id (product_id),
    INDEX idx_episode_id (episode_id),
    INDEX idx_user_id (user_id),
    INDEX idx_profile_id (profile_id)
);

-- tb_product_notice
CREATE TABLE tb_product_notice (
    id INT AUTO_INCREMENT PRIMARY KEY,
    product_id INT NOT NULL COMMENT '작품 아이디',
    user_id INT NOT NULL COMMENT '유저 아이디',
    subject VARCHAR(300) COMMENT '공지 제목',
    content TEXT COMMENT '공지 내용',
    publish_reserve_date TIMESTAMP COMMENT '예약 설정',
    open_yn VARCHAR(1) DEFAULT 'N' COMMENT '작품 공지 공개 여부',
    use_yn VARCHAR(1) DEFAULT 'Y' COMMENT '사용 여부',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_product_id (product_id),
    INDEX idx_user_id (user_id)
);

-- tb_product_promotion
CREATE TABLE tb_product_promotion (
    id INT AUTO_INCREMENT PRIMARY KEY,
    product_id INT NOT NULL COMMENT '작품 아이디',
    promotion_id INT NOT NULL COMMENT '프로모션 아이디',
    req_status VARCHAR(20) COMMENT '신청 구분 - 신청, 철회, 반려, 승인',
    req_date TIMESTAMP COMMENT '신청 일자',
    use_yn VARCHAR(1) DEFAULT 'Y' COMMENT '사용 여부',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_product_id (product_id),
    INDEX idx_promotion_id (promotion_id),
    INDEX idx_req_status (req_status)
);

-- tb_product_paid_apply
CREATE TABLE tb_product_paid_apply (
    id INT AUTO_INCREMENT PRIMARY KEY,
    product_id INT NOT NULL COMMENT '작품 아이디',
    status_code VARCHAR(20) NOT NULL COMMENT '상태코드 - 심사중, 반려, 승인',
    req_user_id INT NOT NULL COMMENT '신청한 유저 아이디',
    req_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '신청 일자',
    use_yn VARCHAR(1) DEFAULT 'Y' COMMENT '사용 여부',
    approval_user_id INT NOT NULL COMMENT '승인한 유저 아이디',
    approval_date TIMESTAMP COMMENT '승인 일자',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_product_id (product_id),
    INDEX idx_status_code (status_code),
    INDEX idx_req_user_id (req_user_id),
    INDEX idx_approval_user_id (approval_user_id)
);

-- tb_product_contract_offer
CREATE TABLE tb_product_contract_offer (
    offer_id INT AUTO_INCREMENT PRIMARY KEY,
    product_id INT NOT NULL COMMENT '작품 아이디',
    profit_type VARCHAR(20) NOT NULL COMMENT '이익 분배 구분',
    author_profit DOUBLE DEFAULT 0 COMMENT '작가 수익',
    offer_profit DOUBLE DEFAULT 0 COMMENT '제시자 수익',
    use_yn VARCHAR(1) DEFAULT 'Y' COMMENT '사용 여부',
    author_user_id INT NOT NULL COMMENT '작가 유저 아이디',
    author_accept_yn VARCHAR(1) DEFAULT 'N' COMMENT '최종 제안 수락 여부',
    offer_user_id INT NOT NULL COMMENT '제안한 유저 아이디',
    offer_type VARCHAR(20) NOT NULL COMMENT '제안 형태',
    offer_code VARCHAR(20) NOT NULL COMMENT '제안 금액대 코드',
    offer_price DOUBLE COMMENT '제안 금액',
    offer_date TIMESTAMP COMMENT '제안 일시',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_product_id (product_id),
    INDEX idx_profit_type (profit_type),
    INDEX idx_author_user_id (author_user_id),
    INDEX idx_offer_user_id (offer_user_id),
    INDEX idx_offer_type (offer_type),
    INDEX idx_offer_code (offer_code)
);

-- tb_product_evaluation
CREATE TABLE tb_product_evaluation (
    id INT AUTO_INCREMENT PRIMARY KEY,
    product_id INT NOT NULL COMMENT '작품 아이디',
    episode_id INT NOT NULL COMMENT '회차 아이디',
    user_id INT NOT NULL COMMENT '유저 아이디',
    eval_code VARCHAR(20) NOT NULL COMMENT '평가 코드',
    use_yn VARCHAR(1) DEFAULT 'Y' COMMENT '사용 여부',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_product_id (product_id),
    INDEX idx_episode_id (episode_id),
    INDEX idx_user_id (user_id),
    INDEX idx_eval_code (eval_code)
);

-- tb_product_rank
CREATE TABLE tb_product_rank (
    rank_id INT AUTO_INCREMENT PRIMARY KEY,
    product_id INT NOT NULL COMMENT '작품 아이디',
    current_rank INT COMMENT '현재 랭킹',
    privious_rank INT COMMENT '이전 랭킹',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_product_id (product_id)
);

-- tb_product_trend_index
CREATE TABLE tb_product_trend_index (
    id INT AUTO_INCREMENT PRIMARY KEY,
    product_id INT NOT NULL COMMENT '작품 아이디',
    reading_rate DOUBLE DEFAULT 0 COMMENT '연독률',
    writing_count_per_week DOUBLE DEFAULT 0 COMMENT '주평균 연재횟수',
    primary_reader_group VARCHAR(300) COMMENT '주요 독자층',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_product_id (product_id)
);

-- tb_mapped_product_keyword
CREATE TABLE tb_mapped_product_keyword (
    id INT AUTO_INCREMENT PRIMARY KEY,
    keyword_id INT NOT NULL COMMENT '키워드 아이디',
    product_id INT NOT NULL COMMENT '작품 아이디',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_keyword_id (keyword_id),
    INDEX idx_product_id (product_id)
);

-- tb_product_user_keyword
CREATE TABLE tb_product_user_keyword (
    keyword_id INT AUTO_INCREMENT PRIMARY KEY,
    product_id INT NOT NULL COMMENT '작품 아이디',
    keyword_name VARCHAR(300) COMMENT '키워드명',
    use_yn VARCHAR(1) DEFAULT 'Y' COMMENT '사용 여부',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_product_id (product_id)
);

-- tb_product_count_variance
CREATE TABLE tb_product_count_variance (
    id INT AUTO_INCREMENT PRIMARY KEY,
    product_id INT NOT NULL COMMENT '작품 아이디',
    count_hit_indicator INT DEFAULT 0 COMMENT '조회수 변동치',
    count_bookmark_indicator INT DEFAULT 0 COMMENT '선작수 변동치',
    count_unbookmark_indicator INT DEFAULT 0 COMMENT '선작해제수 변동치',
    count_recommend_indicator INT DEFAULT 0 COMMENT '추천수 변동치',
    count_cp_hit_indicator INT DEFAULT 0 COMMENT 'cp조회수 변동치',
    count_interest_indicator INT DEFAULT 0 COMMENT '누적관심수 변동치',
    count_interest_sustain_indicator INT DEFAULT 0 COMMENT '관심유지수 변동치',
    count_interest_loss_indicator INT DEFAULT 0 COMMENT '관심이탈수 변동치',
    reading_rate_indicator DOUBLE DEFAULT 0 COMMENT '연독률 변동치',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_product_id (product_id)
);

-- tb_product_episode_count_variance
CREATE TABLE tb_product_episode_count_variance (
    id INT AUTO_INCREMENT PRIMARY KEY,
    product_id INT NOT NULL COMMENT '작품 아이디',
    episode_id INT NOT NULL COMMENT '회차 아이디',
    episode_no INT DEFAULT 0 COMMENT '회차수',
    count_hit_indicator INT DEFAULT 0 COMMENT '조회수 변동치',
    count_recommend_indicator INT DEFAULT 0 COMMENT '추천수 변동치',
    count_comment_indicator INT DEFAULT 0 COMMENT '댓글수 변동치',
    count_evaluation_indicator INT DEFAULT 0 COMMENT '평가수 변동치',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_product_id (product_id),
    INDEX idx_episode_id (episode_id)
);

-- tb_user_bookmark
CREATE TABLE tb_user_bookmark (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL COMMENT '유저 아이디',
    product_id INT NOT NULL COMMENT '작품 아이디',
    use_yn VARCHAR(1) DEFAULT 'Y' COMMENT '사용 여부',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_user_id (user_id),
    INDEX idx_product_id (product_id)
);

-- tb_user_product_usage
CREATE TABLE tb_user_product_usage (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL COMMENT '유저 아이디',
    product_id INT NOT NULL COMMENT '작품 아이디',
    episode_id INT NOT NULL COMMENT '회차 아이디',
    recommend_yn VARCHAR(1) DEFAULT 'N' COMMENT '추천 여부',
    use_yn VARCHAR(1) DEFAULT 'Y' COMMENT '사용 여부',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_user_id (user_id),
    INDEX idx_product_id (product_id),
    INDEX idx_episode_id (episode_id)
);

-- tb_user_product_recent
CREATE TABLE tb_user_product_recent (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL COMMENT '유저 아이디',
    product_id INT NOT NULL COMMENT '작품 아이디',
    use_yn VARCHAR(1) DEFAULT 'Y' COMMENT '사용 여부',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_user_id (user_id),
    INDEX idx_product_id (product_id)
);

-- tb_user_product_comment_recommend
CREATE TABLE tb_user_product_comment_recommend (
    id INT AUTO_INCREMENT PRIMARY KEY,
    product_id INT NOT NULL COMMENT '작품 아이디',
    episode_id INT NOT NULL COMMENT '회차 아이디',
    comment_id INT NOT NULL COMMENT '댓글 아이디',
    user_id INT NOT NULL COMMENT '유저 아이디',
    recommend_yn VARCHAR(1) DEFAULT 'N' COMMENT '공감 여부',
    not_recommend_yn VARCHAR(1) DEFAULT 'N' COMMENT '비공감 여부',
    use_yn VARCHAR(1) DEFAULT 'Y' COMMENT '사용 여부',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_product_id (product_id),
    INDEX idx_episode_id (episode_id),
    INDEX idx_comment_id (comment_id),
    INDEX idx_user_id (user_id)
);

-- tb_product_review
CREATE TABLE tb_product_review (
    id INT AUTO_INCREMENT PRIMARY KEY,
    product_id INT NOT NULL COMMENT '작품 아이디',
    episode_id INT COMMENT '회차 아이디',
    user_id INT NOT NULL COMMENT '유저 아이디',
    review_text VARCHAR(3000) NOT NULL COMMENT '리뷰 내용',
    open_yn VARCHAR(1) DEFAULT 'Y' COMMENT '공개 여부',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_product_id (product_id),
    INDEX idx_episode_id (episode_id),
    INDEX idx_user_id (user_id)
);

-- tb_product_episode_like
CREATE TABLE tb_product_episode_like (
    id INT AUTO_INCREMENT PRIMARY KEY,
    product_id INT NOT NULL COMMENT '작품 아이디',
    episode_id INT NOT NULL COMMENT '회차 아이디',
    user_id INT NOT NULL COMMENT '유저 아이디',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_product_id (product_id),
    INDEX idx_episode_id (episode_id),
    INDEX idx_user_id (user_id)
);

-- tb_ticket_item
CREATE TABLE tb_ticket_item (
    ticket_id INT AUTO_INCREMENT PRIMARY KEY,
    ticket_type VARCHAR(20) NOT NULL COMMENT '티켓 타입',
    ticket_name VARCHAR(200) COMMENT '티켓 이름',
    price INT DEFAULT 0 COMMENT '티켓 금액',
    settlement_yn VARCHAR(1) DEFAULT 'N' COMMENT '정산 여부',
    expired_hour INT DEFAULT 0 COMMENT '사용 만료시간',
    use_yn VARCHAR(1) DEFAULT 'Y' COMMENT '사용 여부',
    target_products VARCHAR(300) DEFAULT '[]' COMMENT '대상 작품 id, 빈배열이면 전체 작품에 사용',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_ticket_type (ticket_type)
);

-- tb_product_order
CREATE TABLE tb_product_order (
    order_id INT AUTO_INCREMENT PRIMARY KEY,
    device_type VARCHAR(20) NOT NULL COMMENT '웹, 앱',
    order_no INT DEFAULT 0 COMMENT '주문 번호',
    user_id INT NOT NULL COMMENT '유저 아이디',
    order_date TIMESTAMP NULL COMMENT '주문 일자',
    total_price INT DEFAULT 0 COMMENT '총 가격',
    cancel_yn VARCHAR(1) DEFAULT 'N' COMMENT '취소 여부',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일'
);

-- tb_product_order_item
CREATE TABLE tb_product_order_item (
    id INT AUTO_INCREMENT PRIMARY KEY,
    order_id INT NOT NULL COMMENT '주문 아이디',
    item_id INT NOT NULL COMMENT '아이템 아이디',
    item_name VARCHAR(200) COMMENT '아이템 이름',
    item_price INT DEFAULT 0 COMMENT '아이템 가격',
    cancel_yn VARCHAR(1) DEFAULT 'N' COMMENT '취소 여부',
    quantity INT DEFAULT 0 COMMENT '수량',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_order_id (order_id),
    INDEX idx_item_id (item_id)
);

-- tb_product_order_item_info
CREATE TABLE tb_product_order_item_info (
    item_info_id INT AUTO_INCREMENT PRIMARY KEY,
    product_id INT NOT NULL COMMENT '작품 아이디',
    episode_id INT NOT NULL COMMENT '회차 아이디',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_product_id (product_id),
    INDEX idx_episode_id (episode_id)
);

-- tb_product_payment
CREATE TABLE tb_product_payment (
    payment_id INT AUTO_INCREMENT PRIMARY KEY,
    order_id INT NOT NULL COMMENT '주문 아이디',
    pay_type VARCHAR(20) NOT NULL COMMENT '지불방식',
    price INT DEFAULT 0 COMMENT '수량',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_order_id (order_id),
    INDEX idx_pay_type (pay_type)
);

-- tb_product_refund
CREATE TABLE tb_product_refund (
    id INT AUTO_INCREMENT PRIMARY KEY,
    refund_type VARCHAR(20) NOT NULL COMMENT '환불 타입',
    payment_id INT NOT NULL COMMENT '결제 아이디',
    order_id INT NOT NULL COMMENT '주문 아이디',
    user_id INT NOT NULL COMMENT '유저 아이디',
    order_item_id INT NOT NULL COMMENT '주문 아이템 아이디',
    refund_price INT DEFAULT 0 COMMENT '환불금',
    created_id INT COMMENT 'row를 생성한 id',
    created_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id INT COMMENT 'row를 갱신한 id',
    updated_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    INDEX idx_payment_id (payment_id),
    INDEX idx_order_id (order_id),
    INDEX idx_user_id (user_id),
    INDEX idx_order_item_id (order_item_id)
);
