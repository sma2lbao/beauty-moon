"""Document processing service for chunking and vectorization."""
from typing import Any

from langchain_core.documents import Document as LCDocument
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlalchemy.orm import Session

from app.db.models import Chunk, ContentStatus, ContentType, Document
from app.db.vectorstore import add_chunks_to_vectorstore, delete_chunks_from_vectorstore
from app.services.llm import embed_texts


class DocumentProcessor:
    """Processes documents: chunking and vectorization."""

    def __init__(
        self,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
    ):
        """Initialize processor.

        Args:
            chunk_size: Target size for each chunk in characters
            chunk_overlap: Overlap between chunks in characters
        """
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            length_function=len,
            separators=["\n\n", "\n", "。", "！", "？", " ", ""],
        )

    def detect_content_type(self, content: str) -> ContentType:
        """Detect the type of content.

        Args:
            content: Text content to analyze

        Returns:
            ContentType enum value
        """
        if "```" in content or "def " in content or "class " in content:
            return ContentType.CODE
        if "|" in content and ("---" in content or "--:" in content):
            return ContentType.TABLE
        return ContentType.TEXT

    def split_document(self, document: Document) -> list[dict[str, Any]]:
        """Split document into chunks.

        Args:
            document: Document to split

        Returns:
            List of chunk dictionaries
        """
        langchain_doc = LCDocument(
            page_content=document.content,
            metadata={"document_id": document.id},
        )

        splits = self.text_splitter.split_documents([langchain_doc])

        chunks = []
        for i, split in enumerate(splits):
            chunks.append({
                "document_id": document.id,
                "content": split.page_content,
                "content_type": self.detect_content_type(split.page_content),
                "chunk_metadata": None,
                "chunk_index": i,
            })

        return chunks

    def process_document(self, db: Session, document_id: str) -> list[Chunk]:
        """Process a document: create chunks and store vectors.

        Args:
            db: Database session
            document_id: ID of document to process

        Returns:
            List of created chunks
        """
        # Get document
        document = db.query(Document).filter(Document.id == document_id).first()
        if not document:
            raise ValueError(f"Document {document_id} not found")

        # Update status
        document.status = ContentStatus.PROCESSING
        db.commit()

        try:
            # Split into chunks
            chunk_dicts = self.split_document(document)

            # Delete existing chunks if any
            existing_chunks = (
                db.query(Chunk).filter(Chunk.document_id == document_id).all()
            )
            if existing_chunks:
                delete_chunks_from_vectorstore([c.id for c in existing_chunks])
                for chunk in existing_chunks:
                    db.delete(chunk)
                db.commit()

            # Create new chunks
            chunks = []
            for chunk_dict in chunk_dicts:
                chunk = Chunk(**chunk_dict)
                db.add(chunk)
                chunks.append(chunk)
            db.commit()

            # Generate embeddings and store in vector store
            texts = [c["content"] for c in chunk_dicts]
            embeddings = embed_texts(texts)

            add_chunks_to_vectorstore(
                chunks=[
                    {"id": c.id, "document_id": c.document_id, "content": c.content}
                    for c in chunks
                ],
                embeddings=embeddings,
            )

            # Update status
            document.status = ContentStatus.COMPLETED
            db.commit()

            return chunks

        except Exception as e:
            document.status = ContentStatus.ERROR
            db.commit()
            raise e
