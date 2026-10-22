"""Read local development configuration from environment variables."""
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "")
EMBEDDING_MODEL = os.getenv(
    "EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
)
RERANKER_MODEL = os.getenv('RERANKER_MODEL', 'cross-encoder/ms-marco-MiniLM-L-6-v2')
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openrouter").strip().lower()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "google/gemini-3.1-flash-lite")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5-mini")

# Payments are opt-in. Sandbox funds never pay for real provider requests.
RAG_PAYMENTS_MODE = os.getenv('RAG_PAYMENTS_MODE', 'disabled').strip().lower()
RAG_WALLET_ENFORCEMENT = os.getenv('RAG_WALLET_ENFORCEMENT', 'false').strip().lower()
NOWPAYMENTS_API_KEY = os.getenv('NOWPAYMENTS_API_KEY', '')
NOWPAYMENTS_IPN_SECRET = os.getenv('NOWPAYMENTS_IPN_SECRET', '')
NOWPAYMENTS_SANDBOX_API_KEY = os.getenv('NOWPAYMENTS_SANDBOX_API_KEY', '')
NOWPAYMENTS_SANDBOX_IPN_SECRET = os.getenv('NOWPAYMENTS_SANDBOX_IPN_SECRET', '')
RAG_PAYMENTS_CALLBACK_BASE_URL = os.getenv('RAG_PAYMENTS_CALLBACK_BASE_URL', '').rstrip('/')

# Explicit global support access; only listed active administrator accounts qualify.
RAG_SUPPORT_STAFF_USER_IDS = os.getenv('RAG_SUPPORT_STAFF_USER_IDS', '')

# Public signups create isolated workspaces; invitations retain their own scope.
RAG_PUBLIC_REGISTRATION_ENABLED = os.getenv('RAG_PUBLIC_REGISTRATION_ENABLED', 'true').strip().lower()
