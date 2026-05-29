import datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage

from api import app

SESSION_ID = "12345678-1234-1234-1234-123456789012"


@pytest.fixture
def mock_graph():
    g = MagicMock()
    g.invoke.return_value = {
        "answer": "Here is the answer.",
        "sources": ["setup.md"],
    }
    snapshot = MagicMock()
    snapshot.values = {
        "messages": [
            HumanMessage(content="how do I set up the runner?"),
            AIMessage(content="Here is the answer."),
        ]
    }
    g.get_state.return_value = snapshot
    g.stream.return_value = iter([{"gate": {}}, {"retrieve": {}}, {"generate": {}}])
    return g


@pytest.fixture
def mock_conn():
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchall.return_value = []
    return conn


@pytest.fixture
def client(mock_graph, mock_conn):
    with (
        patch("api.psycopg.connect", return_value=mock_conn),
        patch("api.PostgresSaver", return_value=MagicMock()),
        patch("api.build_graph", return_value=mock_graph),
    ):
        with TestClient(app) as c:
            yield c


@pytest.fixture
def client_no_raise(mock_graph, mock_conn):
    """Client that returns 500 responses instead of re-raising server exceptions."""
    with (
        patch("api.psycopg.connect", return_value=mock_conn),
        patch("api.PostgresSaver", return_value=MagicMock()),
        patch("api.build_graph", return_value=mock_graph),
    ):
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c


class TestHealth:
    def test_ok_when_db_reachable(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "db": "ok"}

    def test_503_when_db_fails(self, client, mock_conn):
        mock_conn.cursor.return_value.__enter__.return_value.execute.side_effect = Exception("DB down")
        resp = client.get("/health")
        assert resp.status_code == 503
        mock_conn.cursor.return_value.__enter__.return_value.execute.side_effect = None


class TestAsk:
    def test_happy_path_returns_answer_and_sources(self, client, mock_graph):
        resp = client.post("/ask", json={"question": "how do I set up the runner?", "session_id": SESSION_ID})
        assert resp.status_code == 200
        data = resp.json()
        assert data["answer"] == "Here is the answer."
        assert data["sources"] == ["setup.md"]
        assert data["session_id"] == SESSION_ID

    def test_graph_is_invoked_with_the_question(self, client, mock_graph):
        client.post("/ask", json={"question": "how do I set up the runner?", "session_id": SESSION_ID})
        mock_graph.invoke.assert_called_once()
        state_arg = mock_graph.invoke.call_args[0][0]
        assert state_arg["question"] == "how do I set up the runner?"

    def test_empty_question_rejected(self, client):
        resp = client.post("/ask", json={"question": "", "session_id": SESSION_ID})
        assert resp.status_code == 422

    def test_question_over_limit_rejected(self, client):
        resp = client.post("/ask", json={"question": "x" * 5001, "session_id": SESSION_ID})
        assert resp.status_code == 422

    def test_invalid_session_id_rejected(self, client):
        resp = client.post("/ask", json={"question": "valid question", "session_id": "not-a-uuid"})
        assert resp.status_code == 422

    def test_llm_failure_returns_500(self, client_no_raise, mock_graph):
        mock_graph.invoke.side_effect = RuntimeError("Ollama unreachable")
        resp = client_no_raise.post("/ask", json={"question": "how do I set up?", "session_id": SESSION_ID})
        assert resp.status_code == 500
        mock_graph.invoke.side_effect = None


class TestListSessions:
    def test_returns_empty_list_when_no_sessions(self, client):
        resp = client.get("/sessions")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_sessions_from_db(self, client, mock_conn):
        ts = datetime.datetime(2024, 6, 1, 12, 0, tzinfo=datetime.timezone.utc)
        mock_conn.cursor.return_value.__enter__.return_value.fetchall.return_value = [
            (SESSION_ID, "how do I set up the runner?", ts),
        ]
        resp = client.get("/sessions")
        assert resp.status_code == 200
        sessions = resp.json()
        assert len(sessions) == 1
        assert sessions[0]["session_id"] == SESSION_ID
        assert sessions[0]["title"] == "how do I set up the runner?"

    def test_pagination_params_accepted(self, client):
        resp = client.get("/sessions?limit=10&offset=20")
        assert resp.status_code == 200

    def test_limit_zero_rejected(self, client):
        resp = client.get("/sessions?limit=0")
        assert resp.status_code == 422

    def test_limit_above_max_rejected(self, client):
        resp = client.get("/sessions?limit=201")
        assert resp.status_code == 422


class TestHistory:
    def test_returns_messages_for_known_session(self, client):
        resp = client.get(f"/sessions/{SESSION_ID}/history")
        assert resp.status_code == 200
        msgs = resp.json()
        assert len(msgs) == 2
        assert msgs[0]["role"] == "human"
        assert msgs[1]["role"] == "ai"

    def test_returns_404_for_unknown_session(self, client, mock_graph):
        mock_graph.get_state.return_value = MagicMock(values={})
        resp = client.get(f"/sessions/{SESSION_ID}/history")
        assert resp.status_code == 404


class TestDeleteSession:
    def test_returns_204(self, client):
        resp = client.delete(f"/sessions/{SESSION_ID}")
        assert resp.status_code == 204

    def test_all_checkpoint_tables_are_cleared(self, client, mock_conn):
        client.delete(f"/sessions/{SESSION_ID}")
        executed = [
            call.args[0]
            for call in mock_conn.cursor.return_value.__enter__.return_value.execute.call_args_list
        ]
        assert any("agent_sessions" in q for q in executed)
        assert any("checkpoints" in q for q in executed)
