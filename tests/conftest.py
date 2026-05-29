import os

# Provide required env vars before any test module is imported.
# api.py instantiates Settings() at module scope, which requires DB_URL.
# Without this, collection fails in CI where no .env file exists.
os.environ.setdefault("DB_URL", "postgresql://test:test@localhost/test")
