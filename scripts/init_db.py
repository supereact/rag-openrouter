from app.db import init_database

if __name__ == "__main__":
    init_database()
    print("Database initialized: pgvector extension, documents, chunks.")
