"""Tests for TaskService."""
from unittest.mock import MagicMock

import pytest

from app.db.models import TaskStatus, TaskType
from app.services.ingestion.tasks import TaskService


@pytest.fixture
def task_service():
    return TaskService()


def _mock_query_chain(db, *methods, return_value):
    """Set return_value at the end of a db.query().method1().method2()... chain."""
    target = db.query.return_value
    for method in methods[:-1]:
        target = getattr(target, method).return_value
    last_method_mock = getattr(target, methods[-1])
    last_method_mock.return_value = return_value


def test_create_task(task_service):
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None

    task = task_service.create_task(
        db, TaskType.DOCUMENT_INDEX, "doc-1", "kb-1"
    )

    assert task.type == TaskType.DOCUMENT_INDEX
    assert task.status == TaskStatus.PENDING
    assert task.target_id == "doc-1"
    assert task.knowledge_base_id == "kb-1"
    db.add.assert_called_once()
    db.commit.assert_called()


def test_create_task_deduplication(task_service):
    db = MagicMock()
    existing = MagicMock()
    existing.status = TaskStatus.PENDING
    _mock_query_chain(db, "filter", "order_by", "first", return_value=existing)

    task = task_service.create_task(
        db, TaskType.DOCUMENT_INDEX, "doc-1", "kb-1"
    )

    assert task is existing
    db.add.assert_not_called()


def test_get_task(task_service):
    db = MagicMock()
    expected = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = expected

    result = task_service.get_task(db, "task-1")

    assert result is expected


def test_list_tasks(task_service):
    db = MagicMock()
    task1 = MagicMock()
    task2 = MagicMock()
    _mock_query_chain(
        db, "filter", "order_by", "limit", "all", return_value=[task1, task2]
    )

    results = task_service.list_tasks(db, "kb-1")

    assert len(results) == 2


def test_list_tasks_with_status_filter(task_service):
    db = MagicMock()
    _mock_query_chain(
        db, "filter", "filter", "order_by", "limit", "all", return_value=[]
    )

    results = task_service.list_tasks(db, "kb-1", status=TaskStatus.COMPLETED)

    assert results == []


def test_mark_running(task_service):
    db = MagicMock()
    task = MagicMock()
    task.status = TaskStatus.PENDING
    db.query.return_value.filter.return_value.first.return_value = task

    result = task_service.mark_running(db, "task-1")

    assert result.status == TaskStatus.RUNNING
    assert result.started_at is not None
    db.commit.assert_called()


def test_mark_completed(task_service):
    db = MagicMock()
    task = MagicMock()
    task.status = TaskStatus.RUNNING
    db.query.return_value.filter.return_value.first.return_value = task

    result = task_service.mark_completed(db, "task-1")

    assert result.status == TaskStatus.COMPLETED
    assert result.completed_at is not None
    db.commit.assert_called()


def test_mark_failed(task_service):
    db = MagicMock()
    task = MagicMock()
    task.status = TaskStatus.RUNNING
    db.query.return_value.filter.return_value.first.return_value = task

    result = task_service.mark_failed(db, "task-1", "Something broke")

    assert result.status == TaskStatus.FAILED
    assert result.error_message == "Something broke"
    assert result.completed_at is not None
    db.commit.assert_called()
