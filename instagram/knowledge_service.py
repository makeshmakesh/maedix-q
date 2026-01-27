"""
Knowledge Base Service for document processing and embedding.

Handles:
- Document upload to S3
- Text extraction from PDF, DOCX, CSV, Excel
- Text chunking
- Embedding generation
- Storage in database
"""

import io
import os
import uuid
import logging
from typing import Optional, List, Dict, Tuple
from django.utils import timezone
from openai import OpenAI

from core.models import Configuration
from core.s3_utils import upload_to_s3, delete_from_s3
from .models import KnowledgeBase, KnowledgeItem, KnowledgeChunk
from .constants import (
    AI_MODELS, AI_CREDITS, EMBEDDING_SETTINGS, SUPPORTED_DOCUMENT_TYPES
)

logger = logging.getLogger(__name__)


# =============================================================================
# Document Extractors
# =============================================================================

class TextExtractor:
    """Extract text from various document types"""

    @staticmethod
    def extract_from_pdf(file_content: bytes) -> Tuple[str, Dict]:
        """Extract text from PDF file"""
        try:
            import PyPDF2
            pdf_reader = PyPDF2.PdfReader(io.BytesIO(file_content))
            text_parts = []
            metadata = {'pages': len(pdf_reader.pages), 'page_texts': []}

            for i, page in enumerate(pdf_reader.pages):
                page_text = page.extract_text() or ''
                text_parts.append(page_text)
                metadata['page_texts'].append({
                    'page': i + 1,
                    'char_count': len(page_text)
                })

            return '\n\n'.join(text_parts), metadata
        except ImportError:
            logger.error("PyPDF2 not installed")
            return '', {'error': 'PyPDF2 not installed'}
        except Exception as e:
            logger.error(f"Error extracting PDF: {e}")
            return '', {'error': str(e)}

    @staticmethod
    def extract_from_docx(file_content: bytes) -> Tuple[str, Dict]:
        """Extract text from DOCX file"""
        try:
            from docx import Document
            doc = Document(io.BytesIO(file_content))
            paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
            metadata = {'paragraphs': len(paragraphs)}
            return '\n\n'.join(paragraphs), metadata
        except ImportError:
            logger.error("python-docx not installed")
            return '', {'error': 'python-docx not installed'}
        except Exception as e:
            logger.error(f"Error extracting DOCX: {e}")
            return '', {'error': str(e)}

    @staticmethod
    def extract_from_csv(file_content: bytes) -> Tuple[str, Dict]:
        """Extract text from CSV file"""
        try:
            import csv
            content = file_content.decode('utf-8')
            reader = csv.DictReader(io.StringIO(content))
            rows = list(reader)
            metadata = {
                'rows': len(rows),
                'columns': reader.fieldnames or []
            }

            # Convert rows to readable text
            text_parts = []
            for i, row in enumerate(rows):
                row_text = f"Row {i + 1}: " + ', '.join(
                    f"{k}: {v}" for k, v in row.items() if v
                )
                text_parts.append(row_text)

            return '\n'.join(text_parts), metadata
        except Exception as e:
            logger.error(f"Error extracting CSV: {e}")
            return '', {'error': str(e)}

    @staticmethod
    def extract_from_excel(file_content: bytes) -> Tuple[str, Dict]:
        """Extract text from Excel file"""
        try:
            import pandas as pd
            # Try reading as xlsx first
            try:
                df = pd.read_excel(io.BytesIO(file_content), engine='openpyxl')
            except Exception:
                df = pd.read_excel(io.BytesIO(file_content), engine='xlrd')

            metadata = {
                'rows': len(df),
                'columns': list(df.columns)
            }

            # Convert to text
            text_parts = []
            for i, row in df.iterrows():
                row_text = f"Row {i + 1}: " + ', '.join(
                    f"{col}: {val}" for col, val in row.items()
                    if pd.notna(val) and str(val).strip()
                )
                text_parts.append(row_text)

            return '\n'.join(text_parts), metadata
        except ImportError:
            logger.error("pandas or openpyxl not installed")
            return '', {'error': 'pandas/openpyxl not installed'}
        except Exception as e:
            logger.error(f"Error extracting Excel: {e}")
            return '', {'error': str(e)}

    @classmethod
    def extract(cls, file_content: bytes, item_type: str) -> Tuple[str, Dict]:
        """Extract text based on item type"""
        extractors = {
            'pdf': cls.extract_from_pdf,
            'docx': cls.extract_from_docx,
            'csv': cls.extract_from_csv,
            'excel': cls.extract_from_excel,
        }
        extractor = extractors.get(item_type)
        if not extractor:
            return '', {'error': f'Unsupported type: {item_type}'}
        return extractor(file_content)


# =============================================================================
# Text Chunker
# =============================================================================

class TextChunker:
    """Split text into chunks for embedding"""

    def __init__(
        self,
        chunk_size: int = None,
        chunk_overlap: int = None
    ):
        self.chunk_size = chunk_size or EMBEDDING_SETTINGS.get('chunk_size', 500)
        self.chunk_overlap = chunk_overlap or EMBEDDING_SETTINGS.get('chunk_overlap', 50)

    def estimate_tokens(self, text: str) -> int:
        """Rough token estimation (4 chars per token)"""
        return len(text) // 4

    def chunk_text(self, text: str) -> List[Dict]:
        """
        Split text into overlapping chunks.
        Returns list of {'content': str, 'token_count': int, 'index': int}
        """
        if not text.strip():
            return []

        # Split by paragraphs first
        paragraphs = text.split('\n\n')
        paragraphs = [p.strip() for p in paragraphs if p.strip()]

        chunks = []
        current_chunk = []
        current_tokens = 0

        for para in paragraphs:
            para_tokens = self.estimate_tokens(para)

            # If single paragraph exceeds chunk size, split by sentences
            if para_tokens > self.chunk_size:
                # Save current chunk first
                if current_chunk:
                    chunk_text = '\n\n'.join(current_chunk)
                    chunks.append({
                        'content': chunk_text,
                        'token_count': self.estimate_tokens(chunk_text),
                        'index': len(chunks)
                    })
                    current_chunk = []
                    current_tokens = 0

                # Split large paragraph by sentences
                sentences = para.replace('. ', '.\n').split('\n')
                for sentence in sentences:
                    sent_tokens = self.estimate_tokens(sentence)
                    if current_tokens + sent_tokens > self.chunk_size and current_chunk:
                        chunk_text = ' '.join(current_chunk)
                        chunks.append({
                            'content': chunk_text,
                            'token_count': self.estimate_tokens(chunk_text),
                            'index': len(chunks)
                        })
                        # Keep overlap
                        overlap_text = ' '.join(current_chunk[-2:]) if len(current_chunk) > 2 else ''
                        current_chunk = [overlap_text] if overlap_text else []
                        current_tokens = self.estimate_tokens(overlap_text)
                    current_chunk.append(sentence)
                    current_tokens += sent_tokens
            else:
                # Add paragraph to current chunk
                if current_tokens + para_tokens > self.chunk_size and current_chunk:
                    chunk_text = '\n\n'.join(current_chunk)
                    chunks.append({
                        'content': chunk_text,
                        'token_count': self.estimate_tokens(chunk_text),
                        'index': len(chunks)
                    })
                    # Keep last paragraph for overlap
                    current_chunk = [current_chunk[-1]] if current_chunk else []
                    current_tokens = self.estimate_tokens(current_chunk[0]) if current_chunk else 0

                current_chunk.append(para)
                current_tokens += para_tokens

        # Don't forget last chunk
        if current_chunk:
            chunk_text = '\n\n'.join(current_chunk)
            chunks.append({
                'content': chunk_text,
                'token_count': self.estimate_tokens(chunk_text),
                'index': len(chunks)
            })

        return chunks


# =============================================================================
# Embedding Generator
# =============================================================================

class EmbeddingGenerator:
    """Generate embeddings using OpenAI API"""

    def __init__(self):
        api_key = Configuration.get_value('openai_api_key', '')
        if not api_key:
            raise ValueError("OpenAI API key not configured")
        self.client = OpenAI(api_key=api_key)
        self.model = AI_MODELS.get('embedding', 'text-embedding-3-small')

    def generate_embedding(self, text: str) -> Tuple[List[float], int]:
        """
        Generate embedding for text.
        Returns (embedding_vector, token_count)
        """
        try:
            response = self.client.embeddings.create(
                model=self.model,
                input=text
            )
            embedding = response.data[0].embedding
            tokens = response.usage.total_tokens
            return embedding, tokens
        except Exception as e:
            logger.error(f"Error generating embedding: {e}")
            return [], 0

    def generate_embeddings_batch(self, texts: List[str]) -> List[Tuple[List[float], int]]:
        """Generate embeddings for multiple texts"""
        results = []
        # OpenAI supports batch embedding
        try:
            response = self.client.embeddings.create(
                model=self.model,
                input=texts
            )
            for i, data in enumerate(response.data):
                results.append((data.embedding, 0))
            # Distribute total tokens across results
            total_tokens = response.usage.total_tokens
            tokens_per = total_tokens // len(texts) if texts else 0
            results = [(emb, tokens_per) for emb, _ in results]
        except Exception as e:
            logger.error(f"Error generating batch embeddings: {e}")
            results = [([], 0) for _ in texts]
        return results


# =============================================================================
# Knowledge Service
# =============================================================================

class KnowledgeService:
    """Main service for knowledge base operations"""

    def __init__(self, user):
        self.user = user

    def create_knowledge_base(
        self,
        name: str,
        description: str = '',
        agent=None
    ) -> KnowledgeBase:
        """Create a new knowledge base"""
        return KnowledgeBase.objects.create(
            user=self.user,
            agent=agent,
            name=name,
            description=description
        )

    def add_text_item(
        self,
        knowledge_base: KnowledgeBase,
        title: str,
        content: str,
        process_now: bool = True
    ) -> KnowledgeItem:
        """Add a text item to knowledge base"""
        item = KnowledgeItem.objects.create(
            knowledge_base=knowledge_base,
            item_type='text',
            title=title,
            content=content,
            processing_status='pending'
        )

        if process_now:
            self.process_item(item)

        return item

    def add_document_item(
        self,
        knowledge_base: KnowledgeBase,
        uploaded_file,
        item_type: str,
        process_now: bool = True
    ) -> Tuple[KnowledgeItem, Optional[str]]:
        """
        Add a document item to knowledge base.
        Returns (item, error_message)
        """
        # Validate file type
        type_config = SUPPORTED_DOCUMENT_TYPES.get(item_type)
        if not type_config:
            return None, f"Unsupported document type: {item_type}"

        # Validate size
        max_size = type_config['max_size_mb'] * 1024 * 1024
        if uploaded_file.size > max_size:
            return None, f"File too large. Maximum size: {type_config['max_size_mb']}MB"

        # Upload to S3
        file_content = uploaded_file.read()
        s3_key = f"knowledge/{self.user.id}/{uuid.uuid4().hex}/{uploaded_file.name}"

        url, key, error = upload_to_s3(
            file_content,
            s3_key,
            uploaded_file.content_type
        )

        if error:
            return None, f"Failed to upload file: {error}"

        # Create item
        item = KnowledgeItem.objects.create(
            knowledge_base=knowledge_base,
            item_type=item_type,
            title=uploaded_file.name,
            file_url=url,
            file_s3_key=key,
            file_name=uploaded_file.name,
            file_size=uploaded_file.size,
            processing_status='pending'
        )

        if process_now:
            self.process_item(item)

        return item, None

    def process_item(self, item: KnowledgeItem) -> bool:
        """Process a knowledge item (extract text, chunk, embed)"""
        item.mark_processing()

        try:
            # Get text content
            if item.item_type == 'text':
                text = item.content
                metadata = {}
            else:
                # Download file from S3 and extract text
                text, metadata = self._extract_text_from_file(item)

            if not text:
                item.mark_failed(metadata.get('error', 'No text extracted'))
                return False

            # Chunk text
            chunker = TextChunker()
            chunks = chunker.chunk_text(text)

            if not chunks:
                item.mark_failed('No chunks generated')
                return False

            # Generate embeddings
            embedder = EmbeddingGenerator()
            total_tokens = 0
            total_cost = 0.0

            for chunk_data in chunks:
                embedding, tokens = embedder.generate_embedding(chunk_data['content'])
                if not embedding:
                    continue

                # Create chunk record
                KnowledgeChunk.objects.create(
                    knowledge_item=item,
                    content=chunk_data['content'],
                    chunk_index=chunk_data['index'],
                    token_count=chunk_data['token_count'],
                    embedding=embedding,
                    metadata={
                        **metadata,
                        'chunk_index': chunk_data['index']
                    }
                )
                total_tokens += tokens

            # Calculate cost
            cost_per_1k = AI_CREDITS.get('EMBEDDING_COST_PER_1K_TOKENS', 0.02)
            total_cost = (total_tokens / 1000) * cost_per_1k

            # Deduct credits from user
            from .ai_engine import CreditManager
            CreditManager.deduct_credits(
                self.user,
                total_cost,
                f"Embedding: {item.title or item.file_name}"
            )

            # Log usage to AIUsageLog
            from .models import AIUsageLog
            AIUsageLog.log_usage(
                user=self.user,
                session=None,
                agent=item.knowledge_base.agent,
                usage_type='embedding',
                model=AI_MODELS.get('embedding', 'text-embedding-3-small'),
                input_tokens=total_tokens,
                output_tokens=0,
                cost_usd=(total_tokens * 0.02) / 1_000_000,  # text-embedding-3-small pricing
                credits_charged=total_cost
            )

            # Mark completed
            item.mark_completed(
                chunk_count=len(chunks),
                token_count=total_tokens,
                embedding_cost=total_cost
            )

            return True

        except Exception as e:
            logger.error(f"Error processing item {item.id}: {e}")
            item.mark_failed(str(e))
            return False

    def _extract_text_from_file(self, item: KnowledgeItem) -> Tuple[str, Dict]:
        """Download file from S3 and extract text"""
        import boto3
        from core.models import Configuration

        # Get S3 client
        aws_access_key = Configuration.get_value('aws_access_key_id', '')
        aws_secret_key = Configuration.get_value('aws_secret_access_key', '')
        aws_region = Configuration.get_value('aws_region', 'ap-south-1')
        bucket_name = Configuration.get_value('aws_s3_bucket', '')

        if not all([aws_access_key, aws_secret_key, bucket_name]):
            return '', {'error': 'S3 not configured'}

        try:
            s3_client = boto3.client(
                's3',
                aws_access_key_id=aws_access_key,
                aws_secret_access_key=aws_secret_key,
                region_name=aws_region
            )

            # Download file
            response = s3_client.get_object(Bucket=bucket_name, Key=item.file_s3_key)
            file_content = response['Body'].read()

            # Extract text
            return TextExtractor.extract(file_content, item.item_type)

        except Exception as e:
            logger.error(f"Error downloading/extracting file: {e}")
            return '', {'error': str(e)}

    def delete_item(self, item: KnowledgeItem) -> bool:
        """Delete a knowledge item and its S3 file"""
        try:
            # Delete from S3 if file item
            if item.file_s3_key:
                delete_from_s3(item.file_s3_key)

            # Delete chunks (cascade will handle this)
            item.delete()

            # Update KB stats
            item.knowledge_base.update_stats()

            return True
        except Exception as e:
            logger.error(f"Error deleting item: {e}")
            return False

    def delete_knowledge_base(self, kb: KnowledgeBase) -> bool:
        """Delete a knowledge base and all its items"""
        try:
            # Delete all S3 files
            for item in kb.items.all():
                if item.file_s3_key:
                    delete_from_s3(item.file_s3_key)

            # Delete KB (cascade will delete items and chunks)
            kb.delete()
            return True
        except Exception as e:
            logger.error(f"Error deleting knowledge base: {e}")
            return False

    def reprocess_item(self, item: KnowledgeItem) -> bool:
        """Reprocess a knowledge item (delete old chunks and regenerate)"""
        # Delete existing chunks
        item.chunks.all().delete()

        # Reset status
        item.processing_status = 'pending'
        item.chunk_count = 0
        item.token_count = 0
        item.embedding_cost = 0.0
        item.processing_error = ''
        item.save()

        # Process again
        return self.process_item(item)
