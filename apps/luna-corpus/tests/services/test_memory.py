"""Tests for memory service."""

from unittest.mock import MagicMock, patch

from app.db.models import MessageRole


class TestEstimateTokens:
    """Tests for estimate_tokens function."""

    def test_estimate_tokens(self):
        """Test token estimation."""
        from app.services.memory import estimate_tokens

        # 4 characters per token approximation
        assert estimate_tokens("hello") == 1
        assert estimate_tokens("hello world") == 2
        assert estimate_tokens("a" * 400) == 100


class TestFormatConversationHistory:
    """Tests for format_conversation_history function."""

    def test_empty_messages(self):
        """Test formatting empty message list."""
        from app.services.memory import format_conversation_history

        result = format_conversation_history([])
        assert result == ""

    def test_single_message(self):
        """Test formatting single message."""
        from app.services.memory import format_conversation_history

        msg = MagicMock()
        msg.role = MessageRole.USER
        msg.content = "Hello"

        result = format_conversation_history([msg])
        assert result == "User: Hello"

    def test_multiple_messages(self):
        """Test formatting multiple messages in chronological order."""
        from app.services.memory import format_conversation_history

        user_msg = MagicMock()
        user_msg.role = MessageRole.USER
        user_msg.content = "Hello"

        assistant_msg = MagicMock()
        assistant_msg.role = MessageRole.ASSISTANT
        assistant_msg.content = "Hi there!"

        # Messages in chronological order
        result = format_conversation_history([user_msg, assistant_msg])
        assert "User: Hello" in result
        assert "Assistant: Hi there!" in result


class TestAddMessageToConversation:
    """Tests for add_message_to_conversation function."""

    def test_add_message(self):
        """Test adding a message to conversation."""
        from app.services.memory import add_message_to_conversation

        mock_db = MagicMock()
        mock_conversation = MagicMock()

        with (
            patch(
                "app.services.memory.get_conversation", return_value=mock_conversation
            ),
            patch("app.services.memory.estimate_tokens", return_value=10),
        ):
            result = add_message_to_conversation(
                db=mock_db,
                conversation_id="conv-123",
                role=MessageRole.USER,
                content="Test message",
            )

            mock_db.add.assert_called_once()
            mock_db.commit.assert_called_once()
            assert result is not None


class TestCreateConversation:
    """Tests for create_conversation function."""

    def test_create_conversation_with_title(self):
        """Test creating conversation with title."""
        from app.services.memory import create_conversation

        mock_db = MagicMock()

        result = create_conversation(
            db=mock_db,
            knowledge_base_id="kb-test",
            title="My Conversation",
        )

        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()
        assert result.title == "My Conversation"

    def test_create_conversation_without_title(self):
        """Test creating conversation without title generates default."""
        from app.services.memory import create_conversation

        mock_db = MagicMock()

        result = create_conversation(db=mock_db, knowledge_base_id="kb-test")

        assert result.title.startswith("Conversation ")


class TestDeleteConversation:
    """Tests for delete_conversation function."""

    def test_delete_existing_conversation(self):
        """Test deleting existing conversation."""
        from app.services.memory import delete_conversation

        mock_db = MagicMock()
        mock_conversation = MagicMock()

        with patch(
            "app.services.memory.get_conversation", return_value=mock_conversation
        ):
            result = delete_conversation(db=mock_db, conversation_id="conv-123")

            assert result is True
            mock_db.delete.assert_called_once_with(mock_conversation)
            mock_db.commit.assert_called_once()

    def test_delete_nonexistent_conversation(self):
        """Test deleting nonexistent conversation returns False."""
        from app.services.memory import delete_conversation

        mock_db = MagicMock()

        with patch("app.services.memory.get_conversation", return_value=None):
            result = delete_conversation(db=mock_db, conversation_id="nonexistent")

            assert result is False
            mock_db.delete.assert_not_called()


class TestClearConversationMessages:
    """Tests for clear_conversation_messages function."""

    def test_clear_messages(self):
        """Test clearing conversation messages."""
        from app.services.memory import clear_conversation_messages

        mock_db = MagicMock()
        mock_conversation = MagicMock()

        with patch(
            "app.services.memory.get_conversation", return_value=mock_conversation
        ):
            result = clear_conversation_messages(
                db=mock_db,
                conversation_id="conv-123",
            )

            assert result is True
            mock_db.query.return_value.filter.return_value.delete.assert_called_once()
            assert mock_conversation.summary is None
            mock_db.commit.assert_called_once()

    def test_clear_nonexistent_conversation(self):
        """Test clearing nonexistent conversation returns False."""
        from app.services.memory import clear_conversation_messages

        mock_db = MagicMock()

        with patch("app.services.memory.get_conversation", return_value=None):
            result = clear_conversation_messages(
                db=mock_db,
                conversation_id="nonexistent",
            )

            assert result is False
