import sys
import os

# Ensure the project root is in sys.path so root-level modules (db, auth, routes, etc.) are importable
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
