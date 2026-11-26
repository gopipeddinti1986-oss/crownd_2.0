import os
import sys
from pathlib import Path

# Keep test JWTs deterministic and satisfy HS256's minimum key-length requirement,
# regardless of developer/sandbox environment variables.
os.environ["JWT_SECRET"] = "test-secret-that-is-long-enough-for-testing-32"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
