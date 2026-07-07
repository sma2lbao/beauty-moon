"""元数据 Schema 管理与分面聚合 API。"""
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.auth import AuthenticatedRequestContext, require_permission
from app.auth.permissions import PermissionSlug
from app.db.database import get_db
from app.metadata.facets import compute_facets
from app.metadata.models import MetadataFieldDefinition
from app.metadata.schema import (
    FieldDefinitionCreate,
    FieldDefinitionRead,
    FieldDefinitionUpdate,
)
from app.observability.metrics import RAG_FACET_DURATION, time_stage

router = APIRouter(prefix="/api/v1", tags=["metadata"])


def _ensure_kb_scope(kb_id: str, context: AuthenticatedRequestContext) -> None:
    if kb_id != context.knowledge_base.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge base not found",
        )


@router.post(
    "/knowledge-bases/{kb_id}/metadata-fields",
    response_model=FieldDefinitionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_metadata_field(
    kb_id: str,
    payload: FieldDefinitionCreate,
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.KNOWLEDGE_BASE_MANAGE)),
    ],
) -> FieldDefinitionRead:
    _ensure_kb_scope(kb_id, context)
    exists = (
        db.query(MetadataFieldDefinition)
        .filter(
            MetadataFieldDefinition.knowledge_base_id == kb_id,
            MetadataFieldDefinition.key == payload.key,
        )
        .first()
    )
    if exists:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"字段已存在: {payload.key}",
        )
    field = MetadataFieldDefinition(
        knowledge_base_id=kb_id,
        key=payload.key,
        label=payload.label,
        field_type=payload.field_type,
        options=payload.options,
        required=payload.required,
        is_facetable=payload.is_facetable,
    )
    db.add(field)
    db.commit()
    db.refresh(field)
    return FieldDefinitionRead.model_validate(field)


@router.get(
    "/knowledge-bases/{kb_id}/metadata-fields",
    response_model=list[FieldDefinitionRead],
)
def list_metadata_fields(
    kb_id: str,
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.KNOWLEDGE_BASE_READ)),
    ],
) -> list[FieldDefinitionRead]:
    _ensure_kb_scope(kb_id, context)
    fields = (
        db.query(MetadataFieldDefinition)
        .filter(MetadataFieldDefinition.knowledge_base_id == kb_id)
        .all()
    )
    return [FieldDefinitionRead.model_validate(f) for f in fields]


@router.patch(
    "/metadata-fields/{field_id}",
    response_model=FieldDefinitionRead,
)
def update_metadata_field(
    field_id: str,
    payload: FieldDefinitionUpdate,
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.KNOWLEDGE_BASE_MANAGE)),
    ],
) -> FieldDefinitionRead:
    field = (
        db.query(MetadataFieldDefinition)
        .filter(MetadataFieldDefinition.id == field_id)
        .first()
    )
    if not field or field.knowledge_base_id != context.knowledge_base.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="字段不存在",
        )
    data = payload.model_dump(exclude_unset=True)
    for attr, value in data.items():
        setattr(field, attr, value)
    db.commit()
    db.refresh(field)
    return FieldDefinitionRead.model_validate(field)


@router.delete(
    "/metadata-fields/{field_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_metadata_field(
    field_id: str,
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.KNOWLEDGE_BASE_MANAGE)),
    ],
) -> None:
    field = (
        db.query(MetadataFieldDefinition)
        .filter(MetadataFieldDefinition.id == field_id)
        .first()
    )
    if not field or field.knowledge_base_id != context.knowledge_base.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="字段不存在",
        )
    db.delete(field)
    db.commit()


@router.get("/knowledge-bases/{kb_id}/facets")
def get_facets(
    kb_id: str,
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[
        AuthenticatedRequestContext,
        Depends(require_permission(PermissionSlug.KNOWLEDGE_BASE_READ)),
    ],
) -> dict[str, Any]:
    _ensure_kb_scope(kb_id, context)
    with time_stage(RAG_FACET_DURATION):
        facets = compute_facets(db, kb_id)
    return {"facets": facets}
