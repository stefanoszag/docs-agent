from langchain_community.chat_models import ChatOllama
from langchain_community.embeddings import OllamaEmbeddings
from langchain_community.vectorstores import PGVector
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough
from pydantic_settings import BaseSettings, SettingsConfigDict

from prompts import RAG_PROMPT


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    ollama_base_url: str
    db_url: str
    embedding_model: str = "nomic-embed-text"
    llm_model: str = "llama3.1:8b"
    collection_name: str = "docs"
    retriever_k: int = 4


def format_docs(docs: list) -> str:
    return "\n\n---\n\n".join(doc.page_content for doc in docs)


def build_chain(settings: Settings):
    embeddings = OllamaEmbeddings(
        base_url=settings.ollama_base_url,
        model=settings.embedding_model,
    )
    store = PGVector(
        connection_string=settings.db_url,
        embedding_function=embeddings,
        collection_name=settings.collection_name,
    )
    retriever = store.as_retriever(search_kwargs={"k": settings.retriever_k})

    llm = ChatOllama(
        base_url=settings.ollama_base_url,
        model=settings.llm_model,
    )

    chain = (
        {"context": retriever | format_docs, "question": RunnablePassthrough()}
        | RAG_PROMPT
        | llm
        | StrOutputParser()
    )
    return chain


def main() -> None:
    settings = Settings()
    print(f"Building RAG chain (LLM: {settings.llm_model})...")
    chain = build_chain(settings)
    print("Ready. Type your question (Ctrl+C to exit)\n")

    while True:
        try:
            question = input("Q: ").strip()
            if not question:
                continue
            answer = chain.invoke(question)
            print(f"\nA: {answer}\n")
        except KeyboardInterrupt:
            print("\nBye!")
            break


if __name__ == "__main__":
    main()
