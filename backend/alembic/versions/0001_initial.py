from alembic import op
from sqlalchemy import create_engine
from app.config import settings
from app.db import Base
from app import models
revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

def upgrade(): Base.metadata.create_all(create_engine(settings.DB_URL))
def downgrade(): Base.metadata.drop_all(create_engine(settings.DB_URL))
