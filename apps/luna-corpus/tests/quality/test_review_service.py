"""Unit tests for the review derivation and upsert service."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import (
    Base,
    EvaluationStatus,
    FeedbackRating,
    QAEvaluation,
    QAFeedback,
    QAInteraction,
    QAReview,
    ReviewRootCause,
    ReviewStatus,
)
from app.quality.review import (
    dismiss_review,
    get_review_detail,
    list_reviews,
    resolve_review,
)

KB = "kb-1"


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def _interaction(session, kb_id=KB):
    i = QAInteraction(
        knowledge_base_id=kb_id, question="Q", answer="A", sources=[]
    )
    session.add(i)
    session.commit()
    return i


def _add_feedback(session, iid, rating):
    session.add(QAFeedback(interaction_id=iid, rating=rating))
    session.commit()


def _add_eval(session, iid, faith, rel, status=EvaluationStatus.COMPLETED):
    session.add(
        QAEvaluation(
            interaction_id=iid,
            faithfulness=faith,
            answer_relevance=rel,
            status=status,
        )
    )
    session.commit()


def test_thumbs_down_enters_queue():
    session = _session()
    i = _interaction(session)
    _add_feedback(session, i.id, FeedbackRating.DOWN)
    rows, total = list_reviews(session, KB)
    assert len(rows) == 1
    assert total == 1
    assert rows[0]["interaction_id"] == i.id
    assert rows[0]["signals"]["thumbs_down"] is True
    assert rows[0]["signals"]["low_score"] is False


def test_low_score_enters_queue():
    session = _session()
    i = _interaction(session)
    _add_eval(session, i.id, faith=0.5, rel=0.9)
    rows, total = list_reviews(session, KB)
    assert len(rows) == 1
    assert total == 1
    assert rows[0]["signals"]["low_score"] is True


def test_threshold_is_strict_less_than():
    session = _session()
    i = _interaction(session)
    _add_eval(session, i.id, faith=0.6, rel=0.6)  # == 0.6, not < 0.6
    assert list_reviews(session, KB)[0] == []


def test_thumbs_up_and_good_score_not_in_queue():
    session = _session()
    i = _interaction(session)
    _add_feedback(session, i.id, FeedbackRating.UP)
    _add_eval(session, i.id, faith=0.9, rel=0.9)
    assert list_reviews(session, KB)[0] == []


def test_pending_eval_does_not_trigger():
    session = _session()
    i = _interaction(session)
    _add_eval(session, i.id, faith=0.1, rel=0.1, status=EvaluationStatus.PENDING)
    assert list_reviews(session, KB)[0] == []


def test_resolved_review_leaves_queue():
    session = _session()
    i = _interaction(session)
    _add_feedback(session, i.id, FeedbackRating.DOWN)
    resolve_review(
        session, KB, i.id,
        root_cause=ReviewRootCause.KNOWLEDGE_GAP, note="fixed", user_id="u1",
    )
    session.commit()
    assert list_reviews(session, KB)[0] == []
    resolved, resolved_total = list_reviews(session, KB, status_filter="resolved")
    assert len(resolved) == 1
    assert resolved_total == 1
    assert resolved[0]["review_status"] == "resolved"


def test_resolve_is_upsert_not_duplicate():
    session = _session()
    i = _interaction(session)
    _add_feedback(session, i.id, FeedbackRating.DOWN)
    resolve_review(
        session, KB, i.id,
        root_cause=ReviewRootCause.OTHER, note="first", user_id="u1",
    )
    session.commit()
    dismiss_review(session, KB, i.id, note="changed my mind", user_id="u2")
    session.commit()
    reviews = session.query(QAReview).filter(QAReview.interaction_id == i.id).all()
    assert len(reviews) == 1
    assert reviews[0].status == ReviewStatus.DISMISSED
    assert reviews[0].resolution_note == "changed my mind"


def test_cross_kb_returns_none():
    session = _session()
    i = _interaction(session, kb_id="other-kb")
    assert get_review_detail(session, KB, i.id) is None
    assert resolve_review(
        session, KB, i.id,
        root_cause=ReviewRootCause.OTHER, note="x", user_id="u1",
    ) is None


def test_detail_returns_signals_and_review():
    session = _session()
    i = _interaction(session)
    _add_feedback(session, i.id, FeedbackRating.DOWN)
    _add_eval(session, i.id, faith=0.4, rel=0.5)
    detail = get_review_detail(session, KB, i.id)
    assert detail["interaction"]["id"] == i.id
    assert len(detail["feedback"]) == 1
    assert detail["evaluation"]["faithfulness"] == 0.4
    assert detail["review"] is None


def test_pagination_total_reflects_full_filtered_count():
    """limit 生效时，total 仍应反映切片前的总条目数。"""
    session = _session()
    for _ in range(3):
        it = _interaction(session)
        _add_feedback(session, it.id, FeedbackRating.DOWN)
    rows, total = list_reviews(session, KB, limit=2)
    assert len(rows) == 2
    assert total == 3
