from sqlalchemy import Integer, String, TIMESTAMP, text
from sqlalchemy.orm import Mapped, mapped_column

from datetime import datetime

from app.const import settings
from app.rdb import Base


class StoreOrder(Base):
    __tablename__ = "tb_store_order"

    # column
    order_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_type: Mapped[str] = mapped_column(
        String(settings.VARCHAR_CODE_SIZE), index=True, nullable=False, comment="웹, 앱"
    )
    order_no: Mapped[str] = mapped_column(
        String(settings.VARCHAR_CODE_SIZE), nullable=False, comment="주문 번호"
    )
    user_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="유저 아이디"
    )
    order_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=True, comment="주문 일자"
    )
    order_status: Mapped[str] = mapped_column(
        String(settings.VARCHAR_CODE_SIZE), nullable=False, comment="주문 상태"
    )
    total_price: Mapped[int] = mapped_column(
        Integer, server_default="0", comment="총 가격"
    )
    cancel_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE), server_default="N", comment="취소 여부"
    )
    invoice_no: Mapped[int] = mapped_column(
        Integer, nullable=True, comment="invoice_no"
    )
    created_id: Mapped[int] = mapped_column(
        Integer, nullable=True, comment="row를 생성한 id"
    )
    created_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_id: Mapped[int] = mapped_column(
        Integer, nullable=True, comment="row를 갱신한 id"
    )
    updated_date: Mapped[datetime] = mapped_column(
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
    )


class ProductOrder(Base):
    __tablename__ = "tb_product_order"

    # column
    order_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_type: Mapped[str] = mapped_column(
        String(settings.VARCHAR_CODE_SIZE), index=True, nullable=False, comment="웹, 앱"
    )
    order_no: Mapped[int] = mapped_column(
        Integer, server_default="0", comment="주문 번호"
    )
    user_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="유저 아이디"
    )
    order_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=True, comment="주문 일자"
    )
    total_price: Mapped[int] = mapped_column(
        Integer, server_default="0", comment="총 가격"
    )
    cancel_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE), server_default="N", comment="취소 여부"
    )
    created_id: Mapped[int] = mapped_column(
        Integer, nullable=True, comment="row를 생성한 id"
    )
    created_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_id: Mapped[int] = mapped_column(
        Integer, nullable=True, comment="row를 갱신한 id"
    )
    updated_date: Mapped[datetime] = mapped_column(
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
    )


class StoreOrderItem(Base):
    __tablename__ = "tb_store_order_item"

    # column
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="주문 아이디"
    )
    item_id: Mapped[str] = mapped_column(
        String(settings.VARCHAR_CODE_SIZE), nullable=False, comment="아이템 아이디"
    )
    item_name: Mapped[str] = mapped_column(
        String(200), nullable=True, comment="아이템 이름"
    )
    item_price: Mapped[int] = mapped_column(
        Integer, server_default="0", comment="아이템 가격"
    )
    cancel_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE), server_default="N", comment="취소 여부"
    )
    quantity: Mapped[int] = mapped_column(Integer, server_default="0", comment="수량")
    created_id: Mapped[int] = mapped_column(
        Integer, nullable=True, comment="row를 생성한 id"
    )
    created_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_id: Mapped[int] = mapped_column(
        Integer, nullable=True, comment="row를 갱신한 id"
    )
    updated_date: Mapped[datetime] = mapped_column(
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
    )


class StorePayment(Base):
    __tablename__ = "tb_store_payment"  # 상품결제

    # column
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="주문 아이디"
    )
    total_price: Mapped[int] = mapped_column(
        Integer, server_default="0", comment="총 수량"
    )
    pg_name: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="PG회사(PORTNAME…)"
    )
    pg_payment_id: Mapped[str] = mapped_column(
        String(50), nullable=True, comment="PG 결제 아이디"
    )
    pg_tx_id: Mapped[str] = mapped_column(
        String(50), nullable=True, comment="PG 거래 아이디"
    )
    created_id: Mapped[int] = mapped_column(
        Integer, nullable=True, comment="row를 생성한 id"
    )
    created_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_id: Mapped[int] = mapped_column(
        Integer, nullable=True, comment="row를 갱신한 id"
    )
    updated_date: Mapped[datetime] = mapped_column(
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
    )


class StorePaymentInfo(Base):
    __tablename__ = "tb_store_payment_info"

    # column
    payment_info_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    payment_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="결제 아이디"
    )
    pay_type: Mapped[str] = mapped_column(
        String(settings.VARCHAR_CODE_SIZE),
        index=True,
        nullable=False,
        comment="결제 타입",
    )
    price: Mapped[int] = mapped_column(Integer, server_default="0", comment="수량")
    created_id: Mapped[int] = mapped_column(
        Integer, nullable=True, comment="row를 생성한 id"
    )
    created_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_id: Mapped[int] = mapped_column(
        Integer, nullable=True, comment="row를 갱신한 id"
    )
    updated_date: Mapped[datetime] = mapped_column(
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
    )


class StoreRefund(Base):
    __tablename__ = "tb_store_refund"

    # column
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    refund_type: Mapped[str] = mapped_column(
        String(settings.VARCHAR_CODE_SIZE),
        index=True,
        nullable=False,
        comment="환불 타입",
    )
    order_item_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="주문 아이템 아이디"
    )
    payment_info_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="결제 정보 아이디"
    )
    order_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="주문 아이디"
    )
    refund_price: Mapped[int] = mapped_column(
        Integer, server_default="0", comment="환불금"
    )
    created_id: Mapped[int] = mapped_column(
        Integer, nullable=True, comment="row를 생성한 id"
    )
    created_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_id: Mapped[int] = mapped_column(
        Integer, nullable=True, comment="row를 갱신한 id"
    )
    updated_date: Mapped[datetime] = mapped_column(
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
    )


class StoreItem(Base):
    __tablename__ = "tb_store_item"  # 상품 테이블(캐시…)

    # column
    item_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    item_type: Mapped[str] = mapped_column(
        String(settings.VARCHAR_CODE_SIZE),
        index=True,
        nullable=False,
        comment="아이템 타입",
    )
    item_name: Mapped[str] = mapped_column(
        String(200), nullable=True, comment="아이템 이름"
    )
    tax_free_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE), server_default="N", comment="면세 여부"
    )
    price: Mapped[int] = mapped_column(Integer, server_default="0", comment="캐시금액")
    use_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE), server_default="Y", comment="사용 여부"
    )
    created_id: Mapped[int] = mapped_column(
        Integer, nullable=True, comment="row를 생성한 id"
    )
    created_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_id: Mapped[int] = mapped_column(
        Integer, nullable=True, comment="row를 갱신한 id"
    )
    updated_date: Mapped[datetime] = mapped_column(
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
    )


class ProductOrderItem(Base):
    __tablename__ = "tb_product_order_item"

    # column
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="주문 아이디"
    )
    item_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="아이템 아이디"
    )
    item_name: Mapped[str] = mapped_column(
        String(200), nullable=True, comment="아이템 이름"
    )
    item_price: Mapped[int] = mapped_column(
        Integer, server_default="0", comment="아이템 가격"
    )
    cancel_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE), server_default="N", comment="취소 여부"
    )
    quantity: Mapped[int] = mapped_column(Integer, server_default="0", comment="수량")
    created_id: Mapped[int] = mapped_column(
        Integer, nullable=True, comment="row를 생성한 id"
    )
    created_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_id: Mapped[int] = mapped_column(
        Integer, nullable=True, comment="row를 갱신한 id"
    )
    updated_date: Mapped[datetime] = mapped_column(
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
    )


class ProductOrderItemInfo(Base):
    __tablename__ = "tb_product_order_item_info"

    # column
    item_info_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    product_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="작품 아이디"
    )
    episode_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="회차 아이디"
    )
    created_id: Mapped[int] = mapped_column(
        Integer, nullable=True, comment="row를 생성한 id"
    )
    created_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_id: Mapped[int] = mapped_column(
        Integer, nullable=True, comment="row를 갱신한 id"
    )
    updated_date: Mapped[datetime] = mapped_column(
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
    )


class ProductPayment(Base):
    __tablename__ = "tb_product_payment"

    # column
    payment_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    order_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="주문 아이디"
    )
    pay_type: Mapped[str] = mapped_column(
        String(settings.VARCHAR_CODE_SIZE),
        index=True,
        nullable=False,
        comment="지불방식",
    )
    price: Mapped[int] = mapped_column(Integer, server_default="0", comment="수량")
    created_id: Mapped[int] = mapped_column(
        Integer, nullable=True, comment="row를 생성한 id"
    )
    created_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_id: Mapped[int] = mapped_column(
        Integer, nullable=True, comment="row를 갱신한 id"
    )
    updated_date: Mapped[datetime] = mapped_column(
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
    )


class ProductRefund(Base):
    __tablename__ = "tb_product_refund"

    # column
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    refund_type: Mapped[str] = mapped_column(
        String(settings.VARCHAR_CODE_SIZE),
        index=True,
        nullable=False,
        comment="환불 타입",
    )
    payment_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="결제 아이디"
    )
    order_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="주문 아이디"
    )
    user_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="유저 아이디"
    )
    order_item_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="주문 아이템 아이디"
    )
    refund_price: Mapped[int] = mapped_column(
        Integer, server_default="0", comment="환불금"
    )
    created_id: Mapped[int] = mapped_column(
        Integer, nullable=True, comment="row를 생성한 id"
    )
    created_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_id: Mapped[int] = mapped_column(
        Integer, nullable=True, comment="row를 갱신한 id"
    )
    updated_date: Mapped[datetime] = mapped_column(
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
    )


class TicketItem(Base):
    __tablename__ = "tb_ticket_item"  # 이용권 테이블(대여권..)

    # column
    ticket_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    ticket_type: Mapped[str] = mapped_column(
        String(settings.VARCHAR_CODE_SIZE),
        index=True,
        nullable=False,
        comment="티켓 타입",
    )
    ticket_name: Mapped[str] = mapped_column(
        String(200), nullable=True, comment="티켓 이름"
    )
    price: Mapped[int] = mapped_column(Integer, server_default="0", comment="티켓 금액")
    settlement_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE), server_default="N", comment="정산 여부"
    )
    expired_hour: Mapped[int] = mapped_column(
        Integer, server_default="0", comment="사용 만료시간"
    )
    use_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE), server_default="Y", comment="사용 여부"
    )
    target_products: Mapped[str] = mapped_column(
        String(settings.VARCHAR_COMM_SIZE),
        server_default="[]",
        comment="대상 작품 id, 빈배열이면 전체 작품에 사용",
    )
    created_id: Mapped[int] = mapped_column(
        Integer, nullable=True, comment="row를 생성한 id"
    )
    created_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_id: Mapped[int] = mapped_column(
        Integer, nullable=True, comment="row를 갱신한 id"
    )
    updated_date: Mapped[datetime] = mapped_column(
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
    )
