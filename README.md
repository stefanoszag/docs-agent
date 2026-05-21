# docs-agent

A local RAG-based knowledge agent that answers questions about your project documentation. Drop markdown files into `docs/`, run the ingest script once, then ask questions via a chat UI or CLI.

Built on LangChain + LangGraph, pgvector, FastAPI, and Ollama — everything runs locally.

## What it does

### Ingest (`ingest.py`)

A one-time setup script that populates the vector database from your markdown files:

1. **Load** — reads all `.md` files recursively from `docs/`
2. **Split** — breaks each document into 1000-character chunks with 200-character overlap
3. **Embed** — sends each chunk to Ollama (`nomic-embed-text`) to produce a vector
4. **Store** — writes chunks and vectors into Postgres via pgvector

Re-run any time you add or update documents. It clears and repopulates the collection each run.

### Agent (`agent.py`)

A LangGraph state machine that handles each question through a pipeline of nodes:

```
User question
    │
    ▼
  gate ──── chitchat ──→ friendly reply
    │
    ├── abuse ──────────→ firm refusal (no LLM)
    │
  proceed
    │
    ▼
 rewrite_query  (rewrite vague follow-ups using conversation history)
    │
    ▼
 classify ──── out_of_scope ──→ "outside scope of documentation"
    │
  in_scope
    │
    ▼
 retrieve  (BM25 + vector search → RRF merge → top chunks)
    │
    ├── score ≥ 0.5, attempt 1 ──→ rephrase ──→ retrieve (retry)
    │
    ├── score ≥ 0.5, attempt 2 ──→ "not enough information"
    │
  confident
    │
    ▼
 rerank  (cross-encoder reorders chunks by relevance)
    │
    ▼
 generate  (retrieved context + conversation history → LLM)
    │
    ▼
 grounding_check ──── not grounded ──→ "not enough information"
    │
  grounded
    │
    ▼
  answer
```

- **gate** — first stop for every message; one LLM call classifies as `proceed`, `chitchat`, or `abuse`
  - *chitchat* (greetings, thanks, small talk) → short friendly reply
  - *abuse* (offensive or harmful content) → hardcoded refusal, no LLM involved
- **rewrite_query** — if conversation history exists, rewrites vague follow-ups ("can you expand on that?") into self-contained retrieval queries; no-op on first turn
- **classify** — LLM decides if the (rewritten) question is answerable from the docs
- **retrieve** — runs BM25 keyword search and vector search in parallel, merges with Reciprocal Rank Fusion; stores raw vector cosine distance as `confidence_score` for the gate check
- **confidence gate** — if best vector score is ≥ 0.5 (too distant), avoids generating; retries with a rephrased query once before giving up
- **rerank** — cross-encoder (`ms-marco-MiniLM-L-6-v2`) rescores and reorders chunks for quality before generation
- **generate** — passes retrieved context + last 3 turns of conversation history to the LLM
- **grounding_check** — LLM-as-judge verifies the answer is supported by the retrieved chunks; discards hallucinated answers

### API (`api.py`)

A FastAPI server that wraps the agent and manages multiple persistent chat sessions:

| Endpoint | Description |
|---|---|
| `GET /` | Chat UI |
| `POST /ask` | Ask a question `{question, session_id}` |
| `GET /sessions` | List all sessions |
| `GET /sessions/{id}/history` | Full message history for a session |
| `DELETE /sessions/{id}` | Delete a session and its checkpoint data |
| `GET /health` | Health check |

Session history is persisted to Postgres via LangGraph's `PostgresSaver` checkpointer. Each session is keyed by a `session_id` UUID, which the browser generates and stores in `localStorage`.

### Frontend (`static/index.html`)

A vanilla JS chat UI served by FastAPI:

- Dark sidebar lists all past sessions, ordered by most recent
- Click any session to restore its full conversation history
- **+ New chat** starts a fresh session
- Hover a session to reveal a delete button
- Typing indicator while waiting for a response
- Enter to send, Shift+Enter for a new line

## Stack

| Component | Tool |
|---|---|
| LLM | Ollama — Llama 3.1 8B |
| Embeddings | Ollama — nomic-embed-text |
| Vector store | pgvector (Postgres) |
| Keyword search | BM25 (rank-bm25) |
| Re-ranking | cross-encoder/ms-marco-MiniLM-L-6-v2 (sentence-transformers) |
| Orchestration | LangChain + LangGraph |
| Session memory | LangGraph PostgresSaver |
| API | FastAPI + uvicorn |
| Infrastructure | Docker Compose |

## Prerequisites

- [Ollama](https://ollama.com) running on your local network with `llama3.1:8b` and `nomic-embed-text` pulled
- [Docker](https://www.docker.com) for Postgres
- [uv](https://github.com/astral-sh/uv) for Python package management

## Running locally

**1. Clone and install dependencies**

```bash
git clone <repo>
cd docs-agent
uv sync
```

**2. Configure environment**

Create a `.env` file:

```env
OLLAMA_BASE_URL=http://<ollama-host>:11434
DB_URL=postgresql+psycopg2://docsagent:docsagent@localhost:5432/docsagent
```

**3. Start Postgres**

```bash
docker compose up -d
```

**4. Add your docs**

Drop markdown files into the `docs/` directory, then ingest them:

```bash
uv run python ingest.py
```

**5. Start the server**

```bash
uv run uvicorn api:app --reload
```

Open [http://localhost:8000](http://localhost:8000).

**CLI (no server needed)**

```bash
uv run python agent.py
```

## Project structure

```
docs-agent/
├── docs/                   # Source markdown documents to ingest
├── static/
│   └── index.html          # Chat UI (vanilla JS, no build step)
├── ingest.py               # Chunk, embed, and store docs into pgvector
├── agent.py                # LangGraph agent (graph, nodes, state)
├── api.py                  # FastAPI app — HTTP endpoints + session management
├── prompts.py              # Prompt templates
├── docker-compose.yml      # Postgres + pgvector
├── pyproject.toml          # Dependencies managed by uv
├── uv.lock                 # Committed to git
├── .env                    # OLLAMA_BASE_URL, DB_URL (never commit)
└── .env.example            # Placeholder values for reference
```

## Configuration

All settings can be overridden via `.env`:

| Variable | Default | Description |
|---|---|---|
| `OLLAMA_BASE_URL` | — | Ollama server URL (required) |
| `DB_URL` | — | Postgres connection string (required) |
| `EMBEDDING_MODEL` | `nomic-embed-text` | Ollama embedding model |
| `LLM_MODEL` | `llama3.1:8b` | Ollama chat model |
| `RETRIEVER_K` | `4` | Number of chunks to retrieve |
| `CONFIDENCE_THRESHOLD` | `0.5` | Cosine distance cutoff — lower means stricter |
| `CHUNK_SIZE` | `1000` | Characters per chunk (ingest only) |
| `CHUNK_OVERLAP` | `200` | Overlap between chunks (ingest only) |
| `RERANKER_MODEL` | `cross-encoder/ms-marco-MiniLM-L-6-v2` | HuggingFace cross-encoder for re-ranking |
| `HISTORY_WINDOW` | `6` | Number of messages (3 Q&A pairs) passed to prompts |
