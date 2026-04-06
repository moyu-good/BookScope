from bookscope.store.embedding_provider import (
    BgeM3LocalProvider,
    EmbeddingProvider,
    Qwen3LocalProvider,
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
    "BgeM3LocalProvider",
    "EmbeddingProvider",
    "Qwen3LocalProvider",
    "Repository",
    "SessionVectorStore",
    "SiliconFlowProvider",
    "SupabaseRepository",
    "get_embedding_provider",
]
