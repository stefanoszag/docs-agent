import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()

import psycopg
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.postgres import PostgresSaver
from pydantic import BaseModel, Field

from agent import Settings, build_graph, initial_state


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=5000)
    session_id: str = Field(pattern=r"^[0-9a-f-]{36}$")


class AskResponse(BaseModel):
    answer: str
    session_id: str


class HistoryMessage(BaseModel):
    role: str
    content: str


class SessionSummary(BaseModel):
    session_id: str
    title: str
    created_at: str


logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

settings = Settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # PGVector needs the SQLAlchemy driver prefix; psycopg3 does not
    pg_url = settings.db_url.replace("postgresql+psycopg2://", "postgresql://")
    conn = psycopg.connect(pg_url, autocommit=True)

    checkpointer = PostgresSaver(conn)
    checkpointer.setup()

    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS agent_sessions (
                session_id TEXT PRIMARY KEY,
                title      TEXT        NOT NULL DEFAULT 'New chat',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)

    app.state.graph = build_graph(settings, checkpointer)
    app.state.conn = conn
    yield
    conn.close()


app = FastAPI(title="docs-agent", lifespan=lifespan)


@app.get("/health")
def health(request: Request) -> dict:
    try:
        with request.app.state.conn.cursor() as cur:
            cur.execute("SELECT 1")
        return {"status": "ok", "db": "ok"}
    except Exception:
        raise HTTPException(status_code=503, detail="Database unavailable")


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    config = {
        "configurable": {"thread_id": req.session_id},
        "metadata": {"session_id": req.session_id, "question": req.question},
        "tags": ["api", settings.llm_provider],
        "run_name": f"ask/{req.session_id[:8]}",
    }
    result = app.state.graph.invoke(initial_state(req.question), config=config)
    with app.state.conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO agent_sessions (session_id, title)
            VALUES (%s, %s)
            ON CONFLICT (session_id) DO NOTHING
            """,
            (req.session_id, req.question[:80]),
        )
    return AskResponse(answer=result["answer"], session_id=req.session_id)


@app.get("/sessions", response_model=list[SessionSummary])
def list_sessions(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[SessionSummary]:
    with app.state.conn.cursor() as cur:
        cur.execute(
            "SELECT session_id, title, created_at FROM agent_sessions ORDER BY created_at DESC LIMIT %s OFFSET %s",
            (limit, offset),
        )
        rows = cur.fetchall()
    return [
        SessionSummary(session_id=r[0], title=r[1], created_at=r[2].isoformat())
        for r in rows
    ]


@app.get("/sessions/{session_id}/history", response_model=list[HistoryMessage])
def get_history(session_id: str) -> list[HistoryMessage]:
    config = {"configurable": {"thread_id": session_id}}
    state = app.state.graph.get_state(config)
    if state is None or not state.values:
        raise HTTPException(status_code=404, detail="Session not found")
    return [
        HistoryMessage(
            role="human" if isinstance(m, HumanMessage) else "ai",
            content=m.content,
        )
        for m in state.values.get("messages", [])
    ]


@app.delete("/sessions/{session_id}", status_code=204)
def delete_session(session_id: str) -> None:
    # The three checkpoint tables are LangGraph internals (PostgresSaver exposes no delete API).
    # If LangGraph renames tables or adds new ones, this will need updating.
    with app.state.conn.cursor() as cur:
        cur.execute("DELETE FROM agent_sessions WHERE session_id = %s", (session_id,))
        cur.execute("DELETE FROM checkpoints WHERE thread_id = %s", (session_id,))
        cur.execute("DELETE FROM checkpoint_blobs WHERE thread_id = %s", (session_id,))
        cur.execute("DELETE FROM checkpoint_writes WHERE thread_id = %s", (session_id,))


# serve the HTML frontend — mounted last so API routes take precedence
app.mount("/", StaticFiles(directory="static", html=True), name="static")
