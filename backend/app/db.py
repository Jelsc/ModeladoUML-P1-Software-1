from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker
from .config import settings

if settings.PERSISTENCE_BACKEND == "mongodb":
    # SQLAlchemy models remain available for legacy tests and explicit PostgreSQL mode,
    # but Mongo runtime imports must not create a platform SQL engine or session factory.
    engine = None
    SessionLocal = None
else:
    engine = create_engine(settings.DB_URL, pool_pre_ping=True)
    if settings.DB_URL.startswith("postgresql"):
        @event.listens_for(engine, "connect")
        def _set_database_timezone(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("SET TIME ZONE 'America/La_Paz'")
            cursor.close()
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base = declarative_base()

def get_db():
    if SessionLocal is None:
        yield None
        return
    db = SessionLocal()
    try: yield db
    finally: db.close()
