from __future__ import annotations

import sys
from pathlib import Path

# The GitHub Action implementation intentionally lives at the repository root so
# action.yml can execute it directly via GITHUB_ACTION_PATH. Add that root to the
# import path during tests so the same production file is exercised by pytest.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
