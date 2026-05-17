# docs-agent

A local RAG-based knowledge agent that answers questions about your project documentation. Drop markdown files into `docs/`, run the ingest script once, then ask questions via the CLI.

Built on LangChain + LangGraph, pgvector, and Ollama — everything runs locally.

## How it works

### Ingest (`ingest.py`)

A one-time setup script that populates the vector database from your markdown files:

1. **Load** — reads all `.md` files recursively from `docs/`
2. **Split** — breaks each document into 1000-character chunks with 200-character overlap so context isn't lost at boundaries
3. **Embed** — sends each chunk to Ollama (`nomic-embed-text`) to produce a vector representation
4. **Store** — writes the chunks and their vectors into Postgres via pgvector

Re-run ingest any time you add or update documents. It clears and repopulates the collection each run.

### Agent (`agent.py`)

A LangGraph state machine with four nodes and conditional routing:

```
User question
    │
    ▼
 classify ──── out_of_scope ──→ "outside scope of documentation"
    │
  in_scope
    │
    ▼
 retrieve  (embed question → vector search → top 4 chunks)
    │
    ├── score < 0.5 ──────────→ generate ──→ answer
    │
    ├── score ≥ 0.5, attempt 1 ──→ rephrase ──→ retrieve (retry)
    │
    └── score ≥ 0.5, attempt 2 ──→ "not enough information"
```

- **classify** — LLM decides whether the question is answerable from the docs before doing any retrieval
- **retrieve** — embeds the current question, queries pgvector for the 4 nearest chunks, returns them with their cosine distance scores
- **confidence gate** — if the best match score is ≥ 0.5 (too distant), it doesn't generate an answer
- **rephrase** — LLM rephrases the question with different keywords to improve retrieval, then retries once
- **generate** — passes retrieved context + original question to the LLM and returns the answer

## Stack

| Component | Tool |
|---|---|
| LLM | Ollama — Llama 3.1 8B |
| Embeddings | Ollama — nomic-embed-text |
| Vector store | pgvector (Postgres) |
| Orchestration | LangChain + LangGraph |
| Infrastructure | Docker Compose |

## Prerequisites

- [Ollama](https://ollama.com) running on your local network with `llama3.1:8b` and `nomic-embed-text` pulled
- [Docker](https://www.docker.com) for Postgres
- [uv](https://github.com/astral-sh/uv) for Python package management

## Setup

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
DB_URL=postgresql://docsagent:docsagent@localhost:5432/docsagent
```

**3. Start Postgres**

```bash
docker compose up -d
```

**4. Add your docs**

Drop markdown files into the `docs/` directory.

**5. Ingest**

```bash
uv run python ingest.py
```

**6. Run the agent**

```bash
uv run python agent.py
```

```
Building LangGraph agent (LLM: llama3.1:8b)...
Ready. Type your question (Ctrl+C to exit)

Q: How does authentication work?

  [confidence] best score: 0.312 (threshold: 0.5)

A: Authentication uses ...
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
| `CONFIDENCE_THRESHOLD` | `0.5` | Cosine distance cutoff (lower = stricter) |
| `CHUNK_SIZE` | `1000` | Characters per chunk (ingest only) |
| `CHUNK_OVERLAP` | `200` | Overlap between chunks (ingest only) |
