"""Keep the historical SQLAlchemy test suite explicit while runtime defaults to MongoDB."""

import os

os.environ.setdefault("PERSISTENCE_BACKEND", "postgresql")
