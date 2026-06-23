"""Conversation memory service."""
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Conversation, Message, MessageRole

settings = get_settings()


def estimate_tokens(text: str) -> int:
    """Estimate token count (rough approximation: 4 chars per token).

    Args:
        text: Text to estimate

    Returns:
        Estimated token count
    """
    return len(text) // 4


def get_conversation(
    db: Session,
    conversation_id: str,
    knowledge_base_id: str | None = None,
) -> Conversation | None:
    """Get a conversation by ID.

    Args:
        db: Database session
        conversation_id: Conversation ID
        knowledge_base_id: Optional knowledge base ID for scoping

    Returns:
        Conversation or None if not found
    """
    query = db.query(Conversation).filter(Conversation.id == conversation_id)
    if knowledge_base_id is not None:
        query = query.filter(Conversation.knowledge_base_id == knowledge_base_id)
    return query.first()


def get_conversation_messages(
    db: Session,
    conversation_id: str,
    max_messages: int | None = None,
) -> list[Message]:
    """Retrieve messages for a conversation.

    Args:
        db: Database session
        conversation_id: Conversation ID
        max_messages: Limit number of messages (uses config if None)

    Returns:
        List of messages in chronological order
    """
    if max_messages is None:
        max_messages = settings.conversation_memory_window

    return (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc())
        .limit(max_messages)
        .all()
    )


def get_message_count(db: Session, conversation_id: str) -> int:
    """Get total message count for a conversation.

    Args:
        db: Database session
        conversation_id: Conversation ID

    Returns:
        Number of messages
    """
    return (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .count()
    )


def format_conversation_history(messages: list[Message]) -> str:
    """Format conversation history for LLM context.

    Args:
        messages: List of messages

    Returns:
        Formatted conversation history string
    """
    if not messages:
        return ""

    formatted = []
    for msg in reversed(messages):
        role_label = "User" if msg.role == MessageRole.USER else "Assistant"
        formatted.append(f"{role_label}: {msg.content}")

    return "\n\n".join(formatted)


def get_memory_context(
    db: Session,
    conversation_id: str,
) -> tuple[str, bool]:
    """Get formatted memory context with summarization check.

    Args:
        db: Database session
        conversation_id: Conversation ID

    Returns:
        Tuple of (formatted_context, needs_summarization)
    """
    conversation = get_conversation(db, conversation_id)

    if not conversation:
        return "", False

    message_count = get_message_count(db, conversation_id)
    needs_summarization = message_count >= settings.conversation_summarize_threshold

    if conversation.summary:
        return f"[Previous conversation summary]\n{conversation.summary}\n\n[Recent messages]", True

    return "", needs_summarization


def add_message_to_conversation(
    db: Session,
    conversation_id: str,
    role: MessageRole,
    content: str,
) -> Message:
    """Add a message to a conversation.

    Args:
        db: Database session
        conversation_id: Conversation ID
        role: Message role
        content: Message content

    Returns:
        Created message
    """
    token_count = estimate_tokens(content)

    message = Message(
        conversation_id=conversation_id,
        role=role,
        content=content,
        token_count=token_count,
    )
    db.add(message)

    conversation = get_conversation(db, conversation_id)
    if conversation:
        conversation.updated_at = datetime.now()

    db.commit()
    db.refresh(message)

    return message


def create_conversation(
    db: Session,
    knowledge_base_id: str,
    title: str | None = None,
) -> Conversation:
    """Create a new conversation.

    Args:
        db: Database session
        knowledge_base_id: Knowledge base ID to associate with the conversation
        title: Optional conversation title

    Returns:
        Created conversation
    """
    if not title:
        title = f"Conversation {datetime.now().strftime('%Y-%m-%d %H:%M')}"

    conversation = Conversation(title=title, knowledge_base_id=knowledge_base_id)
    db.add(conversation)
    db.commit()
    db.refresh(conversation)

    return conversation


def delete_conversation(db: Session, conversation_id: str) -> bool:
    """Delete a conversation.

    Args:
        db: Database session
        conversation_id: Conversation ID

    Returns:
        True if deleted, False if not found
    """
    conversation = get_conversation(db, conversation_id)
    if not conversation:
        return False

    db.delete(conversation)
    db.commit()
    return True


def clear_conversation_messages(db: Session, conversation_id: str) -> bool:
    """Clear all messages from a conversation (keeps conversation).

    Args:
        db: Database session
        conversation_id: Conversation ID

    Returns:
        True if cleared, False if conversation not found
    """
    conversation = get_conversation(db, conversation_id)
    if not conversation:
        return False

    db.query(Message).filter(Message.conversation_id == conversation_id).delete()
    conversation.summary = None
    conversation.updated_at = datetime.now()
    db.commit()

    return True
