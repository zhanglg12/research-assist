from __future__ import annotations

import logging
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import chromadb
import requests
from chromadb import Documents, EmbeddingFunction, Embeddings
from chromadb.config import Settings

from .config import load_zotero_config


LOG = logging.getLogger(__name__)


@contextmanager
def suppress_stdout():
    with open(os.devnull, "w") as devnull:
        old_stdout = sys.stdout
        sys.stdout = devnull
        try:
            yield
        finally:
            sys.stdout = old_stdout


class OpenAIEmbeddingFunction(EmbeddingFunction):
    """OpenAI-compatible embedding backend (remote, not local)."""

    def __init__(self, model_name: str = "text-embedding-3-small", api_key: str | None = None, base_url: str | None = None):
        self.model_name = model_name
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.base_url = base_url or os.getenv("OPENAI_BASE_URL")
        if not self.api_key:
            raise ValueError("OpenAI API key is required")
        try:
            import openai
        except ImportError as exc:
            raise ImportError("openai package is required for OpenAI embeddings") from exc
        client_kwargs: dict[str, Any] = {"api_key": self.api_key}
        if self.base_url:
            client_kwargs["base_url"] = self.base_url
        self.client = openai.OpenAI(**client_kwargs)

    def __call__(self, input: Documents) -> Embeddings:
        response = self.client.embeddings.create(model=self.model_name, input=input)
        return [data.embedding for data in response.data]

    # chromadb may call `EmbeddingFunction.name()` as an unbound method when
    # serializing legacy configs. Accept being called with no `self`.
    def name(self=None) -> str:  # type: ignore[override]
        if self is None:
            return "openai"
        base = self.base_url or "default"
        return f"openai:{self.model_name}:{base}"

    def get_config(self) -> dict[str, Any]:
        return {"model_name": self.model_name, "base_url": self.base_url}

    @classmethod
    def build_from_config(cls, config: dict[str, Any]) -> "OpenAIEmbeddingFunction":
        return cls(
            model_name=str(config.get("model_name") or "text-embedding-3-small"),
            base_url=config.get("base_url"),
        )


class OllamaEmbeddingFunction(EmbeddingFunction):
    """Local Ollama embedding backend with automatic endpoint detection.

    Tries OpenAI-compatible ``/v1/embeddings`` first; falls back to the
    native ``/api/embeddings`` endpoint when the /v1 call fails.
    """

    def __init__(self, model_name: str = "qwen3-embedding:0.6b", api_key: str | None = None, base_url: str | None = None):
        self.model_name = model_name
        self.api_key = api_key or os.getenv("OLLAMA_API_KEY") or "ollama"
        self.base_url = (base_url or os.getenv("OLLAMA_BASE_URL") or "http://localhost:11434/v1").rstrip("/")
        self._use_native: bool | None = None  # None = not yet probed

    def _call_v1(self, input: Documents) -> Embeddings:
        """OpenAI-compatible /v1/embeddings."""
        url = f"{self.base_url}/embeddings"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        response = requests.post(
            url,
            json={"model": self.model_name, "input": list(input)},
            headers=headers,
            timeout=120,
            proxies={"http": None, "https": None},
        )
        response.raise_for_status()
        payload = response.json()
        records = payload.get("data")
        if not isinstance(records, list):
            raise ValueError("Ollama embedding response missing 'data' list")
        embeddings = [record.get("embedding") for record in records]
        if any(not isinstance(embedding, list) for embedding in embeddings):
            raise ValueError("Ollama embedding response missing embedding vectors")
        return embeddings

    def _call_native(self, input: Documents) -> Embeddings:
        """Native Ollama /api/embeddings (one prompt at a time)."""
        # Derive the Ollama root from base_url by stripping /v1 suffix.
        root = self.base_url
        if root.endswith("/v1"):
            root = root[:-3]
        url = f"{root}/api/embed"
        embeddings: Embeddings = []
        for text in input:
            response = requests.post(
                url,
                json={"model": self.model_name, "input": text},
                timeout=120,
                proxies={"http": None, "https": None},
            )
            response.raise_for_status()
            payload = response.json()
            vecs = payload.get("embeddings")
            if isinstance(vecs, list) and len(vecs) > 0:
                embeddings.append(vecs[0])
            else:
                raise ValueError(f"Unexpected native Ollama response: {list(payload.keys())}")
        return embeddings

    def __call__(self, input: Documents) -> Embeddings:
        if self._use_native is True:
            return self._call_native(input)
        if self._use_native is False:
            return self._call_v1(input)
        # First call — probe /v1 then fallback to native
        try:
            result = self._call_v1(input)
            self._use_native = False
            return result
        except Exception as v1_err:
            LOG.warning("Ollama /v1/embeddings failed (%s), trying native /api/embed", v1_err)
            try:
                result = self._call_native(input)
                self._use_native = True
                LOG.info("Using native Ollama /api/embed endpoint")
                return result
            except Exception as native_err:
                raise RuntimeError(
                    f"Both Ollama endpoints failed.\n"
                    f"  /v1/embeddings: {v1_err}\n"
                    f"  /api/embed: {native_err}"
                ) from native_err

    def name(self=None) -> str:  # type: ignore[override]
        if self is None:
            return "ollama"
        return f"ollama:{self.model_name}:{self.base_url}"

    def get_config(self) -> dict[str, Any]:
        return {"model_name": self.model_name, "base_url": self.base_url}

    @classmethod
    def build_from_config(cls, config: dict[str, Any]) -> "OllamaEmbeddingFunction":
        return cls(
            model_name=str(config.get("model_name") or "qwen3-embedding:0.6b"),
            api_key=config.get("api_key"),
            base_url=config.get("base_url"),
        )


class GeminiEmbeddingFunction(EmbeddingFunction):
    """Gemini embedding backend (remote, not local)."""

    def __init__(self, model_name: str = "gemini-embedding-001", api_key: str | None = None, base_url: str | None = None):
        self.model_name = model_name
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        self.base_url = base_url or os.getenv("GEMINI_BASE_URL")
        if not self.api_key:
            raise ValueError("Gemini API key is required")
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise ImportError("google-genai package is required for Gemini embeddings") from exc

        client_kwargs: dict[str, Any] = {"api_key": self.api_key}
        if self.base_url:
            client_kwargs["http_options"] = types.HttpOptions(baseUrl=self.base_url)
        self.client = genai.Client(**client_kwargs)
        self.types = types

    def __call__(self, input: Documents) -> Embeddings:
        embeddings = []
        for text in input:
            response = self.client.models.embed_content(
                model=self.model_name,
                contents=[text],
                config=self.types.EmbedContentConfig(
                    task_type="retrieval_document",
                    title="Zotero library document",
                ),
            )
            embeddings.append(response.embeddings[0].values)
        return embeddings

    def name(self=None) -> str:  # type: ignore[override]
        if self is None:
            return "gemini"
        base = self.base_url or "default"
        return f"gemini:{self.model_name}:{base}"

    def get_config(self) -> dict[str, Any]:
        return {"model_name": self.model_name, "base_url": self.base_url}

    @classmethod
    def build_from_config(cls, config: dict[str, Any]) -> "GeminiEmbeddingFunction":
        return cls(
            model_name=str(config.get("model_name") or "gemini-embedding-001"),
            base_url=config.get("base_url"),
        )


class HuggingFaceEmbeddingFunction(EmbeddingFunction):
    """Local embedding backend via sentence-transformers."""

    def __init__(self, model_name: str = "Qwen/Qwen3-Embedding-0.6B"):
        self.model_name = model_name
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise ImportError(
                "sentence-transformers is required for local embeddings. "
                "Install the optional extra: `uv sync --extra semantic-local`."
            ) from exc
        LOG.info("Loading embedding model: %s", model_name)
        self.model = SentenceTransformer(model_name, trust_remote_code=True)

    def __call__(self, input: Documents) -> Embeddings:
        embeddings = self.model.encode(list(input), convert_to_numpy=True)
        return embeddings.tolist()

    def name(self=None) -> str:  # type: ignore[override]
        if self is None:
            return "sentence-transformers"
        return f"sentence-transformers:{self.model_name}"

    def get_config(self) -> dict[str, Any]:
        return {"model_name": self.model_name}

    @classmethod
    def build_from_config(cls, config: dict[str, Any]) -> "HuggingFaceEmbeddingFunction":
        return cls(model_name=str(config.get("model_name") or "Qwen/Qwen3-Embedding-0.6B"))


class FastEmbedEmbeddingFunction(EmbeddingFunction):
    """Lightweight local embedding backend via fastembed."""

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5"):
        self.model_name = model_name
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:
            raise ImportError(
                "fastembed is required for the fast local embedding backend. "
                "Install with: `uv sync --extra semantic-fastembed`."
            ) from exc
        LOG.info("Loading fastembed model: %s", model_name)
        self.model = TextEmbedding(model_name=model_name)

    def __call__(self, input: Documents) -> Embeddings:
        return [embedding.tolist() for embedding in self.model.embed(list(input))]

    def name(self=None) -> str:  # type: ignore[override]
        if self is None:
            return "fastembed"
        return f"fastembed:{self.model_name}"

    def get_config(self) -> dict[str, Any]:
        return {"model_name": self.model_name}

    @classmethod
    def build_from_config(cls, config: dict[str, Any]) -> "FastEmbedEmbeddingFunction":
        return cls(model_name=str(config.get("model_name") or "BAAI/bge-small-en-v1.5"))


class ChromaClient:
    def __init__(
        self,
        *,
        collection_name: str,
        persist_directory: str,
        embedding_model: str = "default",
        embedding_config: dict[str, Any] | None = None,
    ):
        self.collection_name = collection_name
        self.embedding_model = embedding_model
        self.embedding_config = embedding_config or {}
        self.persist_directory = persist_directory

        with suppress_stdout():
            self.client = chromadb.PersistentClient(
                path=self.persist_directory,
                settings=Settings(anonymized_telemetry=False, allow_reset=True),
            )
            self.embedding_function = self._create_embedding_function()
            try:
                self.collection = self.client.get_or_create_collection(
                    name=self.collection_name,
                    embedding_function=self.embedding_function,
                )
            except Exception as exc:
                if "embedding function conflict" in str(exc).lower():
                    LOG.warning(
                        "Embedding model changed to '%s'; resetting collection for rebuild.",
                        self.embedding_model,
                    )
                    self.client.delete_collection(name=self.collection_name)
                    self.collection = self.client.create_collection(
                        name=self.collection_name,
                        embedding_function=self.embedding_function,
                    )
                else:
                    raise

    def _create_embedding_function(self) -> EmbeddingFunction:
        if self.embedding_model == "openai":
            model_name = self.embedding_config.get("model_name", "text-embedding-3-small")
            api_key = self.embedding_config.get("api_key")
            base_url = self.embedding_config.get("base_url")
            return OpenAIEmbeddingFunction(model_name=model_name, api_key=api_key, base_url=base_url)
        if self.embedding_model == "gemini":
            model_name = self.embedding_config.get("model_name", "gemini-embedding-001")
            api_key = self.embedding_config.get("api_key")
            base_url = self.embedding_config.get("base_url")
            return GeminiEmbeddingFunction(model_name=model_name, api_key=api_key, base_url=base_url)
        if self.embedding_model == "qwen":
            model_name = self.embedding_config.get("model_name", "qwen3-embedding:0.6b")
            api_key = self.embedding_config.get("api_key", "ollama")
            base_url = self.embedding_config.get("base_url", "http://localhost:11434/v1")
            return OllamaEmbeddingFunction(model_name=model_name, api_key=api_key, base_url=base_url)
        if self.embedding_model == "embeddinggemma":
            model_name = self.embedding_config.get("model_name", "google/embeddinggemma-300m")
            return HuggingFaceEmbeddingFunction(model_name=model_name)
        if self.embedding_model == "fastembed":
            model_name = self.embedding_config.get("model_name", "BAAI/bge-small-en-v1.5")
            return FastEmbedEmbeddingFunction(model_name=model_name)
        if self.embedding_model not in {"default", "openai", "gemini"}:
            return HuggingFaceEmbeddingFunction(model_name=self.embedding_model)
        return chromadb.utils.embedding_functions.DefaultEmbeddingFunction()

    def upsert_documents(self, *, documents: list[str], metadatas: list[dict[str, Any]], ids: list[str]) -> None:
        self.collection.upsert(documents=documents, metadatas=metadatas, ids=ids)

    def search(self, *, query_texts: list[str], n_results: int = 10, where: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.collection.query(query_texts=query_texts, n_results=n_results, where=where)

    def get_collection_info(self) -> dict[str, Any]:
        try:
            count = self.collection.count()
        except Exception as exc:
            return {
                "name": self.collection_name,
                "count": 0,
                "embedding_model": self.embedding_model,
                "persist_directory": self.persist_directory,
                "error": str(exc),
            }
        return {
            "name": self.collection_name,
            "count": count,
            "embedding_model": self.embedding_model,
            "persist_directory": self.persist_directory,
        }

    def reset_collection(self) -> None:
        self.client.delete_collection(name=self.collection_name)
        self.collection = self.client.create_collection(
            name=self.collection_name,
            embedding_function=self.embedding_function,
        )

    def get_document_metadata(self, doc_id: str) -> dict[str, Any] | None:
        try:
            result = self.collection.get(ids=[doc_id], include=["metadatas"])
            if result.get("ids") and result.get("metadatas"):
                return (result["metadatas"] or [None])[0]
        except Exception:
            return None
        return None


def create_chroma_client(config_path: str | Path | None = None) -> ChromaClient:
    cfg = load_zotero_config(config_path)
    persist_directory = cfg.semantic_persist_directory
    persist_directory.mkdir(parents=True, exist_ok=True)

    embedding_model = cfg.semantic_embedding_model
    # Start from config-file embedding_config, then overlay env-var overrides.
    embedding_config: dict[str, Any] = dict(cfg.semantic_embedding_config)
    if embedding_model == "openai":
        if os.getenv("OPENAI_API_KEY"):
            embedding_config["api_key"] = os.getenv("OPENAI_API_KEY")
        if os.getenv("OPENAI_BASE_URL"):
            embedding_config["base_url"] = os.getenv("OPENAI_BASE_URL")
        if os.getenv("OPENAI_EMBEDDING_MODEL"):
            embedding_config["model_name"] = os.getenv("OPENAI_EMBEDDING_MODEL")
    if embedding_model == "gemini":
        if os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"):
            embedding_config["api_key"] = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if os.getenv("GEMINI_BASE_URL"):
            embedding_config["base_url"] = os.getenv("GEMINI_BASE_URL")
        if os.getenv("GEMINI_EMBEDDING_MODEL"):
            embedding_config["model_name"] = os.getenv("GEMINI_EMBEDDING_MODEL")
    if embedding_model == "qwen":
        if os.getenv("OLLAMA_BASE_URL"):
            embedding_config["base_url"] = os.getenv("OLLAMA_BASE_URL")
        if os.getenv("OLLAMA_EMBEDDING_MODEL"):
            embedding_config["model_name"] = os.getenv("OLLAMA_EMBEDDING_MODEL")
        if os.getenv("OLLAMA_API_KEY"):
            embedding_config["api_key"] = os.getenv("OLLAMA_API_KEY")
    if embedding_model == "fastembed":
        if os.getenv("FASTEMBED_MODEL"):
            embedding_config["model_name"] = os.getenv("FASTEMBED_MODEL")

    return ChromaClient(
        collection_name=cfg.semantic_collection_name,
        persist_directory=persist_directory.as_posix(),
        embedding_model=embedding_model,
        embedding_config=embedding_config,
    )
