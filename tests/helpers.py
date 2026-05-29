from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage


def make_doc(content: str, metadata: dict | None = None) -> Document:
    return Document(page_content=content, metadata=metadata or {})


def make_state(**overrides) -> dict:
    base = {
        "question": "what is the auth flow?",
        "active_question": "what is the auth flow?",
        "docs": [],
        "attempts": 1,
        "answer": "",
        "sources": [],
        "confidence_score": 0.2,
        "gate_result": "proceed",
        "route": "in_scope",
        "grounded": True,
        "messages": [],
    }
    base.update(overrides)
    return base


SAMPLE_HISTORY = [
    HumanMessage(content="how does auth work?"),
    AIMessage(content="Auth uses JWT tokens."),
]
