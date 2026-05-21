from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

RAG_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        "You are a helpful assistant that answers questions based on the provided documentation.\n"
        "Use only the context below to answer. If the answer isn't in the context, say you don't know.\n\n"
        "Context:\n{context}",
    ),
    MessagesPlaceholder(variable_name="history", optional=True),
    ("human", "{question}"),
])

QUERY_REWRITE_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        "Given the conversation history and the user's latest message, determine if the message "
        "is a follow-up that relies on prior context. If so, rewrite it as a complete, self-contained "
        "question suitable for document retrieval. If it is already self-contained, return it unchanged. "
        "Reply with only the question, nothing else.",
    ),
    MessagesPlaceholder(variable_name="history"),
    ("human", "{question}"),
])

GROUNDING_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        "You are a fact-checker. Given source chunks and an answer, decide if the answer is fully "
        "supported by the sources. Reply with exactly one word: 'grounded' or 'not_grounded'.",
    ),
    (
        "human",
        "Sources:\n{context}\n\nAnswer:\n{answer}",
    ),
])

CLASSIFIER_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        "You are a router that decides whether a question can be answered from internal project documentation.\n"
        "The documentation covers software architecture, authentication, deployment, and infrastructure topics.\n"
        "Reply with exactly one word: 'in_scope' or 'out_of_scope'.",
    ),
    ("human", "{question}"),
])

REPHRASE_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        "Rephrase the following question to improve document retrieval. "
        "Use different keywords while preserving the intent. "
        "Reply with only the rephrased question, nothing else.",
    ),
    ("human", "{question}"),
])

GATE_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        "Classify the user message into exactly one of three categories:\n"
        "- 'proceed': a genuine question or request that may relate to software documentation\n"
        "- 'chitchat': conversational messages such as greetings, thanks, small talk, or farewells\n"
        "- 'abuse': harmful, offensive, threatening, or clearly inappropriate content\n\n"
        "Reply with exactly one word: proceed, chitchat, or abuse.",
    ),
    ("human", "{question}"),
])

CHITCHAT_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        "You are a friendly documentation assistant. The user has sent a conversational message. "
        "Reply briefly and warmly in one or two sentences. Do not answer technical questions.",
    ),
    ("human", "{question}"),
])
