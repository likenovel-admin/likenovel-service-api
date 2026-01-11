import json
import logging
from fastapi import status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime

from app.exceptions import CustomResponseException
import app.schemas.admin as admin_schema
from app.const import ErrorMessages
from app.utils.response import check_exists_or_404


logger = logging.getLogger("admin_app")  # 커스텀 로거 생성

"""
관리자 퀘스트 관리 서비스 함수 모음
"""


async def on_quest(id: int, db: AsyncSession):
    """
    퀘스트 관리

    Args:
        id: 활성화할 퀘스트 ID
        db: 데이터베이스 세션

    Returns:
        퀘스트 활성화 결과
    """

    query = text(f"""
        SELECT
            *
        FROM tb_quest
        WHERE quest_id = {id}
        ORDER BY created_date DESC LIMIT 1
    """)
    result = await db.execute(query, {})
    rows = result.mappings().all()

    check_exists_or_404(rows, ErrorMessages.NOT_FOUND_QUEST)

    quest = dict(rows[0])

    if quest["use_yn"] == "Y":
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message=ErrorMessages.ALREADY_USING_STATE,
        )

    query = text("""
                        update tb_quest set
                        use_yn = 'Y', updated_id = :updated_id, updated_date = :updated_date
                        where quest_id = :id
                    """)

    await db.execute(
        query,
        {
            "id": id,
            "updated_id": -1,
            "updated_date": datetime.now(),
        },
    )

    quest["use_yn"] = "Y"
    return {"result": quest}


async def off_quest(id: int, db: AsyncSession):
    """
    퀘스트 관리

    Args:
        id: 비활성화할 퀘스트 ID
        db: 데이터베이스 세션

    Returns:
        퀘스트 비활성화 결과
    """

    query = text(f"""
        SELECT
            *
        FROM tb_quest
        WHERE quest_id = {id}
        ORDER BY created_date DESC LIMIT 1
    """)
    result = await db.execute(query, {})
    rows = result.mappings().all()

    check_exists_or_404(rows, ErrorMessages.NOT_FOUND_QUEST)

    quest = dict(rows[0])

    if quest["use_yn"] == "N":
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message=ErrorMessages.ALREADY_STOPPED_STATE,
        )

    query = text("""
                        update tb_quest set
                        use_yn = 'N', updated_id = :updated_id, updated_date = :updated_date
                        where quest_id = :id
                    """)

    await db.execute(
        query,
        {
            "id": id,
            "updated_id": -1,
            "updated_date": datetime.now(),
        },
    )

    quest["use_yn"] = "N"
    return {"result": quest}


async def quest_all(db: AsyncSession):
    """
    퀘스트 목록

    Args:
        db: 데이터베이스 세션

    Returns:
        퀘스트 목록
    """
    try:
        query = text("""
                    select * from tb_quest order by quest_id
                    """)
        result = await db.execute(query, {})
        rows = result.mappings().all()

        res_body = dict()
        res_body["data"] = []
        for row in rows:
            quest = dict(row)

            quest["renewal"] = (
                json.loads(quest["renewal"]) if quest["renewal"] is not None else {}
            )
            if "MON" not in quest["renewal"]:
                quest["renewal"]["MON"] = "N"
            if "TUE" not in quest["renewal"]:
                quest["renewal"]["TUE"] = "N"
            if "WED" not in quest["renewal"]:
                quest["renewal"]["WED"] = "N"
            if "THU" not in quest["renewal"]:
                quest["renewal"]["THU"] = "N"
            if "FRI" not in quest["renewal"]:
                quest["renewal"]["FRI"] = "N"
            if "SAT" not in quest["renewal"]:
                quest["renewal"]["SAT"] = "N"
            if "SUN" not in quest["renewal"]:
                quest["renewal"]["SUN"] = "N"

            quest["step1"] = (
                json.loads(quest["step1"]) if quest["step1"] is not None else {}
            )
            if "useYn" not in quest["step1"]:
                quest["step1"]["useYn"] = "N"
            if "count_process" not in quest["step1"]:
                quest["step1"]["count_process"] = 0
            if "count_ticket" not in quest["step1"]:
                quest["step1"]["count_ticket"] = 0

            quest["step2"] = (
                json.loads(quest["step2"]) if quest["step2"] is not None else {}
            )
            if "useYn" not in quest["step2"]:
                quest["step2"]["useYn"] = "N"
            if "count_process" not in quest["step2"]:
                quest["step2"]["count_process"] = 0
            if "count_ticket" not in quest["step2"]:
                quest["step2"]["count_ticket"] = 0

            quest["step3"] = (
                json.loads(quest["step3"]) if quest["step3"] is not None else {}
            )
            if "useYn" not in quest["step3"]:
                quest["step3"]["useYn"] = "N"
            if "count_process" not in quest["step3"]:
                quest["step3"]["count_process"] = 0
            if "count_ticket" not in quest["step3"]:
                quest["step3"]["count_ticket"] = 0

            res_body["data"].append(quest)

        return res_body

    except Exception as e:
        logger.error(e)
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.INTERNAL_SERVER_ERROR,
        )


async def quest_detail_by_id(id: int, db: AsyncSession):
    """
    퀘스트 상세 조회

    Args:
        id: 조회할 퀘스트 ID
        db: 데이터베이스 세션

    Returns:
        퀘스트 상세 정보
    """

    query = text(f"""
        SELECT
            *
        FROM tb_quest
        WHERE quest_id = {id}
        ORDER BY created_date DESC LIMIT 1
    """)
    result = await db.execute(query, {})
    rows = result.mappings().all()

    check_exists_or_404(rows, ErrorMessages.NOT_FOUND_QUEST)

    quest = dict(rows[0])

    quest["renewal"] = (
        json.loads(quest["renewal"]) if quest["renewal"] is not None else {}
    )
    if "MON" not in quest["renewal"]:
        quest["renewal"]["MON"] = "N"
    if "TUE" not in quest["renewal"]:
        quest["renewal"]["TUE"] = "N"
    if "WED" not in quest["renewal"]:
        quest["renewal"]["WED"] = "N"
    if "THU" not in quest["renewal"]:
        quest["renewal"]["THU"] = "N"
    if "FRI" not in quest["renewal"]:
        quest["renewal"]["FRI"] = "N"
    if "SAT" not in quest["renewal"]:
        quest["renewal"]["SAT"] = "N"
    if "SUN" not in quest["renewal"]:
        quest["renewal"]["SUN"] = "N"

    quest["step1"] = json.loads(quest["step1"]) if quest["step1"] is not None else {}
    if "useYn" not in quest["step1"]:
        quest["step1"]["useYn"] = "N"
    if "count_process" not in quest["step1"]:
        quest["step1"]["count_process"] = 0
    if "count_ticket" not in quest["step1"]:
        quest["step1"]["count_ticket"] = 0

    quest["step2"] = json.loads(quest["step2"]) if quest["step2"] is not None else {}
    if "useYn" not in quest["step2"]:
        quest["step2"]["useYn"] = "N"
    if "count_process" not in quest["step2"]:
        quest["step2"]["count_process"] = 0
    if "count_ticket" not in quest["step2"]:
        quest["step2"]["count_ticket"] = 0

    quest["step3"] = json.loads(quest["step3"]) if quest["step3"] is not None else {}
    if "useYn" not in quest["step3"]:
        quest["step3"]["useYn"] = "N"
    if "count_process" not in quest["step3"]:
        quest["step3"]["count_process"] = 0
    if "count_ticket" not in quest["step3"]:
        quest["step3"]["count_ticket"] = 0

    return quest


async def put_quest(req_body: admin_schema.PutQuestReqBody, id: int, db: AsyncSession):
    """
    퀘스트 수정

    Args:
        req_body: 수정할 퀘스트 정보
        id: 수정할 퀘스트 ID
        db: 데이터베이스 세션

    Returns:
        퀘스트 수정 결과
    """

    query = text("""
                    SELECT * FROM tb_quest WHERE quest_id = :id
                    """)
    result = await db.execute(query, {"id": id})
    rows = result.mappings().all()

    check_exists_or_404(rows, ErrorMessages.NOT_FOUND_QUEST)

    quest = dict(rows[0])

    quest["renewal"] = (
        json.loads(quest["renewal"]) if quest["renewal"] is not None else {}
    )
    if "MON" not in quest["renewal"]:
        quest["renewal"]["MON"] = "N"
    if "TUE" not in quest["renewal"]:
        quest["renewal"]["TUE"] = "N"
    if "WED" not in quest["renewal"]:
        quest["renewal"]["WED"] = "N"
    if "THU" not in quest["renewal"]:
        quest["renewal"]["THU"] = "N"
    if "FRI" not in quest["renewal"]:
        quest["renewal"]["FRI"] = "N"
    if "SAT" not in quest["renewal"]:
        quest["renewal"]["SAT"] = "N"
    if "SUN" not in quest["renewal"]:
        quest["renewal"]["SUN"] = "N"

    quest["step1"] = json.loads(quest["step1"]) if quest["step1"] is not None else {}
    if "useYn" not in quest["step1"]:
        quest["step1"]["useYn"] = "N"
    if "count_process" not in quest["step1"]:
        quest["step1"]["count_process"] = 0
    if "count_ticket" not in quest["step1"]:
        quest["step1"]["count_ticket"] = 0

    quest["step2"] = json.loads(quest["step2"]) if quest["step2"] is not None else {}
    if "useYn" not in quest["step2"]:
        quest["step2"]["useYn"] = "N"
    if "count_process" not in quest["step2"]:
        quest["step2"]["count_process"] = 0
    if "count_ticket" not in quest["step2"]:
        quest["step2"]["count_ticket"] = 0

    quest["step3"] = json.loads(quest["step3"]) if quest["step3"] is not None else {}
    if "useYn" not in quest["step3"]:
        quest["step3"]["useYn"] = "N"
    if "count_process" not in quest["step3"]:
        quest["step3"]["count_process"] = 0
    if "count_ticket" not in quest["step3"]:
        quest["step3"]["count_ticket"] = 0

    update_filed_query_list = [
        "updated_id = :updated_id",
        "updated_date = :updated_date",
    ]

    db_execute_params = {"updated_id": -1, "updated_date": datetime.now(), "id": id}

    if req_body.use_yn is not None:
        update_filed_query_list.append("use_yn = :use_yn")
        db_execute_params["use_yn"] = req_body.use_yn

    if req_body.title is not None:
        update_filed_query_list.append("title = :title")
        db_execute_params["title"] = req_body.title

    if req_body.reward_id is not None:
        update_filed_query_list.append("reward_id = :reward_id")
        db_execute_params["reward_id"] = req_body.reward_id

    if req_body.end_date is not None:
        update_filed_query_list.append("end_date = :end_date")
        db_execute_params["end_date"] = req_body.end_date

    if req_body.goal_stage is not None:
        update_filed_query_list.append("goal_stage = :goal_stage")
        db_execute_params["goal_stage"] = req_body.goal_stage

    if req_body.renewal is not None:
        update_filed_query_list.append("renewal = :renewal")
        db_execute_params["renewal"] = json.dumps(
            {
                "MON": req_body.renewal["MON"]
                if "MON" in req_body.renewal
                else quest["renewal"]["MON"],
                "TUE": req_body.renewal["TUE"]
                if "TUE" in req_body.renewal
                else quest["renewal"]["TUE"],
                "WED": req_body.renewal["WED"]
                if "WED" in req_body.renewal
                else quest["renewal"]["WED"],
                "THU": req_body.renewal["THU"]
                if "THU" in req_body.renewal
                else quest["renewal"]["THU"],
                "FRI": req_body.renewal["FRI"]
                if "FRI" in req_body.renewal
                else quest["renewal"]["FRI"],
                "SAT": req_body.renewal["SAT"]
                if "SAT" in req_body.renewal
                else quest["renewal"]["SAT"],
                "SUN": req_body.renewal["SUN"]
                if "SUN" in req_body.renewal
                else quest["renewal"]["SUN"],
            }
        )

    if req_body.step1 is not None:
        update_filed_query_list.append("step1 = :step1")
        db_execute_params["step1"] = json.dumps(
            {
                "useYn": req_body.step1["useYn"]
                if "useYn" in req_body.step1
                else quest["step1"]["useYn"],
                "count_process": req_body.step1["count_process"]
                if "count_process" in req_body.step1
                else quest["step1"]["count_process"],
                "count_ticket": req_body.step1["count_ticket"]
                if "count_ticket" in req_body.step1
                else quest["step1"]["count_ticket"],
            }
        )

    if req_body.step2 is not None:
        update_filed_query_list.append("step2 = :step2")
        db_execute_params["step2"] = json.dumps(
            {
                "useYn": req_body.step2["useYn"]
                if "useYn" in req_body.step2
                else quest["step2"]["useYn"],
                "count_process": req_body.step2["count_process"]
                if "count_process" in req_body.step2
                else quest["step2"]["count_process"],
                "count_ticket": req_body.step2["count_ticket"]
                if "count_ticket" in req_body.step2
                else quest["step2"]["count_ticket"],
            }
        )

    if req_body.step3 is not None:
        update_filed_query_list.append("step3 = :step3")
        db_execute_params["step3"] = json.dumps(
            {
                "useYn": req_body.step3["useYn"]
                if "useYn" in req_body.step3
                else quest["step3"]["useYn"],
                "count_process": req_body.step3["count_process"]
                if "count_process" in req_body.step3
                else quest["step3"]["count_process"],
                "count_ticket": req_body.step3["count_ticket"]
                if "count_ticket" in req_body.step3
                else quest["step3"]["count_ticket"],
            }
        )

    update_filed_query = ",".join(update_filed_query_list)

    query = text(f"""
                        update tb_quest set
                        {update_filed_query}
                        where quest_id = :id
                    """)

    await db.execute(query, db_execute_params)

    return {"result": req_body}
