import logging
from typing import Annotated, TypedDict

import psycopg2
from langchain_community.chat_models import ChatOllama
from langchain_community.embeddings import OllamaEmbeddings
from langchain_community.retrievers import BM25Retriever
from langchain_core.language_models import BaseChatModel
from langchain_core.embeddings import Embeddings
from langchain_community.vectorstores import PGVector
from langchain_core.documents import Document
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from langchain_core.output_parsers import StrOutputParser
from langgraph.graph import END, START, StateGraph
from langgraph.graph import add_messages
from pydantic_settings import BaseSettings, SettingsConfigDict
from sentence_transformers import CrossEncoder

from prompts import (
    CHITCHAT_PROMPT,
    CLASSIFIER_PROMPT,
    GATE_PROMPT,
    GROUNDING_PROMPT,
    QUERY_REWRITE_PROMPT,
    RAG_PROMPT,
    REPHRASE_PROMPT,
)

logger = logging.getLogger(__name__)

MAX_RETRIES = 1
RRF_K = 60


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    db_url: str
    llm_provider: str = "ollama"        # ollama | anthropic | openai
    embedding_provider: str = "ollama"  # ollama | openai
    llm_model: str = "llama3.1:8b"
    embedding_model: str = "nomic-embed-text"
    ollama_base_url: str = "http://localhost:11434"  # only required for ollama provider
    collection_name: str = "docs"
    retriever_k: int = 4
    confidence_threshold: float = 0.5
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    history_window: int = 6  # number of messages (3 Q&A pairs) passed to prompts


def _build_llm(settings: Settings) -> BaseChatModel:
    if settings.llm_provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model=settings.llm_model)
    if settings.llm_provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=settings.llm_model)
    return ChatOllama(base_url=settings.ollama_base_url, model=settings.llm_model)


def _build_embeddings(settings: Settings) -> Embeddings:
    if settings.embedding_provider == "openai":
        from langchain_openai import OpenAIEmbeddings
        return OpenAIEmbeddings(model=settings.embedding_model)
    return OllamaEmbeddings(base_url=settings.ollama_base_url, model=settings.embedding_model)


class AgentState(TypedDict):
    question: str           # original, never mutated
    active_question: str    # rewritten for retrieval (follow-up rewrite or rephrase)
    docs: list[tuple[Document, float]]
    attempts: int
    answer: str
    sources: list[str]      # unique source filenames that backed the answer
    confidence_score: float  # best raw vector cosine distance (lower = more confident)
    gate_result: str         # "proceed" | "chitchat" | "abuse"
    route: str               # "in_scope" | "out_of_scope" (set by classify)
    grounded: bool           # grounding check result
    messages: Annotated[list[AnyMessage], add_messages]


def format_docs(docs: list[tuple[Document, float]]) -> str:
    return "\n\n---\n\n".join(doc.page_content for doc, _ in docs)


def initial_state(question: str) -> dict:
    """Return a fresh AgentState dict for a new question."""
    return {
        "question": question,
        "active_question": question,
        "docs": [],
        "attempts": 0,
        "answer": "",
        "sources": [],
        "confidence_score": 0.0,
        "gate_result": "",
        "route": "",
        "grounded": True,
        "messages": [],
    }


def load_all_documents(db_url: str, collection_name: str) -> list[Document]:
    pg_url = db_url.replace("postgresql+psycopg2://", "postgresql://")
    conn = psycopg2.connect(pg_url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT e.document, e.cmetadata
                FROM langchain_pg_embedding e
                JOIN langchain_pg_collection c ON e.collection_id = c.uuid
                WHERE c.name = %s
                """,
                (collection_name,),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return [Document(page_content=row[0], metadata=row[1] or {}) for row in rows]


def rrf_merge(
    vector_results: list[tuple[Document, float]],
    bm25_docs: list[Document],
    k: int = RRF_K,
) -> list[tuple[Document, float]]:
    scores: dict[str, dict] = {}
    for rank, (doc, _) in enumerate(vector_results):
        key = doc.page_content
        if key not in scores:
            scores[key] = {"doc": doc, "score": 0.0}
        scores[key]["score"] += 1 / (k + rank + 1)
    for rank, doc in enumerate(bm25_docs):
        key = doc.page_content
        if key not in scores:
            scores[key] = {"doc": doc, "score": 0.0}
        scores[key]["score"] += 1 / (k + rank + 1)
    merged = sorted(scores.values(), key=lambda x: x["score"], reverse=True)
    return [(item["doc"], item["score"]) for item in merged]


# --- conditional routers (module-level so they can be unit-tested) ---

def route_after_gate(state: AgentState) -> str:
    gr = state["gate_result"]
    if gr == "abuse":
        return "respond_guardrail"
    if gr == "chitchat":
        return "respond_chitchat"
    return "rewrite_query"


def route_after_classify(state: AgentState) -> str:
    return "retrieve" if state["route"] == "in_scope" else END


def route_after_retrieve(state: AgentState, confidence_threshold: float) -> str:
    if not state["docs"]:
        return "give_up"
    logger.debug("[confidence] best vector score: %.3f (threshold: %.3f)", state["confidence_score"], confidence_threshold)
    # confidence_score is cosine distance: lower = more similar = more confident.
    # < threshold means a close match was found → rerank for quality then generate.
    # >= threshold means poor retrieval → rephrase and retry.
    if state["confidence_score"] < confidence_threshold:
        return "rerank"
    if state["attempts"] <= MAX_RETRIES:
        return "rephrase"
    return "give_up"


def route_after_grounding(state: AgentState) -> str:
    return END if state["grounded"] else "give_up"


def build_graph(settings: Settings, checkpointer=None):
    embeddings = _build_embeddings(settings)
    store = PGVector(
        connection_string=settings.db_url,
        embedding_function=embeddings,
        collection_name=settings.collection_name,
    )
    llm = _build_llm(settings)
    parser = StrOutputParser()

    logger.info("Loading documents for BM25 index...")
    all_docs = load_all_documents(settings.db_url, settings.collection_name)
    bm25 = BM25Retriever.from_documents(all_docs, k=settings.retriever_k)
    logger.info("BM25 index built from %d chunks.", len(all_docs))

    logger.info("Loading reranker (%s)...", settings.reranker_model)
    reranker = CrossEncoder(settings.reranker_model)
    logger.info("Reranker ready.")

    # --- nodes ---

    def gate(state: AgentState) -> dict:
        result = (GATE_PROMPT | llm | parser).invoke({"question": state["question"]}).strip().lower()
        if "abuse" in result:
            gate_result = "abuse"
        elif "chitchat" in result:
            gate_result = "chitchat"
        else:
            gate_result = "proceed"
        return {"gate_result": gate_result}

    def respond_chitchat(state: AgentState) -> dict:
        answer = (CHITCHAT_PROMPT | llm | parser).invoke({"question": state["question"]}).strip()
        return {
            "answer": answer,
            "messages": [HumanMessage(content=state["question"]), AIMessage(content=answer)],
        }

    def respond_guardrail(state: AgentState) -> dict:
        answer = "I'm not able to respond to that. Please keep our conversation respectful."
        return {
            "answer": answer,
            "messages": [HumanMessage(content=state["question"]), AIMessage(content=answer)],
        }

    def rewrite_query(state: AgentState) -> dict:
        history = state["messages"]
        if not history:
            return {"active_question": state["question"]}
        rewritten = (QUERY_REWRITE_PROMPT | llm | parser).invoke({
            "question": state["question"],
            "history": history[-settings.history_window:],
        }).strip()
        if rewritten != state["question"]:
            logger.debug("[rewrite] %r → %r", state["question"], rewritten)
        return {"active_question": rewritten}

    def classify(state: AgentState) -> dict:
        result = (CLASSIFIER_PROMPT | llm | parser).invoke({"question": state["active_question"]})
        route = "in_scope" if "in_scope" in result.strip().lower() else "out_of_scope"
        if route == "out_of_scope":
            answer = "This question is outside the scope of the available documentation."
            return {
                "route": route,
                "answer": answer,
                "messages": [HumanMessage(content=state["question"]), AIMessage(content=answer)],
            }
        return {"route": route, "answer": ""}

    def retrieve(state: AgentState) -> dict:
        query = state["active_question"]
        vector_results = store.similarity_search_with_score(query, k=settings.retriever_k)
        bm25_docs = bm25.invoke(query)
        merged = rrf_merge(vector_results, bm25_docs)
        best_vector_score = min((score for _, score in vector_results), default=1.0)
        return {
            "docs": merged,
            "confidence_score": best_vector_score,
            "attempts": state["attempts"] + 1,
        }

    def rephrase(state: AgentState) -> dict:
        rephrased = (REPHRASE_PROMPT | llm | parser).invoke({"question": state["active_question"]}).strip()
        logger.debug("[rephrase] %r → %r", state["active_question"], rephrased)
        return {"active_question": rephrased}

    def rerank(state: AgentState) -> dict:
        query = state["active_question"]
        docs = [doc for doc, _ in state["docs"]]
        scores = reranker.predict([(query, doc.page_content) for doc in docs])
        ranked = sorted(zip(docs, scores.tolist()), key=lambda x: x[1], reverse=True)
        logger.debug("[rerank] top score: %.3f" if ranked else "[rerank] no docs", ranked[0][1] if ranked else None)
        return {"docs": [(doc, float(score)) for doc, score in ranked]}

    def generate(state: AgentState) -> dict:
        history = state["messages"][-settings.history_window:]
        answer = (RAG_PROMPT | llm | parser).invoke({
            "context": format_docs(state["docs"]),
            "question": state["question"],
            "history": history,
        })
        sources = list(dict.fromkeys(
            doc.metadata["source"].split("/")[-1]
            for doc, _ in state["docs"]
            if doc.metadata.get("source")
        ))
        return {
            "answer": answer,
            "sources": sources,
            "messages": [HumanMessage(content=state["question"]), AIMessage(content=answer)],
        }

    def grounding_check(state: AgentState) -> dict:
        result = (GROUNDING_PROMPT | llm | parser).invoke({
            "context": format_docs(state["docs"]),
            "answer": state["answer"],
        }).strip().lower()
        grounded = "not_grounded" not in result
        logger.debug("[grounding] %s", "grounded" if grounded else "NOT grounded")
        return {"grounded": grounded}

    def give_up(state: AgentState) -> dict:
        answer = "I don't have enough information in the documentation to answer this question reliably."
        return {
            "answer": answer,
            "messages": [HumanMessage(content=state["question"]), AIMessage(content=answer)],
        }

    # --- graph ---

    graph = StateGraph(AgentState)
    graph.add_node("gate", gate)
    graph.add_node("respond_chitchat", respond_chitchat)
    graph.add_node("respond_guardrail", respond_guardrail)
    graph.add_node("rewrite_query", rewrite_query)
    graph.add_node("classify", classify)
    graph.add_node("retrieve", retrieve)
    graph.add_node("rephrase", rephrase)
    graph.add_node("rerank", rerank)
    graph.add_node("generate", generate)
    graph.add_node("grounding_check", grounding_check)
    graph.add_node("give_up", give_up)

    graph.add_edge(START, "gate")
    graph.add_conditional_edges("gate", route_after_gate)
    graph.add_edge("respond_chitchat", END)
    graph.add_edge("respond_guardrail", END)
    graph.add_edge("rewrite_query", "classify")
    graph.add_conditional_edges("classify", route_after_classify)
    graph.add_conditional_edges("retrieve", lambda s: route_after_retrieve(s, settings.confidence_threshold))
    graph.add_edge("rephrase", "retrieve")
    graph.add_edge("rerank", "generate")
    graph.add_edge("generate", "grounding_check")
    graph.add_conditional_edges("grounding_check", route_after_grounding)
    graph.add_edge("give_up", END)

    return graph.compile(checkpointer=checkpointer)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    settings = Settings()
    logger.info("Building LangGraph agent (LLM: %s via %s)...", settings.llm_model, settings.llm_provider)
    graph = build_graph(settings)
    print("Ready. Type your question (Ctrl+C to exit)\n")

    while True:
        try:
            question = input("Q: ").strip()
            if not question:
                continue
            result = graph.invoke(initial_state(question))
            print(f"\nA: {result['answer']}\n")
        except KeyboardInterrupt:
            print("\nBye!")
            break


if __name__ == "__main__":
    main()
