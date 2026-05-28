"""
eval.py — offline evaluation harness for docs-agent.

Runs the golden dataset through the full LangGraph graph and scores three metrics
per question, then writes results to a CSV with a summary row.

Metrics:
  groundedness        — does the answer match the retrieved chunks?   (0 or 1, LLM-as-judge)
  answer_relevance    — does the answer address the question?         (0 or 1, LLM-as-judge)
  retrieval_precision — fraction of retrieved chunks containing       (0.0–1.0, keyword heuristic)
                        content words from the expected answer

Usage:
    uv run python eval.py
    uv run python eval.py --golden evals/golden.json --out evals/results.csv
"""

import argparse
import csv
import json
import re
import sys
from pathlib import Path

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from agent import Settings, _build_llm, build_graph, initial_state
from prompts import GROUNDING_PROMPT

ANSWER_RELEVANCE_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        "You are an evaluator. Given a question and an answer, decide if the answer "
        "directly and meaningfully addresses the question. "
        "Reply with exactly one word: 'relevant' or 'not_relevant'.",
    ),
    ("human", "Question: {question}\n\nAnswer: {answer}"),
])

_STOP_WORDS = {
    "the", "a", "an", "is", "it", "in", "on", "at", "to", "for", "of",
    "and", "or", "with", "are", "was", "be", "by", "from", "that", "this",
    "its", "as", "if", "not", "no", "but", "so", "can", "will", "also",
    "have", "has", "been", "you", "your", "they", "their", "then", "use",
}

CSV_FIELDS = [
    "question",
    "expected_answer",
    "actual_answer",
    "groundedness",
    "answer_relevance",
    "retrieval_precision",
    "docs_retrieved",
    "confidence_score",
]

def _keywords(text: str) -> set[str]:
    return {
        w.lower()
        for w in re.findall(r"\b\w{4,}\b", text)
        if w.lower() not in _STOP_WORDS
    }


def score_retrieval_precision(docs: list, expected_answer: str) -> float:
    if not docs:
        return 0.0
    keywords = _keywords(expected_answer)
    if not keywords:
        return 0.0
    hits = sum(
        1 for doc, _ in docs
        if any(kw in doc.page_content.lower() for kw in keywords)
    )
    return round(hits / len(docs), 3)


def score_groundedness(llm, docs: list, answer: str) -> int:
    if not docs or not answer:
        return 0
    context = "\n\n---\n\n".join(doc.page_content for doc, _ in docs)
    result = (GROUNDING_PROMPT | llm | StrOutputParser()).invoke({
        "context": context,
        "answer": answer,
    }).strip().lower()
    return 0 if "not_grounded" in result else 1


def score_answer_relevance(llm, question: str, answer: str) -> int:
    if not answer:
        return 0
    result = (ANSWER_RELEVANCE_PROMPT | llm | StrOutputParser()).invoke({
        "question": question,
        "answer": answer,
    }).strip().lower()
    return 1 if "relevant" in result and "not_relevant" not in result else 0


def run_eval(golden_path: Path, out_path: Path) -> None:
    golden = json.loads(golden_path.read_text())
    print(f"Loaded {len(golden)} examples from {golden_path}\n")

    settings = Settings()
    print("Building graph (loads BM25 index and reranker)...")
    graph = build_graph(settings)
    llm = _build_llm(settings)
    print("Ready.\n")

    rows: list[dict] = []

    for i, item in enumerate(golden, 1):
        question = item["question"]
        expected = item["expected_answer"]
        print(f"[{i:02d}/{len(golden)}] {question}")

        result = graph.invoke(initial_state(question), config={"tags": ["eval"]})

        answer = result.get("answer", "")
        docs = result.get("docs", [])
        confidence = result.get("confidence_score", 0.0)

        g = score_groundedness(llm, docs, answer)
        r = score_answer_relevance(llm, question, answer)
        p = score_retrieval_precision(docs, expected)

        print(f"         groundedness={g}  relevance={r}  precision={p:.2f}  docs={len(docs)}  confidence={confidence:.3f}")

        rows.append({
            "question": question,
            "expected_answer": expected,
            "actual_answer": answer,
            "groundedness": g,
            "answer_relevance": r,
            "retrieval_precision": p,
            "docs_retrieved": len(docs),
            "confidence_score": round(confidence, 4),
        })

    n = len(rows)
    summary = {
        "question": "AVERAGE",
        "expected_answer": "",
        "actual_answer": "",
        "groundedness": round(sum(r["groundedness"] for r in rows) / n, 3),
        "answer_relevance": round(sum(r["answer_relevance"] for r in rows) / n, 3),
        "retrieval_precision": round(sum(r["retrieval_precision"] for r in rows) / n, 3),
        "docs_retrieved": round(sum(r["docs_retrieved"] for r in rows) / n, 1),
        "confidence_score": round(sum(r["confidence_score"] for r in rows) / n, 4),
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
        writer.writerow(summary)

    print(f"\n{'='*55}")
    print(f"  Groundedness:        {summary['groundedness']:.1%}")
    print(f"  Answer relevance:    {summary['answer_relevance']:.1%}")
    print(f"  Retrieval precision: {summary['retrieval_precision']:.1%}")
    print(f"{'='*55}")
    print(f"Results written to {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate docs-agent against a golden dataset")
    parser.add_argument("--golden", default="evals/golden.json", type=Path, help="Path to golden Q&A pairs (JSON)")
    parser.add_argument("--out", default="evals/results.csv", type=Path, help="Path to write results CSV")
    args = parser.parse_args()

    if not args.golden.exists():
        print(f"Golden dataset not found: {args.golden}", file=sys.stderr)
        sys.exit(1)

    run_eval(args.golden, args.out)


if __name__ == "__main__":
    main()
