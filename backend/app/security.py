from datetime import datetime, timedelta, timezone
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.hash import bcrypt
from .config import settings
from .db import get_db
from .models import User
from .mongo_store import MongoStore, get_mongo_store

bearer = HTTPBearer()
def hash_password(value): return bcrypt.hash(value[:72])
def create_token(user_id): return jwt.encode({"sub": str(user_id), "exp": datetime.now(timezone.utc)+timedelta(hours=8)}, settings.JWT_SECRET, algorithm="HS256")

def get_auth_storage(request: Request, db=Depends(get_db)):
    if settings.PERSISTENCE_BACKEND == "mongodb":
        return get_mongo_store(request)
    return db


def current_user(credentials: HTTPAuthorizationCredentials = Depends(bearer), storage=Depends(get_auth_storage)):
    try: user_id = int(jwt.decode(credentials.credentials, settings.JWT_SECRET, algorithms=["HS256"]).get("sub"))
    except JWTError: raise HTTPException(401, "Token inválido o vencido")
    except (TypeError, ValueError): raise HTTPException(401, "Token inválido o vencido")
    if isinstance(storage, MongoStore):
        user = storage.user_by_id(user_id, active=True)
    else:
        user = storage.query(User).filter_by(id=user_id, active=True).first()
    if not user: raise HTTPException(401, "Usuario no encontrado")
    return user
