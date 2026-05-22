from sqlalchemy import DateTime, Index, Integer, String, TIMESTAMP, text
from sqlalchemy.dialects.mysql import BIGINT
from sqlalchemy.orm import Mapped, mapped_column

from datetime import datetime

from app.rdb import Base


class SiteStatisticsLog(Base):
    __tablename__ = "tb_site_statistics_log"  # 사이트 통계 집계용 로그 테이블

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, comment="집계 일자"
    )
    type: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="타입(visit, page_view, login, active)"
    )
    user_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="유저 아이디"
    )
    created_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class SitePageViewEvent(Base):
    __tablename__ = "tb_site_page_view_event"
    __table_args__ = (
        Index("uq_site_page_view_event_event_id", "event_id", unique=True),
        Index("idx_site_page_view_event_source_occurred", "source", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True), primary_key=True, autoincrement=True
    )
    event_id: Mapped[str] = mapped_column(
        String(36), nullable=False, comment="클라이언트 생성 이벤트 UUID"
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, comment="브라우저 route 노출 시각"
    )
    user_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="로그인 유저 ID, 게스트는 NULL"
    )
    visitor_id: Mapped[str] = mapped_column(
        String(80), nullable=False, comment="브라우저 단위 익명 방문자 ID"
    )
    session_id: Mapped[str] = mapped_column(
        String(80), nullable=False, comment="브라우저 세션 ID"
    )
    route_group: Mapped[str] = mapped_column(
        String(80), nullable=False, comment="route 대분류"
    )
    route_name: Mapped[str] = mapped_column(
        String(120), nullable=False, comment="route 세부명"
    )
    path_template: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="정규화된 route template"
    )
    path: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="query/hash 제거 pathname"
    )
    query_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="허용된 query identity hash"
    )
    referrer_path: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="이전 pathname"
    )
    source: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        server_default="service-web",
        comment="이벤트 소스",
    )
    taxonomy_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1", comment="route taxonomy version"
    )
    created_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class SiteStatistics(Base):
    __tablename__ = "tb_site_statistics"  # 사이트 통계 집계 테이블

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, comment="집계 일자"
    )
    visitors: Mapped[int] = mapped_column(Integer, default=0, comment="방문자수")
    page_view: Mapped[int] = mapped_column(Integer, default=0, comment="페이지뷰 수")
    login_count: Mapped[int] = mapped_column(Integer, default=0, comment="로그인 수")
    dau: Mapped[int] = mapped_column(
        Integer, default=0, comment="DAU(일간 순수 유저 수)"
    )
    mau: Mapped[int] = mapped_column(
        Integer, default=0, comment="MAU(월간 순수 유저 수)"
    )
    created_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class PaymentStatisticsLog(Base):
    __tablename__ = "tb_payment_statistics_log"  # 결제 통계 집계용 로그 테이블

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, comment="집계 일자"
    )
    type: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="타입(pay, use_coin, donation, ad)"
    )
    user_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="유저 아이디"
    )
    amount: Mapped[int] = mapped_column(Integer, default=0, comment="금액 또는 코인 수")
    created_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class PaymentStatistics(Base):
    __tablename__ = "tb_payment_statistics"  # 결제 통계 집계 테이블

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, comment="집계 일자"
    )
    pay_count: Mapped[int] = mapped_column(
        Integer, default=0, comment="그 날의 총 결제 횟수"
    )
    pay_coin: Mapped[int] = mapped_column(
        Integer, default=0, comment="그 날의 총 결제 코인 수"
    )
    pay_amount: Mapped[int] = mapped_column(
        Integer, default=0, comment="그 날의 총 결제 금액"
    )
    use_coin_count: Mapped[int] = mapped_column(
        Integer, default=0, comment="그 날의 총 코인 사용 횟수"
    )
    use_coin: Mapped[int] = mapped_column(
        Integer, default=0, comment="그 날의 총 코인 사용량"
    )
    donation_count: Mapped[int] = mapped_column(
        Integer, default=0, comment="그 날의 총 후원 횟수"
    )
    donation_coin: Mapped[int] = mapped_column(
        Integer, default=0, comment="그 날의 총 후원 코인 수"
    )
    ad_revenue: Mapped[int] = mapped_column(
        Integer, default=0, comment="그 날의 총 광고 수익"
    )
    created_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class PaymentStatisticsByUser(Base):
    __tablename__ = "tb_payment_statistics_by_user"  # 회원별 결제 통계 집계 테이블

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, comment="집계 일자"
    )
    user_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="유저 아이디"
    )
    pay_count: Mapped[int] = mapped_column(
        Integer, default=0, comment="그 날의 총 결제 횟수"
    )
    pay_coin: Mapped[int] = mapped_column(
        Integer, default=0, comment="그 날의 총 결제 코인 수"
    )
    pay_amount: Mapped[int] = mapped_column(
        Integer, default=0, comment="그 날의 총 결제 금액"
    )
    use_coin_count: Mapped[int] = mapped_column(
        Integer, default=0, comment="그 날의 총 코인 사용 횟수"
    )
    use_coin: Mapped[int] = mapped_column(
        Integer, default=0, comment="그 날의 총 코인 사용량"
    )
    donation_count: Mapped[int] = mapped_column(
        Integer, default=0, comment="그 날의 총 후원 횟수"
    )
    donation_coin: Mapped[int] = mapped_column(
        Integer, default=0, comment="그 날의 총 후원 코인 수"
    )
    ad_revenue: Mapped[int] = mapped_column(
        Integer, default=0, comment="그 날의 총 광고 수익"
    )
    created_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class ProductHitSnapshotHourly(Base):
    __tablename__ = "tb_product_hit_snapshot_hourly"
    __table_args__ = (
        Index(
            "idx_product_hit_snapshot_hourly_product_basis",
            "product_id",
            "basis_at",
        ),
    )

    basis_at: Mapped[datetime] = mapped_column(
        DateTime, primary_key=True, nullable=False, comment="Top50 기준시각(HH:30)"
    )
    product_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, nullable=False, comment="작품 ID"
    )
    count_hit: Mapped[int] = mapped_column(
        BIGINT(unsigned=True),
        nullable=False,
        server_default="0",
        comment="기준시점 작품 누적 조회수",
    )
    created_id: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", comment="row를 생성한 id"
    )
    created_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_id: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", comment="row를 갱신한 id"
    )
    updated_date: Mapped[datetime] = mapped_column(
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
    )


class ProductEpisodeHitSnapshotHourly(Base):
    __tablename__ = "tb_product_episode_hit_snapshot_hourly"
    __table_args__ = (
        Index(
            "idx_product_episode_hit_snapshot_hourly_product_basis",
            "product_id",
            "basis_at",
        ),
        Index(
            "idx_product_episode_hit_snapshot_hourly_basis_product_episode_no",
            "basis_at",
            "product_id",
            "episode_no",
        ),
    )

    basis_at: Mapped[datetime] = mapped_column(
        DateTime, primary_key=True, nullable=False, comment="Top50 기준시각(HH:30)"
    )
    product_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, nullable=False, comment="작품 ID"
    )
    episode_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, nullable=False, comment="회차 ID"
    )
    episode_no: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="회차 번호"
    )
    count_hit: Mapped[int] = mapped_column(
        BIGINT(unsigned=True),
        nullable=False,
        server_default="0",
        comment="기준시점 회차 누적 조회수",
    )
    created_id: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", comment="row를 생성한 id"
    )
    created_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_id: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", comment="row를 갱신한 id"
    )
    updated_date: Mapped[datetime] = mapped_column(
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
    )
