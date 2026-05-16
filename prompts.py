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
