"""元数据字段类型与字段定义 Pydantic 模型。"""
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class FieldType(StrEnum):
    """元数据字段类型。"""

    ENUM = "enum"
    STRING = "string"
    DATE = "date"
    NUMBER = "number"
    TAGS = "tags"


class FieldDefinitionCreate(BaseModel):
    """创建字段定义的请求模型。"""

    key: str = Field(..., min_length=1, max_length=64)
    label: str = Field(..., min_length=1, max_length=255)
    field_type: FieldType
    options: list[str] | None = None
    required: bool = False
    is_facetable: bool = True


class FieldDefinitionUpdate(BaseModel):
    """更新字段定义的请求模型（字段类型与 key 不可改）。"""

    label: str | None = Field(default=None, min_length=1, max_length=255)
    options: list[str] | None = None
    required: bool | None = None
    is_facetable: bool | None = None


class FieldDefinitionRead(BaseModel):
    """字段定义响应模型。"""

    id: str
    knowledge_base_id: str
    key: str
    label: str
    field_type: FieldType
    options: list[str] | None
    required: bool
    is_facetable: bool

    model_config = ConfigDict(from_attributes=True)
