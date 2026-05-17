from langchain_core.prompts import ChatPromptTemplate

RAG_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        "You are a helpful assistant that answers questions based on the provided documentation.\n"
        "Use only the context below to answer. If the answer isn't in the context, say you don't know.\n\n"
        "Context:\n{context}",
    ),
    ("human", "{question}"),
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
