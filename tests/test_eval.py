import pytest
from langchain_core.documents import Document
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from eval import score_answer_relevance, score_groundedness, score_retrieval_precision

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_doc(content: str) -> tuple[Document, float]:
    return (Document(page_content=content), 1.0)


def mock_llm(response: str) -> RunnableLambda:
    """Return a LangChain-compatible runnable that always outputs `response`.

    Uses RunnableLambda so it composes correctly with LCEL (PROMPT | llm | parser)
    without needing a real LLM or network call.
    """
    return RunnableLambda(lambda _: AIMessage(content=response))


# ---------------------------------------------------------------------------
# score_groundedness
# ---------------------------------------------------------------------------

class TestScoreGroundedness:
    def _score(self, llm_output: str, docs=None, answer="some answer") -> int:
        if docs is None:
            docs = [make_doc("relevant context")]
        llm = mock_llm(llm_output)
        return score_groundedness(llm, docs, answer)

    def test_grounded_returns_1(self):
        assert self._score("grounded") == 1

    def test_not_grounded_underscore_returns_0(self):
        assert self._score("not_grounded") == 0

    def test_not_grounded_space_returns_0(self):
        # Bug fixed: LLM uses natural language instead of underscore format
        assert self._score("not grounded") == 0

    def test_unknown_llm_output_defaults_to_0(self):
        # Conservative: unknown response should not be counted as grounded
        assert self._score("I cannot determine this") == 0

    def test_empty_answer_returns_0(self):
        llm = mock_llm("grounded")
        assert score_groundedness(llm, [make_doc("ctx")], "") == 0

    def test_empty_docs_returns_0(self):
        llm = mock_llm("grounded")
        assert score_groundedness(llm, [], "some answer") == 0


# ---------------------------------------------------------------------------
# score_answer_relevance
# ---------------------------------------------------------------------------

class TestScoreAnswerRelevance:
    def _score(self, llm_output: str, answer="some answer") -> int:
        llm = mock_llm(llm_output)
        return score_answer_relevance(llm, "what is X?", answer)

    def test_relevant_returns_1(self):
        assert self._score("relevant") == 1

    def test_not_relevant_underscore_returns_0(self):
        assert self._score("not_relevant") == 0

    def test_not_relevant_space_returns_0(self):
        # Bug fixed: "not relevant" (space) must not slip through as 1
        assert self._score("not relevant") == 0

    def test_unknown_llm_output_defaults_to_0(self):
        assert self._score("unclear") == 0

    def test_empty_answer_returns_0(self):
        llm = mock_llm("relevant")
        assert score_answer_relevance(llm, "what is X?", "") == 0


# ---------------------------------------------------------------------------
# score_retrieval_precision
# ---------------------------------------------------------------------------

class TestScoreRetrievalPrecision:
    def test_all_docs_contain_keywords_returns_1(self):
        docs = [make_doc("docker container setup"), make_doc("install docker engine")]
        assert score_retrieval_precision(docs, "docker installation setup") == 1.0

    def test_no_docs_contain_keywords_returns_0(self):
        docs = [make_doc("unrelated content here"), make_doc("other stuff entirely")]
        assert score_retrieval_precision(docs, "docker installation") == 0.0

    def test_partial_hit_returns_fraction(self):
        docs = [make_doc("docker setup guide"), make_doc("unrelated content")]
        precision = score_retrieval_precision(docs, "docker setup")
        assert precision == 0.5

    def test_empty_docs_returns_0(self):
        assert score_retrieval_precision([], "any question") == 0.0

    def test_expected_answer_with_only_stopwords_returns_0(self):
        # All words are stop words — no keywords to match
        assert score_retrieval_precision([make_doc("some text")], "the a an is") == 0.0

    def test_short_words_ignored(self):
        # Words under 4 chars are filtered out by _keywords
        docs = [make_doc("some content here")]
        assert score_retrieval_precision(docs, "run the job") == 0.0
