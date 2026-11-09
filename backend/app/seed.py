from .config import settings
from .db import SessionLocal
from .models import User
from .security import hash_password
def main():
    if not settings.SEED_DEMO: return
    if settings.PERSISTENCE_BACKEND == "mongodb":
        from .mongo_store import MongoStore
        store = MongoStore(settings.MONGODB_URL, settings.MONGODB_DATABASE)
        try:
            store.initialize()
            user = store.user_by_email("demo@uml.local")
            if not user:
                user = {"id": store.allocate_user_id(), "email": "demo@uml.local", "name": "Demo User",
                        "password_hash": hash_password("demo123"), "role": "admin", "active": True}
                store.users.insert_one(user)
            else:
                store.users.update_one({"id": user["id"]}, {"$set": {"role": "admin", "active": True}})
            store.set_admin_membership(user["id"], True)
        finally:
            store.close()
        return
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(email="demo@uml.local").first()
        if not user:
            db.add(User(email="demo@uml.local", name="Demo User", password_hash=hash_password("demo123"), role="admin")); db.commit()
        elif user.role != "admin":
            user.role = "admin"; db.commit()
    finally: db.close()
if __name__ == "__main__": main()
