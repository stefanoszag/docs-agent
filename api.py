from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI, HTTPException
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.postgres import PostgresSaver
from pydantic import BaseModel

from agent import Settings, build_graph


class AskRequest(BaseModel):
    question: str
    session_id: str


class AskResponse(BaseModel):
    answer: str
    session_id: str


class HistoryMessage(BaseModel):
    role: str
    content: str


settings = Settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = psycopg.connect(settings.db_url, autocommit=True)
    checkpointer = PostgresSaver(conn)
    checkpointer.setup()
    app.state.graph = build_graph(settings, checkpointer)
    app.state.conn = conn
    yield
    conn.close()


app = FastAPI(title="docs-agent", lifespan=lifespan)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    config = {"configurable": {"thread_id": req.session_id}}
    result = app.state.graph.invoke(
        {
            "question": req.question,
            "active_question": req.question,
            "docs": [],
            "attempts": 0,
            "answer": "",
            "route": "",
            "messages": [],
        },
        config=config,
    )
    return AskResponse(answer=result["answer"], session_id=req.session_id)


@app.get("/sessions/{session_id}/history", response_model=list[HistoryMessage])
def get_history(session_id: str) -> list[HistoryMessage]:
    config = {"configurable": {"thread_id": session_id}}
    state = app.state.graph.get_state(config)
    if not state or not state.values:
        raise HTTPException(status_code=404, detail="Session not found")
    return [
        HistoryMessage(
            role="human" if isinstance(m, HumanMessage) else "ai",
            content=m.content,
        )
        for m in state.values.get("messages", [])
    ]
