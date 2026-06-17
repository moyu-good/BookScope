from bookscope.store.embedding_provider import (
    EmbeddingProvider,
    SiliconFlowProvider,
    get_embedding_provider,
)
from bookscope.store.repository import AnalysisResult, Repository
from bookscope.store.supabase_repository import SupabaseRepository

try:
    from bookscope.store.vector_store import SessionVectorStore
except ImportError:
    SessionVectorStore = None  # type: ignore[assignment,misc]

__all__ = [
    "AnalysisResult",
    "EmbeddingProvider",
    "Repository",
    "SessionVectorStore",
    "SiliconFlowProvider",
    "SupabaseRepository",
    "get_embedding_provider",
]
