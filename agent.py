from typing import TypedDict

from langchain_community.chat_models import ChatOllama
from langchain_community.embeddings import OllamaEmbeddings
from langchain_community.vectorstores import PGVector
from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langgraph.graph import END, START, StateGraph
from pydantic_settings import BaseSettings, SettingsConfigDict

from prompts import CLASSIFIER_PROMPT, RAG_PROMPT, REPHRASE_PROMPT

MAX_RETRIES = 1


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    ollama_base_url: str
    db_url: str
    embedding_model: str = "nomic-embed-text"
    llm_model: str = "llama3.1:8b"
    collection_name: str = "docs"
    retriever_k: int = 4
    confidence_threshold: float = 0.5


class AgentState(TypedDict):
    question: str         # original, never mutated
    active_question: str  # rephrased on retry
    docs: list[tuple[Document, float]]
    attempts: int
    answer: str
    route: str


def format_docs(docs: list[tuple[Document, float]]) -> str:
    return "\n\n---\n\n".join(doc.page_content for doc, _ in docs)


def build_graph(settings: Settings):
    embeddings = OllamaEmbeddings(
        base_url=settings.ollama_base_url,
        model=settings.embedding_model,
    )
    store = PGVector(
        connection_string=settings.db_url,
        embedding_function=embeddings,
        collection_name=settings.collection_name,
    )
    llm = ChatOllama(
        base_url=settings.ollama_base_url,
        model=settings.llm_model,
    )
    parser = StrOutputParser()

    # --- nodes ---

    def classify(state: AgentState) -> dict:
        result = (CLASSIFIER_PROMPT | llm | parser).invoke({"question": state["question"]})
        route = "in_scope" if "in_scope" in result.strip().lower() else "out_of_scope"
        answer = "" if route == "in_scope" else "This question is outside the scope of the available documentation."
        return {"route": route, "answer": answer}

    def retrieve(state: AgentState) -> dict:
        docs = store.similarity_search_with_score(state["active_question"], k=settings.retriever_k)
        return {"docs": docs, "attempts": state["attempts"] + 1}

    def rephrase(state: AgentState) -> dict:
        rephrased = (REPHRASE_PROMPT | llm | parser).invoke({"question": state["active_question"]}).strip()
        print(f"  [rephrase] '{state['active_question']}' → '{rephrased}'")
        return {"active_question": rephrased}

    def generate(state: AgentState) -> dict:
        answer = (RAG_PROMPT | llm | parser).invoke({
            "context": format_docs(state["docs"]),
            "question": state["question"],
        })
        return {"answer": answer}

    def give_up(_state: AgentState) -> dict:
        return {"answer": "I don't have enough information in the documentation to answer this question reliably."}

    # --- conditional routers ---

    def route_after_classify(state: AgentState) -> str:
        return "retrieve" if state["route"] == "in_scope" else END

    def route_after_retrieve(state: AgentState) -> str:
        if not state["docs"]:
            return "give_up"
        best_score = min(score for _, score in state["docs"])
        print(f"  [confidence] best score: {best_score:.3f} (threshold: {settings.confidence_threshold})")
        if best_score < settings.confidence_threshold:
            return "generate"
        if state["attempts"] <= MAX_RETRIES:
            return "rephrase"
        return "give_up"

    # --- graph ---

    graph = StateGraph(AgentState)
    graph.add_node("classify", classify)
    graph.add_node("retrieve", retrieve)
    graph.add_node("rephrase", rephrase)
    graph.add_node("generate", generate)
    graph.add_node("give_up", give_up)

    graph.add_edge(START, "classify")
    graph.add_conditional_edges("classify", route_after_classify)
    graph.add_conditional_edges("retrieve", route_after_retrieve)
    graph.add_edge("rephrase", "retrieve")
    graph.add_edge("generate", END)
    graph.add_edge("give_up", END)

    return graph.compile()


def main() -> None:
    settings = Settings()
    print(f"Building LangGraph agent (LLM: {settings.llm_model})...")
    graph = build_graph(settings)
    print("Ready. Type your question (Ctrl+C to exit)\n")

    while True:
        try:
            question = input("Q: ").strip()
            if not question:
                continue
            result = graph.invoke({
                "question": question,
                "active_question": question,
                "docs": [],
                "attempts": 0,
                "answer": "",
                "route": "",
            })
            print(f"\nA: {result['answer']}\n")
        except KeyboardInterrupt:
            print("\nBye!")
            break


if __name__ == "__main__":
    main()
