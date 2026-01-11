from sqlalchemy import Integer, String, TIMESTAMP, text
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
