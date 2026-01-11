from app.services.product.product_service import (
    convert_product_data,
    get_select_fields_and_joins_for_product,
    get_user_id,
)
from app.utils.query import get_file_path_sub_query
from fastapi import status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.exceptions import CustomResponseException
from app.const import ErrorMessages
# from sklearn.metrics.pairwise import cosine_similarity

import logging
import http.client
import json
import re

logger = logging.getLogger("search_service")


"""
통합검색(search) 도메인 개별 서비스 함수 모음
"""


async def products_of_searched(
    kc_user_id: str,
    db: AsyncSession,
    keyword: str,
    adult_yn: str = "N",
    page: int = 1,
    limit: int = 10,
    orderby: str = "update",
):
    """
    통합검색(일반검색 - 작품, 퀘스트, 이벤트)
    """

    try:
        user_id = await get_user_id(kc_user_id, db)
        if orderby == "update":
            sortby = "p.last_episode_date desc"
        elif orderby == "view":
            sortby = "p.count_hit desc"
        else:
            sortby = "p.last_episode_date desc"

        query_parts = get_select_fields_and_joins_for_product(
            user_id=user_id, join_rank=False
        )
        # adult_yn='Y': 전체 조회 (성인 포함), adult_yn='N': 성인 제외 (all만)
        ratings_filter = "" if adult_yn == "Y" else "and p.ratings_code = 'all'"

        query = text(f"""
            select {query_parts["select_fields"]}
            from tb_product p
            {query_parts["joins"]}
            where
                (
                    p.title like :keyword
                    or
                    p.author_name like :keyword
                )
                {ratings_filter}
                and p.open_yn = 'Y'
            order by {sortby}
            limit {limit} offset {(page - 1) * limit}
        """)
        result = await db.execute(
            query,
            {
                "keyword": f"%{keyword}%",
            },
        )
        rows = result.mappings().all()
        product_all = [convert_product_data(row) for row in rows]

        query = text(f"""
            select
                *,
                {get_file_path_sub_query("e.thumbnail_image_id", "thumbnail_image_path")},
                {get_file_path_sub_query("e.detail_image_id", "detail_image_path")}
            from tb_event_v2 e
            where title like :keyword
            AND CURRENT_TIMESTAMP BETWEEN start_date AND end_date
        """)
        result = await db.execute(query, {"keyword": f"%{keyword}%"})
        rows = result.mappings().all()
        events = [dict(row) for row in rows]

        query = text("""
            select
                quest_id as questId,
                title as questTitle,
                '' as questContent
            from tb_quest
            where title like :keyword
        """)
        result = await db.execute(query, {"keyword": f"%{keyword}%"})
        rows = result.mappings().all()
        quests = [dict(row) for row in rows]

        res_fetched = dict()
        res_fetched["products"] = product_all
        res_fetched["events"] = events
        res_fetched["quests"] = quests

        res_body = dict()
        res_body["data"] = res_fetched

        return res_body

    except Exception:
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.SEARCH_SERVICE_ERROR,
        )


async def results_of_autocomplete(
    kc_user_id: str, db: AsyncSession, keyword: str, adult_yn: str = "N"
):
    """
    일반 통합검색 자동완성 키워드
    """

    try:
        user_id = await get_user_id(kc_user_id, db)
        query_parts = get_select_fields_and_joins_for_product(
            user_id=user_id, join_rank=False
        )
        # adult_yn='Y': 전체 조회 (성인 포함), adult_yn='N': 성인 제외 (all만)
        ratings_filter = "" if adult_yn == "Y" else "and p.ratings_code = 'all'"

        query = text(f"""
            select {query_parts["select_fields"]}
            from tb_product p
            {query_parts["joins"]}
            where
                (
                    p.title like :keyword
                    or
                    p.author_name like :keyword
                )
                {ratings_filter}
                and p.open_yn = 'Y'
            limit 10 offset 0
        """)
        result = await db.execute(
            query,
            {
                "keyword": f"%{keyword}%",
            },
        )
        rows = result.mappings().all()
        product_all = [convert_product_data(row) for row in rows]

        query = text("""
            select
                id as eventId,
                title as eventTitle,
                information as eventContent
            from tb_event_v2
            where title like :keyword
            limit 3 offset 0
        """)
        result = await db.execute(query, {"keyword": f"%{keyword}%"})
        rows = result.mappings().all()
        events = [dict(row) for row in rows]

        try:
            titles = list(set([product["title"] for product in product_all]))
            authorNicknames = list(
                set([product["authorNickname"] for product in product_all])
            )[:3]
            # keywords = list(set([product['keywords'] for product in product_all]))[:3]

        except Exception as e:
            logger.error(f"Error: {e}")

        titles_data = [
            {"key": "product", "content": title}
            for title in titles
            if title is not None and title != ""
        ]
        authorNicknames_data = [
            {"key": "author", "content": authorNickname}
            for authorNickname in authorNicknames
            if authorNickname is not None and authorNickname != ""
        ]
        # keywords_data = [{'key': 'keyword', 'content': keyword} for keyword in keywords if keyword is not None]
        events_data = [
            {"key": "event", "content": event}
            for event in events
            if event is not None and event != ""
        ]

        # 모든 배열 통합
        combined_results = titles_data + authorNicknames_data + events_data

        res_body = dict()
        res_body["data"] = combined_results
        return res_body

    except Exception:
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.SEARCH_SERVICE_ERROR,
        )


async def products_of_search_by_story(story: str, adult_yn: str = "N"):
    """
    스토리 검색
    """

    try:
        vector = text_to_vector("여기에 스토리를 입력하세요")
        logger.info(f"vector: {vector}")

        # similarities = [cosine_similarity([query_vector], [doc])[0][0] for doc in vector_embeddings]

        # client = meilisearch.Client(f"{settings.MEILISEARCH_HOST}", f"{settings.MEILISEARCH_API_KEY}")
        # fetched_data = safe_multi_search(client,
        #     [
        #         {'indexUid':'products-all', 'q':f"{story}", 'filter':f'adultYn = "{adult_yn}"', 'page':1, 'hitsPerPage':10, 'matchingStrategy':'all', 'showRankingScore': True, 'rankingScoreThreshold': 0.5, 'attributesToSearchOn': ['title', 'authorNickname']}
        #         , {'indexUid':'events', 'q':f"{story}", 'page':1, 'hitsPerPage':3, 'matchingStrategy':'all', 'showRankingScore': True, 'rankingScoreThreshold': 0.5}
        #     ]
        # )

    except Exception as e:
        logger.error(f"similarities error: {e}")
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.SEARCH_SERVICE_ERROR,
        )

    return vector


class CompletionExecutor:
    """텍스트를 보내면 네이버에서 1024 벡터를 반환함"""

    def __init__(self, host, api_key, api_key_primary_val, request_id):
        self._host = host
        self._api_key = api_key
        self._api_key_primary_val = api_key_primary_val
        self._request_id = request_id

    def _send_request(self, completion_request):
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "X-NCP-CLOVASTUDIO-API-KEY": self._api_key,
            "X-NCP-APIGW-API-KEY": self._api_key_primary_val,
            "X-NCP-CLOVASTUDIO-REQUEST-ID": self._request_id,
        }

        try:
            conn = http.client.HTTPSConnection(self._host)
            conn.request(
                "POST",
                "/serviceapp/v1/api-tools/embedding/v2/174eddaae94644cd89fcc0cdaa9c6abd",
                json.dumps(completion_request),
                headers,
            )

            response = conn.getresponse()
            result = json.loads(response.read().decode("utf-8"))

            logger.info(f"result: {result}")

            conn.close()
        except Exception as e:
            logger.error(f"_send_request error: {e}")

        return result

    def execute(self, completion_request):
        """
        네이버에 보낸 후 성공 or 실패 가능
        성공할 경우 1024벡터 반환
        실패할 경우 'Error' 반환
        """

        logger.info(f"completion_request: {completion_request}")

        res = self._send_request(completion_request)
        logger.info(f"res: {res}")

        if res["status"]["code"] == "20000":
            return res["result"]["embedding"]
        else:
            return "execute error"


# 텍스트 전처리 - 한글만 남김
def text_normalization(text):
    return re.sub(r"[^가-힣\s]", "", text)


# 텍스트 입력, 벡터 변환
def text_to_vector(text):
    completion_executor = CompletionExecutor(
        host="clovastudio.apigw.ntruss.com",
        api_key="NTA0MjU2MWZlZTcxNDJiY2IMA94IE+I/WKyZGLkWjQNG6dYPYKkN85rwDcsuIcb+dHD55qSJE141cqoT52eD7NlJKBsK4nHAYu+ia3bz3NY=",
        api_key_primary_val="tTutEkUIDaoRxjJkqKmpDnHggfn25O7mZacKHfz6",
        request_id="9f29b98f91b44b38b802dfb7ccfbdcd7",
    )

    input_text = text_normalization(text)
    request_data = json.loads(f'{{"text" : "{input_text}"}}', strict=False)
    vector = completion_executor.execute(request_data)
    return vector


async def get_trending_keywords():
    # client = meilisearch.Client(f"{settings.MEILISEARCH_HOST}", f"{settings.MEILISEARCH_API_KEY}")
    # fetched_data = client.search("", indexUid='trending-keywords')
    return [
        "회귀물",
        "로스티플",
        "무협 강호전설",
        "현대 판타지",
        "추리 소설 명작",
        "SF 스릴러",
        "청춘 학원물",
        "세계관 설정",
        "좀비 아포칼립스",
        "로맨틱 코미디",
    ]


async def get_weekly_most_viewed_products(
    kc_user_id: str,
    db: AsyncSession,
    adult_yn: str = "N",
    page: int = 1,
    limit: int = 10,
):
    """
    금주의 최다 조회 작품 목록 조회
    최근 7일간 조회수가 가장 많은 작품을 반환
    """
    try:
        user_id = await get_user_id(kc_user_id, db)

        # 전체 개수 조회
        count_query = text("""
            SELECT COUNT(DISTINCT phl.product_id) as total_count
            FROM tb_product_hit_log phl
            WHERE phl.hit_date >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)
        """)
        count_result = await db.execute(count_query)
        total_count = count_result.scalar() or 0

        # 최근 7일간 조회수 상위 작품 ID 조회
        query = text("""
            SELECT
                phl.product_id,
                SUM(phl.hit_count) as weekly_hits
            FROM tb_product_hit_log phl
            WHERE phl.hit_date >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)
            GROUP BY phl.product_id
            ORDER BY weekly_hits DESC
            LIMIT :limit OFFSET :offset
        """)
        result = await db.execute(query, {"limit": limit, "offset": (page - 1) * limit})
        weekly_hits_rows = result.mappings().all()

        if not weekly_hits_rows:
            return {"data": [], "totalCount": total_count, "pageSize": limit}

        # 작품 ID 목록
        product_ids = [row["product_id"] for row in weekly_hits_rows]

        # 작품 상세 정보 조회
        query_parts = get_select_fields_and_joins_for_product(
            user_id=user_id, join_rank=False
        )
        # adult_yn='Y': 전체 조회 (성인 포함), adult_yn='N': 성인 제외 (all만)
        ratings_filter = "" if adult_yn == "Y" else "AND p.ratings_code = 'all'"

        query = text(f"""
            SELECT {query_parts["select_fields"]}
            FROM tb_product p
            {query_parts["joins"]}
            WHERE p.product_id IN :product_ids
                {ratings_filter}
                AND p.open_yn = 'Y'
        """)
        result = await db.execute(
            query,
            {
                "product_ids": tuple(product_ids),
            },
        )
        rows = result.mappings().all()

        # product_id를 키로 하는 딕셔너리 생성
        products_dict = {row["productId"]: convert_product_data(row) for row in rows}

        # 조회수 순서대로 정렬하여 반환
        products = []
        for hit_row in weekly_hits_rows:
            product_id = hit_row["product_id"]
            if product_id in products_dict:
                product = products_dict[product_id]
                product["weeklyHits"] = hit_row["weekly_hits"]
                products.append(product)

        return {"data": products, "totalCount": total_count, "pageSize": limit}

    except Exception as e:
        logger.error(e)
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.SEARCH_SERVICE_ERROR,
        )


async def search_products_for_review(
    kc_user_id: str,
    db: AsyncSession,
    keyword: str,
    adult_yn: str = "N",
    limit: int | None = None,
):
    """
    리뷰 작성용 작품 검색
    작품명, 작가명으로 검색
    """
    try:
        user_id = await get_user_id(kc_user_id, db)

        query_parts = get_select_fields_and_joins_for_product(
            user_id=user_id, join_rank=False
        )
        # adult_yn='Y': 전체 조회 (성인 포함), adult_yn='N': 성인 제외 (all만)
        ratings_filter = "" if adult_yn == "Y" else "AND p.ratings_code = 'all'"

        query = text(f"""
            SELECT {query_parts["select_fields"]}
            FROM tb_product p
            {query_parts["joins"]}
            WHERE
                (
                    p.title LIKE :keyword
                    OR
                    p.author_name LIKE :keyword
                )
                {ratings_filter}
                AND p.open_yn = 'Y'
            ORDER BY p.last_episode_date DESC
            {f"LIMIT {limit}" if limit is not None else ""}
        """)
        result = await db.execute(
            query,
            {
                "keyword": f"%{keyword}%",
            },
        )
        rows = result.mappings().all()
        products = [convert_product_data(row) for row in rows]

        return {"data": products}

    except Exception:
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.SEARCH_SERVICE_ERROR,
        )
