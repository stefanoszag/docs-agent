from agent import format_docs, rrf_merge
from tests.helpers import make_doc


class TestRrfMerge:
    def test_vector_only_preserves_rank_order(self):
        docs = [(make_doc("a"), 0.1), (make_doc("b"), 0.3), (make_doc("c"), 0.8)]
        result = rrf_merge(docs, [])
        assert [d.page_content for d, _ in result] == ["a", "b", "c"]

    def test_bm25_only_preserves_rank_order(self):
        docs = [make_doc("a"), make_doc("b"), make_doc("c")]
        result = rrf_merge([], docs)
        assert [d.page_content for d, _ in result] == ["a", "b", "c"]

    def test_overlap_scores_higher_than_single_source(self):
        shared = make_doc("shared")
        result = rrf_merge(
            [(shared, 0.3), (make_doc("vector_only"), 0.1)],
            [shared, make_doc("bm25_only")],
        )
        assert result[0][0].page_content == "shared"

    def test_overlap_doc_appears_once(self):
        shared = make_doc("shared")
        result = rrf_merge([(shared, 0.1)], [shared])
        contents = [d.page_content for d, _ in result]
        assert contents.count("shared") == 1

    def test_empty_both_returns_empty(self):
        assert rrf_merge([], []) == []

    def test_empty_vector_returns_bm25_results(self):
        result = rrf_merge([], [make_doc("a"), make_doc("b")])
        assert len(result) == 2

    def test_empty_bm25_returns_vector_results(self):
        result = rrf_merge([(make_doc("a"), 0.1), (make_doc("b"), 0.2)], [])
        assert len(result) == 2

    def test_scores_are_positive(self):
        docs = [(make_doc("a"), 0.1), (make_doc("b"), 0.5)]
        result = rrf_merge(docs, [make_doc("c")])
        assert all(score > 0 for _, score in result)


class TestFormatDocs:
    def test_single_doc(self):
        assert format_docs([(make_doc("hello"), 0.1)]) == "hello"

    def test_multiple_docs_joined_with_separator(self):
        result = format_docs([(make_doc("first"), 0.1), (make_doc("second"), 0.2)])
        assert "first" in result
        assert "second" in result
        assert "---" in result

    def test_scores_are_ignored(self):
        result = format_docs([(make_doc("content"), 0.99)])
        assert result == "content"

    def test_empty_returns_empty_string(self):
        assert format_docs([]) == ""
