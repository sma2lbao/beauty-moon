"""Tests for LangGraph RAG flow."""

from unittest.mock import patch

import pytest


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

    with (
        patch("app.graph.rag_graph.embed_text", return_value=mock_embedding),
        patch("app.graph.rag_graph.hybrid_search", return_value=mock_results),
        patch(
            "app.graph.rag_graph.validate_retrieved_docs_for_knowledge_base",
            return_value=mock_results,
        ),
    ):
        state = RAGState(
            question="test question",
            knowledge_base_id="kb-1",
            conversation_id=None,
            conversation_history=[],
            retrieved_docs=[],
            answer=None,
            sources=[],
            processing_time_ms=None,
            needs_summarization=False,
        )
        result = retrieve_node(state)

        assert "retrieved_docs" in result
        assert len(result["retrieved_docs"]) == 1


def test_generate_node():
    """Test generate node."""
    from app.graph.rag_graph import generate_node
    from app.graph.state import RAGState

    state = RAGState(
        question="What is Python?",
        knowledge_base_id="kb-1",
        conversation_id=None,
        conversation_history=[],
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
        needs_summarization=False,
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

    with (
        patch("app.graph.rag_graph.embed_text", return_value=mock_embedding),
        patch("app.graph.rag_graph.hybrid_search", return_value=mock_results),
        patch(
            "app.graph.rag_graph.validate_retrieved_docs_for_knowledge_base",
            return_value=mock_results,
        ),
        patch("app.graph.rag_graph.generate_response", return_value="Test answer"),
    ):
        result = answer_question("Test question", "kb-1")

        assert "answer" in result
        assert "sources" in result
        assert "processing_time_ms" in result


def test_answer_question_no_results():
    """Test answering when no documents found."""
    from app.graph.rag_graph import answer_question

    with (
        patch("app.graph.rag_graph.embed_text", return_value=[0.1, 0.2]),
        patch("app.graph.rag_graph.hybrid_search", return_value=[]),
        patch(
            "app.graph.rag_graph.validate_retrieved_docs_for_knowledge_base",
            return_value=[],
        ),
    ):
        result = answer_question("Test question", "kb-1")

        assert "I couldn't find" in result["answer"]
        assert result["sources"] == []


def test_answer_question_uses_validated_sources_for_prompt():
    from app.graph.rag_graph import answer_question

    raw_results = [
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
    ]
    validated_results = [raw_results[0]]

    with (
        patch("app.graph.rag_graph.embed_text", return_value=[0.1]),
        patch("app.graph.rag_graph.hybrid_search", return_value=raw_results),
        patch(
            "app.graph.rag_graph.validate_retrieved_docs_for_knowledge_base",
            return_value=validated_results,
        ),
        patch(
            "app.graph.rag_graph.generate_response", return_value="Answer"
        ) as generate,
    ):
        result = answer_question("Test question", "kb-1")

    prompt = generate.call_args.kwargs["prompt"]
    assert "Allowed" in prompt
    assert "Blocked" not in prompt
    assert result["sources"] == [
        {
            "document_id": "doc-1",
            "chunk_content": "Allowed",
            "relevance_score": 0.1,
            "chunk_index": None,
            "char_start": None,
            "char_end": None,
            "heading_path": None,
        }
    ]


def test_answer_question_returns_no_results_when_validation_filters_everything():
    from app.graph.rag_graph import answer_question

    with (
        patch("app.graph.rag_graph.embed_text", return_value=[0.1]),
        patch(
            "app.graph.rag_graph.hybrid_search",
            return_value=[
                {
                    "chunk_id": "chunk-2",
                    "document_id": "doc-2",
                    "content": "Blocked",
                    "score": 0.2,
                }
            ],
        ),
        patch(
            "app.graph.rag_graph.validate_retrieved_docs_for_knowledge_base",
            return_value=[],
        ),
    ):
        result = answer_question("Test question", "kb-1")

    assert "I couldn't find" in result["answer"]
    assert result["sources"] == []


async def collect_stream(async_iterable):
    events = []
    async for event in async_iterable:
        events.append(event)
    return events


@pytest.mark.asyncio
async def test_answer_question_stream_uses_validated_sources():
    from app.graph.rag_graph import answer_question_stream

    raw_results = [
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
    ]
    validated_results = [raw_results[0]]

    async def fake_streaming_response(prompt, context):
        yield "Answer"

    with (
        patch("app.graph.rag_graph.embed_text", return_value=[0.1]),
        patch("app.graph.rag_graph.hybrid_search", return_value=raw_results),
        patch(
            "app.graph.rag_graph.validate_retrieved_docs_for_knowledge_base",
            return_value=validated_results,
        ),
        patch(
            "app.graph.rag_graph.generate_streaming_response", fake_streaming_response
        ),
    ):
        events = await collect_stream(answer_question_stream("Test question", "kb-1"))

    done = [event for event in events if event["event"] == "done"][0]
    assert done["data"]["sources"] == [
        {
            "document_id": "doc-1",
            "chunk_content": "Allowed",
            "relevance_score": 0.1,
            "chunk_index": None,
            "char_start": None,
            "char_end": None,
            "heading_path": None,
        }
    ]


def test_answer_question_multi_turn_uses_validated_sources():
    from app.graph.rag_graph import answer_question_multi_turn

    raw_results = [
        {
            "chunk_id": "chunk-1",
            "document_id": "doc-1",
            "content": "Allowed",
            "score": 0.1,
        }
    ]

    with (
        patch("app.graph.rag_graph.embed_text", return_value=[0.1]),
        patch("app.graph.rag_graph.hybrid_search", return_value=raw_results),
        patch(
            "app.graph.rag_graph.validate_retrieved_docs_for_knowledge_base",
            return_value=raw_results,
        ),
        patch("app.graph.rag_graph.generate_response", return_value="Answer"),
    ):
        result = answer_question_multi_turn("Test question", "kb-1")

    assert result["sources"] == [
        {
            "document_id": "doc-1",
            "chunk_content": "Allowed",
            "relevance_score": 0.1,
            "chunk_index": None,
            "char_start": None,
            "char_end": None,
            "heading_path": None,
        }
    ]


@pytest.mark.asyncio
async def test_answer_question_multi_turn_stream_uses_validated_sources():
    from app.graph.rag_graph import answer_question_multi_turn_stream

    raw_results = [
        {
            "chunk_id": "chunk-1",
            "document_id": "doc-1",
            "content": "Allowed",
            "score": 0.1,
        }
    ]

    async def fake_streaming_response(prompt, context):
        yield "Answer"

    with (
        patch("app.graph.rag_graph.embed_text", return_value=[0.1]),
        patch("app.graph.rag_graph.hybrid_search", return_value=raw_results),
        patch(
            "app.graph.rag_graph.validate_retrieved_docs_for_knowledge_base",
            return_value=raw_results,
        ),
        patch(
            "app.graph.rag_graph.generate_streaming_response", fake_streaming_response
        ),
    ):
        events = await collect_stream(
            answer_question_multi_turn_stream("Test question", "kb-1")
        )

    done = [event for event in events if event["event"] == "done"][0]
    assert done["data"]["sources"] == [
        {
            "document_id": "doc-1",
            "chunk_content": "Allowed",
            "relevance_score": 0.1,
            "chunk_index": None,
            "char_start": None,
            "char_end": None,
            "heading_path": None,
        }
    ]
