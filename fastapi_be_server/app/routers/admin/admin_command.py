from fastapi import APIRouter, Depends, File, Path, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any

from app.rdb import get_likenovel_db
from app.utils.auth import analysis_logger, chk_cur_user
import app.schemas.admin as admin_schema
import app.schemas.auth as auth_schema
from app.services.admin import (
    admin_basic_service,
    admin_content_service,
    admin_event_service,
    admin_faq_service,
    admin_notification_service,
    admin_promotion_service,
    admin_quest_service,
    admin_recommend_service,
    admin_system_service,
    admin_user_service,
)
import app.services.auth.auth_service as auth_service
from app.utils.common import check_user

router = APIRouter(prefix="/admins")


@router.post("/login", tags=["CMS - 관리자"], dependencies=[Depends(analysis_logger)])
async def login_admin(
    req_body: auth_schema.SigninReqBody, db: AsyncSession = Depends(get_likenovel_db)
):
    """
    관리자 로그인
    """

    return await auth_service.post_auth_signin(
        req_body=req_body, db=db, call_from="admin"
    )


@router.put(
    "/users/{user_id}", tags=["CMS - 회원"], dependencies=[Depends(analysis_logger)]
)
async def put_user(
    req_body: admin_schema.PutUserReqBody,
    user_id: int = Path(..., description="유저 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    회원 정보 수정
    이 API로는 관리자 권한 수정만 가능합니다
    비밀번호 재설정은 인증 - 기타 - 비밀번호 재설정 API를 사용해주세요
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_basic_service.put_user(user_id, req_body, db=db)


@router.post(
    "/apply-role/{id}/accept",
    tags=["CMS - 자격 신청"],
    dependencies=[Depends(analysis_logger)],
)
async def accept_apply_role(
    id: int = Path(..., description="자격 신청 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    자격 신청 승인
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_user_service.accept_apply_role(id, db)


@router.post(
    "/apply-role/{id}/deny",
    tags=["CMS - 자격 신청"],
    dependencies=[Depends(analysis_logger)],
)
async def deny_apply_role(
    id: int = Path(..., description="자격 신청 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    자격 신청 반려
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_user_service.deny_apply_role(id, db)


@router.put("/badge/{id}", tags=["CMS - 뱃지"], dependencies=[Depends(analysis_logger)])
async def put_badge(
    req_body: admin_schema.PutBadgeReqBody,
    id: int = Path(..., description="뱃지 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    뱃지 수정
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_user_service.put_badge(req_body, id, db)


@router.post(
    "/apply-rank-up/{id}/accept",
    tags=["CMS - 승급 신청"],
    dependencies=[Depends(analysis_logger)],
)
async def accept_apply_rank_up(
    id: int = Path(..., description="승급 신청 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    승급 신청 승인
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_user_service.accept_apply_rank_up(id, db)


@router.post(
    "/apply-rank-up/{id}/deny",
    tags=["CMS - 승급 신청"],
    dependencies=[Depends(analysis_logger)],
)
async def deny_apply_rank_up(
    id: int = Path(..., description="승급 신청 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    승급 신청 반려
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_user_service.deny_apply_rank_up(id, db)


@router.put(
    "/reviews/{id}", tags=["CMS - 리뷰"], dependencies=[Depends(analysis_logger)]
)
async def put_review(
    req_body: admin_schema.PutProductReviewReqBody,
    id: int = Path(..., description="리뷰 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    리뷰 수정
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_content_service.put_review(id, req_body, db=db)


@router.delete(
    "/reviews/{id}", tags=["CMS - 리뷰"], dependencies=[Depends(analysis_logger)]
)
async def delete_review(
    id: int = Path(..., description="리뷰 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    리뷰 삭제
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_content_service.delete_review(id, db=db)


@router.put(
    "/comments/{id}", tags=["CMS - 댓글"], dependencies=[Depends(analysis_logger)]
)
async def put_comment(
    req_body: admin_schema.PutProductCommentReqBody,
    id: int = Path(..., description="댓글 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    댓글 수정
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_content_service.put_comment(id, req_body, db=db)


@router.delete(
    "/comments/{id}", tags=["CMS - 댓글"], dependencies=[Depends(analysis_logger)]
)
async def delete_comment(
    id: int = Path(..., description="댓글 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    댓글 삭제
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_content_service.delete_comment(id, db=db)


@router.put(
    "/notices/{id}", tags=["CMS - 공지"], dependencies=[Depends(analysis_logger)]
)
async def put_notice(
    req_body: admin_schema.PutProductNoticeReqBody,
    id: int = Path(..., description="공지 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    공지 수정
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_content_service.put_notice(id, req_body, db=db)


@router.delete(
    "/notices/{id}", tags=["CMS - 공지"], dependencies=[Depends(analysis_logger)]
)
async def delete_notice(
    id: int = Path(..., description="공지 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    공지 삭제
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_content_service.delete_notice(id, db=db)


@router.post(
    "/keywords", tags=["CMS - 테마 키워드"], dependencies=[Depends(analysis_logger)]
)
async def post_keywords(
    req_body: admin_schema.PostKeywordReqBody,
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    테마 키워드 생성
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_system_service.post_keywords(req_body, db=db)


@router.put(
    "/keywords/{id}",
    tags=["CMS - 테마 키워드"],
    dependencies=[Depends(analysis_logger)],
)
async def put_keywords(
    req_body: admin_schema.PutKeywordReqBody,
    id: int = Path(..., description="키워드 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    테마 키워드 수정
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_system_service.put_keywords(id, req_body, db=db)


@router.delete(
    "/keywords/{id}",
    tags=["CMS - 테마 키워드"],
    dependencies=[Depends(analysis_logger)],
)
async def delete_keywords(
    id: int = Path(..., description="키워드 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    테마 키워드 삭제
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_system_service.delete_keywords(id, db=db)


@router.post(
    "/publisher-promotion",
    tags=["CMS - 출판사 프로모션"],
    dependencies=[Depends(analysis_logger)],
)
async def post_publisher_promotion(
    req_body: admin_schema.PostPublisherPromotionReqBody,
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    출판사 프로모션 구좌 생성
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_system_service.post_publisher_promotion(req_body, db=db)


@router.put(
    "/publisher-promotion/{id}",
    tags=["CMS - 출판사 프로모션"],
    dependencies=[Depends(analysis_logger)],
)
async def put_publisher_promotion(
    req_body: admin_schema.PutPublisherPromotionReqBody,
    id: int = Path(..., description="키워드 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    출판사 프로모션 구좌 수정
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_system_service.put_publisher_promotion(id, req_body, db=db)


@router.delete(
    "/publisher-promotion/{id}",
    tags=["CMS - 출판사 프로모션"],
    dependencies=[Depends(analysis_logger)],
)
async def delete_publisher_promotion(
    id: int = Path(..., description="키워드 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    출판사 프로모션 구좌 삭제
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_system_service.delete_publisher_promotion(id, db=db)


@router.post(
    "/algorithm-recommend/users/upload",
    tags=["CMS - 알고리즘 추천구좌"],
    dependencies=[Depends(analysis_logger)],
)
async def algorithm_recommend_user_csv_upload(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    알고리즘 추천구좌 관리 - 유저 테이블 csv 업로드
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_recommend_service.algorithm_recommend_user_csv_upload(
        file, db=db
    )


@router.post(
    "/algorithm-recommend/set-topic/upload",
    tags=["CMS - 알고리즘 추천구좌"],
    dependencies=[Depends(analysis_logger)],
)
async def algorithm_recommend_set_topic_csv_upload(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    알고리즘 추천구좌 관리 - 주제 설정 테이블 csv 업로드
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_recommend_service.algorithm_recommend_set_topic_csv_upload(
        file, db=db
    )


@router.put(
    "/algorithm-recommend/sections/{id}",
    tags=["CMS - 알고리즘 추천구좌"],
    dependencies=[Depends(analysis_logger)],
)
async def put_algorithm_recommend_section(
    req_body: admin_schema.PutAlgorithmRecommendSectionReqBody,
    id: int = Path(..., description="추천 섹션 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    알고리즘 추천구좌 관리 - 추천 섹션 수정
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_recommend_service.put_algorithm_recommend_section(
        id, req_body, db=db
    )


@router.post(
    "/algorithm-recommend/similar/{type}/upload",
    tags=["CMS - 알고리즘 추천구좌"],
    dependencies=[Depends(analysis_logger)],
)
async def algorithm_recommend_similar_csv_upload(
    type: str = Path(
        ..., description="타입, 내용비슷: content | 장르비슷: genre | 장바구니: cart"
    ),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    알고리즘 추천구좌 관리 - 추천1 내용비슷 csv 업로드
    알고리즘 추천구좌 관리 - 추천2 장르비슷 csv 업로드
    알고리즘 추천구좌 관리 - 추천3 장바구니 csv 업로드
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_recommend_service.algorithm_recommend_similar_csv_upload(
        type, file, db=db
    )


@router.post(
    "/direct-recommend",
    tags=["CMS - 직접 추천구좌"],
    dependencies=[Depends(analysis_logger)],
)
async def post_direct_recommend(
    req_body: admin_schema.PostDirectRecommendReqBody,
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    직접 추천구좌 등록
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_recommend_service.post_direct_recommend(req_body, db=db)


@router.put(
    "/direct-recommend/{id}",
    tags=["CMS - 직접 추천구좌"],
    dependencies=[Depends(analysis_logger)],
)
async def put_direct_recommend(
    req_body: admin_schema.PutDirectRecommendReqBody,
    id: int = Path(..., description="직접 추천구좌 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    직접 추천구좌 수정
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_recommend_service.put_direct_recommend(id, req_body, db=db)


@router.delete(
    "/direct-recommend/{id}",
    tags=["CMS - 직접 추천구좌"],
    dependencies=[Depends(analysis_logger)],
)
async def delete_direct_recommend(
    id: int = Path(..., description="직접 추천구좌 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    직접 추천구좌 삭제
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_recommend_service.delete_direct_recommend(id, db=db)


@router.post(
    "/applied-promotion",
    tags=["CMS - 신청 프로모션"],
    dependencies=[Depends(analysis_logger)],
)
async def post_applied_promotion(
    req_body: admin_schema.PostAppliedPromotionReqBody,
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    신청 프로모션 등록
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_promotion_service.post_applied_promotion(req_body, db=db)


@router.post(
    "/applied-promotion/{id}/accept",
    tags=["CMS - 신청 프로모션"],
    dependencies=[Depends(analysis_logger)],
)
async def accept_applied_promotion_accept(
    req_body: admin_schema.PostAcceptAppliedPromotionReqBody,
    id: int = Path(..., description="신청 프로모션 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    신청 프로모션 승인
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_promotion_service.accept_applied_promotion_accept(
        id, req_body, db=db
    )


@router.post(
    "/applied-promotion/{id}/deny",
    tags=["CMS - 신청 프로모션"],
    dependencies=[Depends(analysis_logger)],
)
async def deny_applied_promotion_accept(
    id: int = Path(..., description="신청 프로모션 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    신청 프로모션 반려
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_promotion_service.deny_applied_promotion_accept(id, db=db)


@router.post(
    "/applied-promotion/{id}/end",
    tags=["CMS - 신청 프로모션"],
    dependencies=[Depends(analysis_logger)],
)
async def end_applied_promotion_accept(
    id: int = Path(..., description="신청 프로모션 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    신청 프로모션 종료
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_promotion_service.end_applied_promotion_accept(id, db=db)


@router.post(
    "/push/templates/{id}/on",
    tags=["CMS - 푸시 메시지"],
    dependencies=[Depends(analysis_logger)],
)
async def on_push_message_templates(
    id: int = Path(..., description="푸시 메시지 템플릿 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    푸시 메시지 템플릿 사용
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_notification_service.on_push_message_templates(id, db=db)


@router.post(
    "/push/templates/{id}/off",
    tags=["CMS - 푸시 메시지"],
    dependencies=[Depends(analysis_logger)],
)
async def off_push_message_templates(
    id: int = Path(..., description="푸시 메시지 템플릿 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    푸시 메시지 템플릿 사용 중지
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_notification_service.off_push_message_templates(id, db=db)


@router.put(
    "/push/templates/{id}",
    tags=["CMS - 푸시 메시지"],
    dependencies=[Depends(analysis_logger)],
)
async def put_push_message_templates(
    req_body: admin_schema.PutPushMessageTemplatesReqBody,
    id: int = Path(..., description="푸시 메시지 템플릿 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    푸시 메시지 관리 - 템플릿 수정
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_notification_service.put_push_message_templates(
        id, req_body, db=db
    )


@router.put(
    "/push/send", tags=["CMS - 푸시 메시지"], dependencies=[Depends(analysis_logger)]
)
async def send_push_message_directly(
    req_body: admin_schema.SendPushMessageDirectlyReqBody,
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    푸시 메시지 관리 - 직접 발송
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_notification_service.send_push_message_directly(req_body, db=db)


@router.post(
    "/quests/{id}/on", tags=["CMS - 퀘스트"], dependencies=[Depends(analysis_logger)]
)
async def on_quest(
    id: int = Path(..., description="퀘스트 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    퀘스트 사용
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_quest_service.on_quest(id, db=db)


@router.post(
    "/quests/{id}/off", tags=["CMS - 퀘스트"], dependencies=[Depends(analysis_logger)]
)
async def off_quest(
    id: int = Path(..., description="퀘스트 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    퀘스트 사용 중지
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_quest_service.off_quest(id, db=db)


@router.put(
    "/quests/{id}", tags=["CMS - 퀘스트"], dependencies=[Depends(analysis_logger)]
)
async def put_quest(
    req_body: admin_schema.PutQuestReqBody,
    id: int = Path(..., description="퀘스트 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    퀘스트 관리 - 수정
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_quest_service.put_quest(req_body, id, db=db)


@router.post("/events", tags=["CMS - 이벤트"], dependencies=[Depends(analysis_logger)])
async def post_event(
    req_body: admin_schema.PostEventReqBody,
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    이벤트 등록
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_event_service.post_event(req_body, db=db)


@router.put(
    "/events/{id}", tags=["CMS - 이벤트"], dependencies=[Depends(analysis_logger)]
)
async def put_event(
    req_body: admin_schema.PutEventReqBody,
    id: int = Path(..., description="이벤트 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    이벤트 수정
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_event_service.put_event(req_body, id, db=db)


@router.post(
    "/events/{id}/show", tags=["CMS - 이벤트"], dependencies=[Depends(analysis_logger)]
)
async def show_event(
    id: int = Path(..., description="이벤트 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    이벤트 노출 ON
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_event_service.show_event(id, db=db)


@router.post(
    "/events/{id}/hide", tags=["CMS - 이벤트"], dependencies=[Depends(analysis_logger)]
)
async def hide_event(
    id: int = Path(..., description="이벤트 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    이벤트 노출 OFF
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_event_service.hide_event(id, db=db)


@router.delete(
    "/events/{id}", tags=["CMS - 이벤트"], dependencies=[Depends(analysis_logger)]
)
async def delete_event(
    id: int = Path(..., description="이벤트 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    이벤트 삭제
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_event_service.delete_event(id, db=db)


@router.post("/banners", tags=["CMS - 배너"], dependencies=[Depends(analysis_logger)])
async def post_banner(
    req_body: admin_schema.PostBannerReqBody,
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    배너 및 팝업 관리 - 배너 등록
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_event_service.post_banner(req_body, db=db)


@router.put(
    "/banners/{id}", tags=["CMS - 배너"], dependencies=[Depends(analysis_logger)]
)
async def put_banner(
    req_body: admin_schema.PutBannerReqBody,
    id: int = Path(..., description="배너 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    배너 및 팝업 관리 - 배너 수정
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_event_service.put_banner(req_body, id, db=db)


@router.delete(
    "/banners/{id}", tags=["CMS - 배너"], dependencies=[Depends(analysis_logger)]
)
async def delete_banner(
    id: int = Path(..., description="배너 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    배너 및 팝업 관리 - 배너 삭제
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_event_service.delete_banner(id, db=db)


@router.put("/popup", tags=["CMS - 팝업"], dependencies=[Depends(analysis_logger)])
async def put_popup(
    req_body: admin_schema.PutPopupReqBody,
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    배너 및 팝업 관리 - 팝업 수정
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_event_service.put_popup(req_body, db=db)


@router.post("/faq", tags=["CMS - FAQ"], dependencies=[Depends(analysis_logger)])
async def post_faq(
    req_body: admin_schema.PostFAQReqBody,
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    공지 / FAQ - FAQ 등록
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_faq_service.post_faq(req_body, db=db)


@router.put("/faq/{id}", tags=["CMS - FAQ"], dependencies=[Depends(analysis_logger)])
async def put_faq(
    req_body: admin_schema.PutFAQReqBody,
    id: int = Path(..., description="FAQ 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    공지 / FAQ - FAQ 수정
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_faq_service.put_faq(req_body, id, db=db)


@router.delete("/faq/{id}", tags=["CMS - FAQ"], dependencies=[Depends(analysis_logger)])
async def delete_faq(
    id: int = Path(..., description="FAQ 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    공지 / FAQ - FAQ 삭제
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_faq_service.delete_faq(id, db=db)


@router.post(
    "/common-rate", tags=["CMS - 비율 조정"], dependencies=[Depends(analysis_logger)]
)
async def save_common_rate_data(
    req_body: admin_schema.PostCommonRateReqBody,
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    비율 조정 저장
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_basic_service.save_common_rate_data(req_body, db=db)


@router.put(
    "/users/{user_id}/password/reset",
    tags=["CMS - 회원"],
    responses={
        200: {
            "description": "Successful Response",
            "content": {
                "application/json": {
                    "examples": {"success_1": {"summary": "OK", "value": None}}
                }
            },
        },
        422: {
            "description": "사용자 validation 규칙 체크",
            "content": {
                "application/json": {
                    "examples": {
                        "retryPossible_1": {
                            "summary": "email 값 validation 에러(유효하지 않은 email 값)",
                            "value": {"code": "E4220"},
                        },
                        "retryPossible_2": {
                            "summary": "password 값 validation 에러(유효하지 않은 password 값)",
                            "value": {"code": "E4221"},
                        },
                    }
                }
            },
        },
        500: {
            "description": "Internal Server Error",
            "content": {
                "application/json": {
                    "examples": {
                        "internal_server_error": {
                            "summary": "INTERNAL_SERVER_ERROR",
                            "value": {},
                        }
                    }
                }
            },
        },
    },
    dependencies=[Depends(analysis_logger)],
)
async def put_auth_identity_password_reset(
    req_body: auth_schema.IdentityPasswordResetReqBody,
    user_id: int = Path(..., description="유저 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    **TODO: 본인인증 모듈 구현 후 수정 및 최종 테스트 필(초안 개발 완료)**\n
    비밀번호 재설정
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_user_service.put_auth_identity_password_reset(
        req_body=req_body, user_id=user_id, db=db
    )


@router.put(
    "/users/{user_id}/signoff",
    tags=["CMS - 회원"],
    responses={
        200: {
            "description": "Successful Response",
            "content": {
                "application/json": {
                    "examples": {"success_1": {"summary": "OK", "value": None}}
                }
            },
        },
        401: {
            "description": "토큰 재발급 요청 필요",
            "content": {
                "application/json": {
                    "examples": {
                        "retryPossible_1": {
                            "summary": "만료된 access 토큰 상태",
                            "value": {"code": "E4010"},
                        }
                    }
                }
            },
        },
        422: {
            "description": "Validation Error",
            "content": {
                "application/json": {
                    "examples": {
                        "retryPossible_1": {
                            "summary": "UNPROCESSABLE_ENTITY",
                            "value": None,
                        }
                    }
                }
            },
        },
        500: {
            "description": "Internal Server Error",
            "content": {
                "application/json": {
                    "examples": {
                        "internal_server_error": {
                            "summary": "INTERNAL_SERVER_ERROR",
                            "value": {},
                        }
                    }
                }
            },
        },
    },
    dependencies=[Depends(analysis_logger)],
)
async def put_auth_signoff(
    user_id: int = Path(..., description="유저 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    **TODO: 통합아이디 연동 모듈 구현 후 수정 및 최종 테스트 필(현재 개별아이디 개발 완료. 나머지 초안 개발 완료)**\n
    회원탈퇴
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_user_service.put_auth_signoff(user_id=user_id, db=db)


@router.post(
    "/general-notices",
    tags=["CMS - 공지사항(사이트 공지)"],
    dependencies=[Depends(analysis_logger)],
)
async def post_general_notice(
    req_body: admin_schema.PostNoticeReqBody,
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    공지사항 등록
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_system_service.post_general_notice(req_body, db=db)


@router.put(
    "/general-notices/{id}",
    tags=["CMS - 공지사항(사이트 공지)"],
    dependencies=[Depends(analysis_logger)],
)
async def put_general_notice(
    req_body: admin_schema.PutNoticeReqBody,
    id: int = Path(..., description="공지사항 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    공지사항 수정
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_system_service.put_general_notice(id, req_body, db=db)


@router.delete(
    "/general-notices/{id}",
    tags=["CMS - 공지사항(사이트 공지)"],
    dependencies=[Depends(analysis_logger)],
)
async def delete_general_notice(
    id: int = Path(..., description="공지사항 번호"),
    db: AsyncSession = Depends(get_likenovel_db),
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    """
    공지사항 삭제
    """
    try:
        await check_user(kc_user_id=user.get("sub"), db=db, role="admin")
    except Exception as e:
        raise e

    return await admin_system_service.delete_general_notice(id, db=db)
