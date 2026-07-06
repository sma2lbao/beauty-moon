"""Tests for knowledge-base filter propagation in RAG flows."""

from unittest.mock import patch

from app.graph import rag_graph


def test_retrieve_node_passes_knowledge_base_filter():
    with (
        patch("app.graph.rag_graph.embed_text", return_value=[0.1]),
        patch(
            "app.graph.rag_graph.hybrid_search",
            return_value=[],
        ) as search,
        patch(
            "app.graph.rag_graph.validate_retrieved_docs_for_knowledge_base",
            return_value=[],
        ),
    ):
        rag_graph.retrieve_node({"question": "What?", "knowledge_base_id": "kb-1"})

    search.assert_called_once_with(
        "What?",
        [0.1],
        top_k=rag_graph.settings.retrieval_top_k,
        knowledge_base_id="kb-1",
    )


def test_answer_question_sets_knowledge_base_id_in_graph_state():
    class FakeGraph:
        def invoke(self, state):
            assert state["knowledge_base_id"] == "kb-1"
            return {"answer": "Answer", "sources": []}

    with patch("app.graph.rag_graph.get_rag_graph", return_value=FakeGraph()):
        result = rag_graph.answer_question("What?", knowledge_base_id="kb-1")

    assert result["answer"] == "Answer"


def test_validate_retrieved_docs_filters_documents_outside_knowledge_base():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.db.database import get_db
    from app.db.models import Base, Document, KnowledgeBase, Tenant, Workspace
    from app.graph import rag_graph

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    tenant = Tenant(name="Acme", slug="acme")
    workspace = Workspace(name="Research", slug="research", tenant=tenant)
    kb_one = KnowledgeBase(id="kb-1", name="Docs", slug="docs", workspace=workspace)
    kb_two = KnowledgeBase(id="kb-2", name="Notes", slug="notes", workspace=workspace)
    doc_one = Document(id="doc-1", title="Allowed", content="A", knowledge_base=kb_one)
    doc_two = Document(id="doc-2", title="Blocked", content="B", knowledge_base=kb_two)
    session.add_all([doc_one, doc_two])
    session.commit()
    session.close()

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    docs = [
        {
            "chunk_id": "chunk-1",
            "document_id": "doc-1",
            "content": "Allowed",
            "score": 0.1,
        },
        {
            "chunk_id": "chunk-2",
            "document_id": "doc-2",
            "content": "Blocked",
            "score": 0.2,
        },
        {"chunk_id": "chunk-3", "document_id": None, "content": "No doc", "score": 0.3},
    ]

    with patch("app.graph.rag_graph.get_db", override_get_db):
        filtered = rag_graph.validate_retrieved_docs_for_knowledge_base(docs, "kb-1")

    assert filtered == [
        {
            "chunk_id": "chunk-1",
            "document_id": "doc-1",
            "content": "Allowed",
            "score": 0.1,
        }
    ]
    engine.dispose()


def test_retrieve_node_validates_sources_before_returning_docs():
    with (
        patch("app.graph.rag_graph.embed_text", return_value=[0.1]),
        patch(
            "app.graph.rag_graph.hybrid_search",
            return_value=[
                {
                    "chunk_id": "chunk-1",
                    "document_id": "doc-1",
                    "content": "Allowed",
                    "score": 0.1,
                },
                {
                    "chunk_id": "chunk-2",
                    "document_id": "doc-2",
                    "content": "Blocked",
                    "score": 0.2,
                },
            ],
        ),
        patch(
            "app.graph.rag_graph.validate_retrieved_docs_for_knowledge_base",
            return_value=[
                {
                    "chunk_id": "chunk-1",
                    "document_id": "doc-1",
                    "content": "Allowed",
                    "score": 0.1,
                }
            ],
        ) as validate,
    ):
        result = rag_graph.retrieve_node(
            {"question": "What?", "knowledge_base_id": "kb-1"}
        )

    validate.assert_called_once()
    assert result["retrieved_docs"] == [
        {
            "chunk_id": "chunk-1",
            "document_id": "doc-1",
            "content": "Allowed",
            "score": 0.1,
        }
    ]
