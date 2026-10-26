from src.db.base import Base
from src.db.session import engine
import src.db
# import src.db.models

def init_db():
    print("Metadata tables BEFORE create_all:")
    print(Base.metadata.tables.keys())
    Base.metadata.create_all(bind=engine)
    print("Database schema created.")

if __name__ == "__main__":
    init_db()
