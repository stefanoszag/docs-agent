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
                         ┌─────────────────────────────┐
                         │        user question         │
                         └──────────────┬──────────────┘
                                        │
                                        ▼
                                      gate
                                   /    |    \
                              abuse  chitchat  proceed
                                │       │        │
                          firm      friendly   rewrite_query
                         refusal     reply         │
                                               classify
                                             /         \
                                      out_of_scope    in_scope
                                           │               │
                                  "outside scope"       retrieve
                                                    (BM25 + vector → RRF)
                                                    /      |         \
                                               no docs  confident   low confidence
                                                  │    (score <    (score ≥ threshold)
                                                  │    threshold)       │
                                                  │        │        attempts left?
                                                  │      rerank     yes: rephrase ──┐
                                                  │   (cross-encoder)  no: give_up  │
                                                  │        │                        │
                                                  │     generate  ◄─────────────────┘
                                                  │   (LLM + context
                                                  │    + history)
                                                  │        │
                                                  │  grounding_check
                                                  │   (LLM-as-judge)
                                                  │   /          \
                                                  │ not        grounded
                                                  │ grounded      │
                                                  │        ┌──────┘
                                                  ▼        ▼
                                            "not enough   answer
                                            information"
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
| `POST /ask/stream` | SSE stream — node status events then final answer |
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
- Typing indicator while waiting for a response; live status text below the dots shows which graph node is running (gate check, scope classification, retrieval, reranking, generation, grounding verification)
- Source document references displayed below each AI answer
- Enter to send, Shift+Enter for a new line

## Agent behaviour examples

The following screenshots show how the agent handles different types of input.

### Real-time agent status

While processing a question, the UI displays live status updates below the typing indicator showing which graph node is currently running — gate check, scope classification, retrieval, reranking, generation, and grounding verification. This gives the user visibility into what the agent is doing rather than waiting on an opaque loading state.

![Agent state report](readme_files/agent%20state%20report.png)

### Happy path — answering from docs

A question that is in scope and has supporting content in the documentation. The agent retrieves relevant chunks, reranks them, generates an answer, and verifies it is grounded before returning it. Response also contains the reference of the document used to generate the response.

![Happy path](readme_files/happy%20path.png)

### Chitchat — conversational input

A non-question message such as a greeting or a thank-you. The gate node classifies it as `chitchat` and routes it to a short friendly reply, skipping retrieval and generation entirely.

![Chitchat response](readme_files/chitchat%20response.png)

### Abusive input — hardcoded refusal

Offensive or harmful content is caught by the gate node and returned a hardcoded refusal message. No LLM call is made beyond the gate classification itself.

![Abusive response](readme_files/abusive%20response.png)

### Out-of-scope question — scope classifier

A question that is not related to the ingested documentation (e.g. general knowledge). The classify node marks it `out_of_scope` and the agent returns a fixed message without touching the retriever.

![Out of scope response](readme_files/out%20of%20context%20response.png)

### No hallucination — confidence gate and grounding check

A question where the documentation does not contain a specific enough answer. The agent retrieves what it can but either the confidence gate (low vector similarity) or the grounding check (LLM-as-judge) determines that generating an answer would be unreliable, so it declines rather than guessing.

![No hallucination response](readme_files/no%20hallucination%20response%20.png)

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
| `DB_URL` | — | Postgres connection string (required) |
| `LLM_PROVIDER` | `ollama` | Chat model provider: `ollama`, `anthropic`, `openai` |
| `EMBEDDING_PROVIDER` | `ollama` | Embedding provider: `ollama`, `openai` |
| `LLM_MODEL` | `llama3.1:8b` | Model name for the chosen provider |
| `EMBEDDING_MODEL` | `nomic-embed-text` | Embedding model name for the chosen provider |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL (only required for Ollama provider) |
| `RETRIEVER_K` | `4` | Number of chunks to retrieve |
| `CONFIDENCE_THRESHOLD` | `0.5` | Cosine distance cutoff — lower means stricter |
| `CHUNK_SIZE` | `1000` | Characters per chunk (ingest only) |
| `CHUNK_OVERLAP` | `200` | Overlap between chunks (ingest only) |
| `RERANKER_MODEL` | `cross-encoder/ms-marco-MiniLM-L-6-v2` | HuggingFace cross-encoder for re-ranking |
| `HISTORY_WINDOW` | `6` | Number of messages (3 Q&A pairs) passed to prompts |

## Running the eval harness

`eval.py` runs the golden dataset (`evals/golden.json`, 20 question/answer pairs) through the full LangGraph graph and scores three metrics per question:

| Metric | Method | Range |
|---|---|---|
| Groundedness | LLM-as-judge — does the answer match the retrieved chunks? | 0 or 1 |
| Answer relevance | LLM-as-judge — does the answer address the question? | 0 or 1 |
| Retrieval precision | Keyword heuristic — fraction of retrieved chunks containing content words from the expected answer | 0.0–1.0 |

Requires Ollama and Postgres to be running (same as the agent itself).

```bash
uv run python eval.py
```

Results are written to `evals/results.csv` (gitignored) with one row per question and a summary row at the end. Each row also records run metadata — `run_at` (UTC timestamp), `llm_provider`, `llm_model`, and `confidence_threshold` — so results from different model configs are comparable. Pass `--golden` and `--out` to override the default paths.

## Running the tests

72 unit and integration tests cover the agent graph (routing, `rrf_merge`, `format_docs`, prompt templates), the FastAPI endpoints (health, ask, sessions, history, delete), and the eval scoring functions (`score_groundedness`, `score_answer_relevance`, `score_retrieval_precision`). They require no running services (no Ollama, no Postgres).

```bash
uv run pytest
```

For verbose output:

```bash
uv run pytest -v
```

## Known limitations

Limitations of the current implementation and the changes required for a production service.

- **BM25 index held in memory** — `build_graph` loads all document chunks from the DB on every startup to build the BM25 index. Does not scale to large corpora. Production fix: replace `rank-bm25` with Postgres full-text search (`tsvector`/`tsquery`), which runs inside the DB with no in-process memory overhead.

- **Confidence threshold is a hard-coded constant** — `CONFIDENCE_THRESHOLD=0.5` was set by hand. For a production service, this should be calibrated against the eval harness and tracked as a versioned hyperparameter, not a config default.

- **No document-level metadata filtering** — chunks are retrieved from a flat collection with no awareness of source file, section, or recency. A production retriever would attach metadata (filename, last-modified, section heading) and use it to scope or weight results.

- **Checkpoint deletion coupled to LangGraph internals** — `DELETE /sessions/{id}` directly deletes from `checkpoints`, `checkpoint_blobs`, and `checkpoint_writes`. These are `PostgresSaver` implementation details that could change in a library upgrade. Requires a proper delete API on the checkpointer.

- **No API authentication** — all FastAPI endpoints are unauthenticated. A production deployment requires at minimum an API key header or OAuth2.

## Observability (LangSmith)

All LLM calls, graph nodes, and retrieval steps are automatically traced via [LangSmith](https://smith.langchain.com) when the following env vars are set in `.env`:

```env
LANGSMITH_TRACING_V2=true
LANGSMITH_API_KEY=ls__...
LANGSMITH_PROJECT=docs-agent
```

Tracing is opt-in — omit these vars to run with zero telemetry. When enabled, every request to `/ask` produces a full trace in the LangSmith UI showing each graph node (`gate`, `classify`, `retrieve`, `rerank`, `generate`, `grounding_check`), the prompts sent, model responses, latency per node, and routing decisions. Runs are tagged with the LLM provider (`ollama`/`anthropic`/`openai`) and session ID for easy filtering. Eval harness runs are tagged `eval` so they are distinguishable from live API traffic.

## Switching LLM providers

Ollama is the default. To switch, update `.env` and restart the server.
If you change the embedding provider you must also re-run `ingest.py` — vectors
in pgvector are tied to the model that produced them.

**Anthropic (Claude)**
```env
LLM_PROVIDER=anthropic
LLM_MODEL=claude-sonnet-4-6
ANTHROPIC_API_KEY=sk-ant-...
```

**OpenAI**
```env
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o
EMBEDDING_PROVIDER=openai
EMBEDDING_MODEL=text-embedding-3-small
OPENAI_API_KEY=sk-...
```

**Ollama (default)**
```env
LLM_PROVIDER=ollama
LLM_MODEL=llama3.1:8b
OLLAMA_BASE_URL=http://192.168.x.x:11434
```
