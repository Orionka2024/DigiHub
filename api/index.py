import sys
import os

# Add the repo root to Python path so all modules are importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# On Vercel, the filesystem is read-only except for /tmp.
# Override the data directory to use /tmp so the store can write files.
os.environ.setdefault("KVK_DATA_DIR", "/tmp/kvk_data")

from app.main import app
