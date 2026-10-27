"""
Lightweight RAG + preference stack.

This package is self-contained and does not touch existing rag modules.
"""

from pathlib import Path

# Default storage locations; can be overridden per call.
DEFAULT_STORE_DIR = Path("rag_store")
DEFAULT_DB_PATH = DEFAULT_STORE_DIR / "clips.db"
DEFAULT_FAISS_INDEX_PATH = DEFAULT_STORE_DIR / "faiss.index"
DEFAULT_ID_MAP_PATH = DEFAULT_STORE_DIR / "id_map.npy"
DEFAULT_EMB_CACHE_PATH = DEFAULT_STORE_DIR / "embeddings.npy"
