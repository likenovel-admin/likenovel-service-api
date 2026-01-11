from pydantic import BaseModel, Field

available_group_types = ["badge", "cover", "episode", "panel", "user"]


class StorageBase(BaseModel):
    pass


"""
request area
"""

"""
response area
"""


class UploadReqBody(StorageBase):
    # 파일 업로드 시 클라이언트에서 보내는 request body
    group_type: str = Field(
        examples=["user"],
        description=f"객체 키 prefix, {' | '.join(available_group_types)}",
    )
    file_name: str = Field(examples=["file_name.ext"], description="원본 파일명")
