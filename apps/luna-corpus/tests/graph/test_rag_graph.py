"""Tests for LangGraph RAG flow."""
from unittest.mock import patch


def test_retrieve_node():
    """Test retrieve node."""
    from app.graph.rag_graph import retrieve_node
    from app.graph.state import RAGState

    mock_embedding = [0.1, 0.2, 0.3]
    mock_results = [
        {
            "chunk_id": "chunk-1",
            "document_id": "doc-1",
            "content": "Test content",
            "score": 0.95,
        }
    ]

    with patch("app.graph.rag_graph.embed_text", return_value=mock_embedding):
        with patch(
            "app.graph.rag_graph.search_vectorstore", return_value=mock_results
        ):
            state = RAGState(question="test question", retrieved_docs=[], answer=None, sources=[], processing_time_ms=None)
            result = retrieve_node(state)

            assert "retrieved_docs" in result
            assert len(result["retrieved_docs"]) == 1


def test_generate_node():
    """Test generate node."""
    from app.graph.rag_graph import generate_node
    from app.graph.state import RAGState

    state = RAGState(
        question="What is Python?",
        retrieved_docs=[
            {
                "chunk_id": "chunk-1",
                "document_id": "doc-1",
                "content": "Python is a programming language.",
                "score": 0.95,
            }
        ],
        answer=None,
        sources=[],
        processing_time_ms=None,
    )

    with patch(
        "app.graph.rag_graph.generate_response", return_value="Python is great!"
    ):
        result = generate_node(state)

        assert "answer" in result
        assert result["answer"] == "Python is great!"
        assert "sources" in result


def test_answer_question():
    """Test full RAG question answering."""
    from app.graph.rag_graph import answer_question

    mock_embedding = [0.1, 0.2, 0.3]
    mock_results = [
        {
            "chunk_id": "chunk-1",
            "document_id": "doc-1",
            "content": "Test content",
            "score": 0.95,
        }
    ]

    with patch("app.graph.rag_graph.embed_text", return_value=mock_embedding):
        with patch(
            "app.graph.rag_graph.search_vectorstore", return_value=mock_results
        ):
            with patch(
                "app.graph.rag_graph.generate_response",
                return_value="Test answer",
            ):
                result = answer_question("Test question")

                assert "answer" in result
                assert "sources" in result
                assert "processing_time_ms" in result


def test_answer_question_no_results():
    """Test answering when no documents found."""
    from app.graph.rag_graph import answer_question

    with patch("app.graph.rag_graph.embed_text", return_value=[0.1, 0.2]):
        with patch("app.graph.rag_graph.search_vectorstore", return_value=[]):
            result = answer_question("Test question")

            assert "I couldn't find" in result["answer"]
            assert result["sources"] == []
