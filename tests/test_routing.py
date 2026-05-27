from langgraph.graph import END

from agent import (
    MAX_RETRIES,
    route_after_classify,
    route_after_gate,
    route_after_grounding,
    route_after_retrieve,
)
from tests.helpers import make_doc, make_state

THRESHOLD = 0.5


class TestRouteAfterGate:
    def test_abuse_routes_to_guardrail(self):
        assert route_after_gate(make_state(gate_result="abuse")) == "respond_guardrail"

    def test_chitchat_routes_to_chitchat(self):
        assert route_after_gate(make_state(gate_result="chitchat")) == "respond_chitchat"

    def test_proceed_routes_to_rewrite(self):
        assert route_after_gate(make_state(gate_result="proceed")) == "rewrite_query"


class TestRouteAfterClassify:
    def test_in_scope_routes_to_retrieve(self):
        assert route_after_classify(make_state(route="in_scope")) == "retrieve"

    def test_out_of_scope_routes_to_end(self):
        assert route_after_classify(make_state(route="out_of_scope")) == END


class TestRouteAfterRetrieve:
    def test_no_docs_gives_up(self):
        state = make_state(docs=[], confidence_score=0.1, attempts=1)
        assert route_after_retrieve(state, THRESHOLD) == "give_up"

    def test_high_confidence_routes_to_rerank(self):
        # distance well below threshold → close match → rerank for quality
        state = make_state(docs=[(make_doc("x"), 0.1)], confidence_score=0.1, attempts=1)
        assert route_after_retrieve(state, THRESHOLD) == "rerank"

    def test_low_confidence_rephrases_within_retry_limit(self):
        # distance above threshold → poor match → rephrase and retry
        state = make_state(docs=[(make_doc("x"), 0.8)], confidence_score=0.8, attempts=1)
        assert route_after_retrieve(state, THRESHOLD) == "rephrase"

    def test_low_confidence_gives_up_after_retries_exhausted(self):
        state = make_state(docs=[(make_doc("x"), 0.8)], confidence_score=0.8, attempts=MAX_RETRIES + 1)
        assert route_after_retrieve(state, THRESHOLD) == "give_up"

    def test_score_exactly_at_threshold_rephrases(self):
        # boundary: 0.5 is not < 0.5, so falls through to rephrase
        state = make_state(docs=[(make_doc("x"), 0.5)], confidence_score=0.5, attempts=1)
        assert route_after_retrieve(state, THRESHOLD) == "rephrase"

    def test_score_just_below_threshold_reranks(self):
        state = make_state(docs=[(make_doc("x"), 0.49)], confidence_score=0.49, attempts=1)
        assert route_after_retrieve(state, THRESHOLD) == "rerank"

    def test_custom_threshold_respected(self):
        state = make_state(docs=[(make_doc("x"), 0.3)], confidence_score=0.3, attempts=1)
        assert route_after_retrieve(state, confidence_threshold=0.2) == "rephrase"
        assert route_after_retrieve(state, confidence_threshold=0.4) == "rerank"


class TestRouteAfterGrounding:
    def test_grounded_routes_to_end(self):
        assert route_after_grounding(make_state(grounded=True)) == END

    def test_not_grounded_gives_up(self):
        assert route_after_grounding(make_state(grounded=False)) == "give_up"
