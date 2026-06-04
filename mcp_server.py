import logging
import uuid

import psycopg
from dotenv import load_dotenv
from langchain_community.vectorstores import PGVector
from langgraph.checkpoint.postgres import PostgresSaver
from mcp.server.fastmcp import FastMCP

from agent import Settings, _build_embeddings, build_graph, initial_state

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

mcp = FastMCP("docs-agent")

settings = Settings()
_conn: psycopg.Connection | None = None
_store: PGVector | None = None
_graph = None


def _get_store() -> PGVector:
    """Lazy-init: embeddings + vector store only. No LLM required."""
    global _store
    if _store is not None:
        return _store
    logger.info("Initialising vector store...")
    _store = PGVector(
        connection_string=settings.db_url,
        embedding_function=_build_embeddings(settings),
        collection_name=settings.collection_name,
    )
    logger.info("Vector store ready.")
    return _store


def _get_graph():
    """Lazy-init: full LangGraph pipeline including LLM."""
    global _conn, _graph
    if _graph is not None:
        return _graph

    logger.info("Initialising full agent (first call)...")
    pg_url = settings.db_url.replace("postgresql+psycopg2://", "postgresql://")
    _conn = psycopg.connect(pg_url, autocommit=True)

    checkpointer = PostgresSaver(_conn)
    checkpointer.setup()

    with _conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS agent_sessions (
                session_id TEXT PRIMARY KEY,
                title      TEXT        NOT NULL DEFAULT 'New chat',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)

    _graph = build_graph(settings, checkpointer)
    logger.info("Agent ready.")
    return _graph


@mcp.tool()
def search_docs(query: str, k: int = 5) -> list[dict]:
    """Search the documentation and return raw chunks for you to synthesize.

    Use this when you want Claude to read the source material and answer directly,
    without routing through the local LLM pipeline (no Ollama required for answering).
    Only needs Ollama for the embedding step.
    """
    results = _get_store().similarity_search_with_score(query, k=k)
    return [
        {
            "content": doc.page_content,
            "source": doc.metadata.get("source", "").split("/")[-1],
            "score": round(float(score), 4),
        }
        for doc, score in results
    ]


@mcp.tool()
def ask_agent(question: str, session_id: str = "") -> dict:
    """Ask a question and get a fully synthesized answer from the local LLM pipeline.

    Routes through the full LangGraph agent: classifier → hybrid retrieval → rerank
    → confidence gate → Ollama LLM → grounding check. Requires Ollama to be reachable.
    Pass a session_id to continue an existing conversation.
    """
    graph = _get_graph()
    if not session_id:
        session_id = str(uuid.uuid4())

    config = {
        "configurable": {"thread_id": session_id},
        "tags": ["mcp", settings.llm_provider],
        "run_name": f"mcp/ask/{session_id[:8]}",
    }
    result = graph.invoke(initial_state(question), config=config)

    with _conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO agent_sessions (session_id, title)
            VALUES (%s, %s)
            ON CONFLICT (session_id) DO NOTHING
            """,
            (session_id, question[:80]),
        )

    return {
        "answer": result["answer"],
        "sources": result.get("sources", []),
        "session_id": session_id,
    }


@mcp.tool()
def list_sessions() -> list[dict]:
    """List the 50 most recent conversation sessions with the docs agent."""
    _get_graph()  # ensure connection is open
    with _conn.cursor() as cur:
        cur.execute(
            "SELECT session_id, title, created_at FROM agent_sessions ORDER BY created_at DESC LIMIT 50"
        )
        rows = cur.fetchall()
    return [
        {"session_id": r[0], "title": r[1], "created_at": r[2].isoformat()}
        for r in rows
    ]


if __name__ == "__main__":
    mcp.run()
