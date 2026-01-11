from fastapi import status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from typing import Dict

from app.const import settings, ErrorMessages
from app.exceptions import CustomResponseException
import app.schemas.storage as storage_schema
import app.services.common.comm_service as comm_service


async def get_presigned_upload_url(
    req_body: storage_schema.UploadReqBody, db: AsyncSession
) -> Dict[str, str]:
    group_type = req_body.group_type
    file_name = req_body.file_name
    if not group_type or group_type == "":
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.GROUP_TYPE_REQUIRED,
        )
    if group_type not in storage_schema.available_group_types:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.INVALID_GROUP_TYPE,
        )
    if not file_name or file_name == "":
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.FILENAME_REQUIRED,
        )

    res_data = {}

    try:
        async with db.begin():
            # 랜덤 생성 uuid 중복 체크
            while True:
                file_name_to_uuid = comm_service.make_rand_uuid()
                ext = ""
                if "." in file_name:
                    ext = file_name.split(".")[-1]
                file_name_to_uuid = f"{file_name_to_uuid}.{ext}"

                query = text("""
                                    select a.file_group_id
                                    from tb_common_file a
                                    inner join tb_common_file_item b on a.file_group_id = b.file_group_id
                                    and b.use_yn = 'Y'
                                    and b.file_name = :file_name
                                    where a.group_type = :group_type
                                    and a.use_yn = 'Y'
                                """)

                result = await db.execute(
                    query, {"file_name": file_name_to_uuid, "group_type": group_type}
                )
                db_rst = result.mappings().all()

                if not db_rst:
                    break

            presigned_url = comm_service.make_r2_presigned_url(
                type="upload",
                bucket_name=settings.R2_SC_IMAGE_BUCKET,
                file_id=f"{group_type}/{file_name_to_uuid}",
            )

            query = text("""
                                insert into tb_common_file (group_type, created_id, updated_id)
                                values (:group_type, :created_id, :updated_id)
                                """)

            await db.execute(
                query,
                {
                    "group_type": group_type,
                    "created_id": settings.DB_DML_DEFAULT_ID,
                    "updated_id": settings.DB_DML_DEFAULT_ID,
                },
            )

            query = text("""
                                select last_insert_id()
                                """)

            result = await db.execute(query)
            new_file_group_id = result.scalar()

            query = text("""
                                insert into tb_common_file_item (file_group_id, file_name, file_org_name, file_path, created_id, updated_id)
                                values (:file_group_id, :file_name, :file_org_name, :file_path, :created_id, :updated_id)
                                """)

            await db.execute(
                query,
                {
                    "file_group_id": new_file_group_id,
                    "file_name": file_name_to_uuid,
                    "file_org_name": file_name,
                    "file_path": f"{settings.R2_SC_CDN_URL}/{group_type}/{file_name_to_uuid}",
                    "created_id": settings.DB_DML_DEFAULT_ID,
                    "updated_id": settings.DB_DML_DEFAULT_ID,
                },
            )

            res_data = {"fileId": new_file_group_id, "uploadPath": presigned_url}
    except CustomResponseException:
        raise
    except OperationalError:
        raise CustomResponseException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            message=ErrorMessages.DB_CONNECTION_ERROR,
        )
    except SQLAlchemyError:
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.DB_OPERATION_ERROR,
        )
    except Exception:
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.STORAGE_SERVICE_ERROR,
        )

    res_body = {"data": res_data}

    return res_body
