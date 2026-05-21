from pathlib import Path

from langchain_community.document_loaders import DirectoryLoader, TextLoader
from langchain_community.embeddings import OllamaEmbeddings
from langchain_community.vectorstores import PGVector
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    db_url: str
    embedding_provider: str = "ollama"  # ollama | openai
    embedding_model: str = "nomic-embed-text"
    ollama_base_url: str = "http://localhost:11434"
    docs_dir: str = "docs"
    chunk_size: int = 1000
    chunk_overlap: int = 200
    collection_name: str = "docs"


def load_documents(docs_dir: str) -> list:
    loader = DirectoryLoader(
        docs_dir,
        glob="**/*.md",
        loader_cls=TextLoader,
        loader_kwargs={"encoding": "utf-8"},
        show_progress=True,
    )
    return loader.load()


def split_documents(docs: list, chunk_size: int, chunk_overlap: int) -> list:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    return splitter.split_documents(docs)


def ingest() -> None:
    settings = Settings()

    docs_path = Path(settings.docs_dir)
    if not docs_path.exists() or not any(docs_path.glob("**/*.md")):
        raise FileNotFoundError(f"No markdown files found in '{settings.docs_dir}/'")

    print(f"Loading documents from '{settings.docs_dir}/'...")
    docs = load_documents(settings.docs_dir)
    chunks = split_documents(docs, settings.chunk_size, settings.chunk_overlap)
    print(f"Split {len(docs)} document(s) into {len(chunks)} chunks")

    if settings.embedding_provider == "openai":
        from langchain_openai import OpenAIEmbeddings
        embeddings = OpenAIEmbeddings(model=settings.embedding_model)
    else:
        embeddings = OllamaEmbeddings(
            base_url=settings.ollama_base_url,
            model=settings.embedding_model,
        )

    print(f"Embedding and storing chunks (model: {settings.embedding_model})...")
    PGVector.from_documents(
        documents=chunks,
        embedding=embeddings,
        connection_string=settings.db_url,
        collection_name=settings.collection_name,
        pre_delete_collection=True,
    )

    print(f"Done — {len(chunks)} chunks stored in collection '{settings.collection_name}'")


if __name__ == "__main__":
    ingest()
