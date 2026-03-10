from datetime import date
from typing import Optional

from pydantic import BaseModel, Field


class PredictionBase(BaseModel):
    pass


class PostAuthorEpisodePredictionReqBody(PredictionBase):
    prediction_key: Optional[str] = Field(
        default=None, examples=["5f2c95a9-9ee0-4b9c-98db-c8e4c08b2cc1"]
    )
    product_id: int = Field(examples=[1083], description="작품 ID")
    screen_name: str = Field(
        default="author_episode_manager", description="예측 발생 화면"
    )
    target_week_start_date: date = Field(
        examples=["2026-02-16"], description="목표 주 시작일(월요일)"
    )
    target_weekly_upload_goal: int = Field(examples=[3], description="목표연재주기")
    recommended_weekly_upload_goal: int = Field(
        default=5, examples=[5], description="플랫폼 권장 주간 연재 횟수"
    )
    uploads_this_week: int = Field(examples=[1], description="이번 주 업로드 횟수")
    remaining_target_uploads: int = Field(
        examples=[2], description="목표연재주기 달성까지 남은 화수"
    )
    remaining_recommended_uploads: int = Field(
        examples=[4], description="권장 주간 연재 횟수 달성까지 남은 화수"
    )
    prediction_base_uploads: int = Field(
        examples=[2], description="예측 계산 기준 화수"
    )
    sample_episode_count: int = Field(examples=[12], description="샘플 회차 수")
    sample_window_type: str = Field(
        default="recent_12", examples=["recent_12"], description="샘플 윈도우 타입"
    )
    prediction_basis: str = Field(
        default="target_goal",
        examples=["target_goal"],
        description="예측 기준(target_goal/recommended_goal)",
    )
    expected_views_min: int = Field(examples=[2200], description="예상 조회수 최소")
    expected_views_max: int = Field(examples=[3100], description="예상 조회수 최대")
    expected_rank_gain_min: int = Field(
        examples=[2], description="예상 순위 상승 최소"
    )
    expected_rank_gain_max: int = Field(
        examples=[4], description="예상 순위 상승 최대"
    )
    has_enough_data: str = Field(
        default="Y", examples=["Y"], description="충분한 데이터 여부(Y/N)"
    )
    model_version: str = Field(
        default="v1.0.0", examples=["v1.0.0"], description="예측 모델 버전"
    )
