from .config import settings
from .db import SessionLocal
from .models import User
from .security import hash_password
def main():
    if not settings.SEED_DEMO: return
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(email="demo@uml.local").first()
        if not user:
            db.add(User(email="demo@uml.local", name="Demo User", password_hash=hash_password("demo123"), role="admin")); db.commit()
        elif user.role != "admin":
            user.role = "admin"; db.commit()
    finally: db.close()
if __name__ == "__main__": main()
