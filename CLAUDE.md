# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Is
A local RAG-based knowledge agent that answers questions about personal project documentation.
Built to learn LangChain, LangGraph, pgvector, and LLM orchestration patterns before applying
these skills to a production ML team knowledge agent at work.

## Stack
- **Language:** Python
- **Package manager:** uv (not pip, not poetry)
- **LLM:** Ollama (running on M1 MacBook Air on local network)
- **Default model:** Gemma 4 or Llama 3.1 8B (prefer Llama 3.1 8B for agentic tasks)
- **Embedding model:** nomic-embed-text via Ollama
- **Vector store:** pgvector (Postgres extension)
- **Orchestration:** LangChain + LangGraph
- **API layer:** Flask
- **Infrastructure:** Docker Compose (local Postgres + pgvector)

## Ollama Connection
Ollama server runs on a separate machine on the local network.
Store the base URL in .env as OLLAMA_BASE_URL (e.g. http://192.168.x.x:11434).
Never hardcode the IP.

## Project Structure
```
docs-agent/
├── docs/                   # Source markdown documents to ingest
├── ingest.py               # Chunk, embed, and store docs into pgvector
├── agent.py                # Query pipeline / LangGraph agent
├── prompts.py              # Prompt templates (keep separate from logic)
├── docker-compose.yml      # Postgres + pgvector
├── pyproject.toml          # Dependencies managed by uv
├── uv.lock                 # Committed to git
├── .env                    # OLLAMA_BASE_URL, DB_URL etc (never commit)
└── .env.example            # Committed version with placeholder values
```

## Build Phases

### Phase 1 — Basic RAG Pipeline
Goal: end-to-end question answering from docs. No agent logic yet.
- Docker Compose with pgvector running locally
- ingest.py: load markdown files → chunk → embed → store in pgvector
- agent.py: embed query → vector search → pass context + question to LLM → return answer
- Simple CLI interface to test queries
- Key learning: embeddings, vector search, RAG pattern

### Phase 2 — LangGraph Orchestration
Goal: wrap Phase 1 pipeline in a LangGraph graph with basic agent logic.
- Classifier node: is the question answerable from docs or is it out of scope?
- Confidence gate: if retrieval score is low, return "I don't know" rather than hallucinate
- Retry logic: if confidence is low, try rephrasing the query and search again
- Key learning: LangGraph nodes, edges, state management

### Phase 3 — Flask API + Chat History
Goal: make it usable as a proper service.
- Flask endpoint: POST /ask accepts a question, returns an answer
- Conversation memory: maintain chat history within a session
- Optional: basic HTML frontend or CLI with history display
- Key learning: stateful agents, session management

## Coding Conventions
- Python with type hints throughout
- Pydantic for data models and config
- Environment variables via python-dotenv, never hardcoded values
- Keep LLM calls and business logic separate
- Prompts live in prompts.py, not inline in agent.py
- Use LangChain abstractions (ChatOllama, OllamaEmbeddings) so swapping LLM provider
  is a one-line change (Ollama → Claude API → OpenAI)

## Key Commands
```bash
# Add dependencies
uv add langchain langchain-community langgraph pgvector psycopg2-binary python-dotenv pydantic
uv add flask                          # Phase 3 only

# Start local Postgres with pgvector
docker compose up -d

# Ingest documents into pgvector
uv run python ingest.py

# Run the agent (Phase 1: CLI)
uv run python agent.py

# Run Flask API (Phase 3)
uv run flask run
```

Dependencies are managed via pyproject.toml and uv.lock — both committed to git.
Never use pip install directly. Always use uv add.

## Architecture Reference
The work project this is preparing for uses the following architecture (use as inspiration,
not a strict spec for this personal project):
- Vague query → Tier classifier → Query transformation
- Retrieval strategies: Fast path, Hybrid search, Knowledge graph, MCP + episodic
- Rerank + fuse → Confidence gate → LLM synthesis → Slack

This personal project targets: query → vector retrieval → confidence gate → LLM synthesis.
LangGraph is used to orchestrate these steps as a graph.