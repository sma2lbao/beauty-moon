"""Task service for managing background ingestion tasks."""
from datetime import datetime

from sqlalchemy.orm import Session

from app.db.models import IngestionTask, TaskStatus, TaskType


class TaskService:
    """Manage ingestion task lifecycle."""

    def create_task(
        self,
        db: Session,
        type: TaskType,
        target_id: str,
        knowledge_base_id: str,
    ) -> IngestionTask:
        """Create a new task, or return existing pending/running task.

        If a PENDING or RUNNING task already exists for the same type+target,
        return it instead of creating a duplicate.
        """
        existing = self.get_task_by_target(db, type, target_id)
        if existing and existing.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
            return existing

        task = IngestionTask(
            type=type,
            target_id=target_id,
            knowledge_base_id=knowledge_base_id,
            status=TaskStatus.PENDING,
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        return task

    def get_task(self, db: Session, task_id: str) -> IngestionTask | None:
        """Get task by ID."""
        return db.query(IngestionTask).filter(IngestionTask.id == task_id).first()

    def get_task_by_target(
        self, db: Session, type: TaskType, target_id: str
    ) -> IngestionTask | None:
        """Get most recent task for a given type + target."""
        return (
            db.query(IngestionTask)
            .filter(IngestionTask.type == type, IngestionTask.target_id == target_id)
            .order_by(IngestionTask.created_at.desc())
            .first()
        )

    def list_tasks(
        self,
        db: Session,
        knowledge_base_id: str,
        status: TaskStatus | None = None,
        limit: int = 50,
    ) -> list[IngestionTask]:
        """List tasks for a knowledge base, optionally filtered by status."""
        query = db.query(IngestionTask).filter(
            IngestionTask.knowledge_base_id == knowledge_base_id
        )
        if status:
            query = query.filter(IngestionTask.status == status)
        return query.order_by(IngestionTask.created_at.desc()).limit(limit).all()

    def mark_running(self, db: Session, task_id: str) -> IngestionTask:
        """Mark task as running and set started_at."""
        task = self.get_task(db, task_id)
        if task:
            task.status = TaskStatus.RUNNING
            task.started_at = datetime.now()
            db.commit()
            db.refresh(task)
        return task

    def mark_completed(self, db: Session, task_id: str) -> IngestionTask:
        """Mark task as completed and set completed_at."""
        task = self.get_task(db, task_id)
        if task:
            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.now()
            db.commit()
            db.refresh(task)
        return task

    def mark_failed(
        self, db: Session, task_id: str, error_message: str
    ) -> IngestionTask:
        """Mark task as failed, record error, and set completed_at."""
        task = self.get_task(db, task_id)
        if task:
            task.status = TaskStatus.FAILED
            task.error_message = error_message
            task.completed_at = datetime.now()
            db.commit()
            db.refresh(task)
        return task
