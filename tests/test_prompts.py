from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from prompts import (
    CHITCHAT_PROMPT,
    CLASSIFIER_PROMPT,
    GATE_PROMPT,
    GROUNDING_PROMPT,
    QUERY_REWRITE_PROMPT,
    RAG_PROMPT,
    REPHRASE_PROMPT,
)
from tests.helpers import SAMPLE_HISTORY


class TestRagPrompt:
    def test_renders_without_history(self):
        messages = RAG_PROMPT.format_messages(context="docs here", question="what is x?", history=[])
        assert messages[-1].content == "what is x?"
        assert any("docs here" in str(m.content) for m in messages)

    def test_renders_with_history(self):
        messages = RAG_PROMPT.format_messages(context="ctx", question="q", history=SAMPLE_HISTORY)
        # system + 2 history + human
        assert len(messages) == 4
        assert messages[-1].content == "q"

    def test_context_is_in_system_message(self):
        messages = RAG_PROMPT.format_messages(context="unique_ctx_string", question="q", history=[])
        system = next(m for m in messages if isinstance(m, SystemMessage))
        assert "unique_ctx_string" in system.content


class TestClassifierPrompt:
    def test_question_is_last_message(self):
        messages = CLASSIFIER_PROMPT.format_messages(question="how does auth work?")
        assert messages[-1].content == "how does auth work?"

    def test_has_system_message(self):
        messages = CLASSIFIER_PROMPT.format_messages(question="q")
        assert isinstance(messages[0], SystemMessage)


class TestGatePrompt:
    def test_question_is_last_message(self):
        messages = GATE_PROMPT.format_messages(question="hello there")
        assert messages[-1].content == "hello there"

    def test_system_message_names_all_categories(self):
        messages = GATE_PROMPT.format_messages(question="q")
        system = messages[0].content
        assert "proceed" in system
        assert "chitchat" in system
        assert "abuse" in system


class TestRephrasePrompt:
    def test_question_is_last_message(self):
        messages = REPHRASE_PROMPT.format_messages(question="how does it work?")
        assert messages[-1].content == "how does it work?"


class TestGroundingPrompt:
    def test_context_and_answer_in_human_message(self):
        messages = GROUNDING_PROMPT.format_messages(context="source text", answer="the answer")
        human = messages[-1].content
        assert "source text" in human
        assert "the answer" in human


class TestQueryRewritePrompt:
    def test_renders_with_history(self):
        messages = QUERY_REWRITE_PROMPT.format_messages(question="follow up", history=SAMPLE_HISTORY)
        assert messages[-1].content == "follow up"

    def test_history_messages_appear_before_question(self):
        messages = QUERY_REWRITE_PROMPT.format_messages(question="q", history=SAMPLE_HISTORY)
        contents = [m.content for m in messages]
        history_idx = contents.index("how does auth work?")
        question_idx = contents.index("q")
        assert history_idx < question_idx


class TestChitchatPrompt:
    def test_question_is_last_message(self):
        messages = CHITCHAT_PROMPT.format_messages(question="thanks!")
        assert messages[-1].content == "thanks!"
