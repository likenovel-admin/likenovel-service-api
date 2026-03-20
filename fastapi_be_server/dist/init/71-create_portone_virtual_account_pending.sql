USE likenovel;

CREATE TABLE IF NOT EXISTS tb_portone_virtual_account_pending (
    pending_id                        INT NOT NULL AUTO_INCREMENT COMMENT 'PK',
    payment_id                        VARCHAR(50) NOT NULL COMMENT 'PortOne payment_id',
    user_id                           INT NOT NULL COMMENT '발급 확인을 통과한 유저 ID',
    item_name                         VARCHAR(200) NOT NULL COMMENT '결제 아이템명',
    item_price                        INT NOT NULL DEFAULT 0 COMMENT '결제 금액',
    pg_tx_id                          VARCHAR(50) NULL COMMENT 'PortOne tx_id',
    issued_at                         VARCHAR(40) NULL COMMENT '가상계좌 발급 시각(PortOne 원본)',
    expired_at                        VARCHAR(40) NULL COMMENT '가상계좌 입금 만료 시각(PortOne 원본)',
    paid_synced_at                    TIMESTAMP NULL COMMENT '입금 완료 후 주문 반영 시각',
    created_id                        INT NULL COMMENT 'row를 생성한 id',
    created_date                      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '생성일',
    updated_id                        INT NULL COMMENT 'row를 갱신한 id',
    updated_date                      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일',
    PRIMARY KEY (pending_id),
    UNIQUE KEY uk_portone_virtual_account_pending_payment_id (payment_id),
    KEY idx_portone_virtual_account_pending_user_id (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='PortOne V2 가상계좌 발급 확인 후 입금 완료 대기 바인딩';
