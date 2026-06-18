import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent
_WORKSPACE = _REPO.parent
sys.path.insert(0, str(_REPO / "src"))

_default_vendor = _WORKSPACE / "vendor" / "strutil-1.0.0"
_vendor = Path(os.environ.get("STRUTIL_VENDOR", str(_default_vendor)))
sys.path.insert(0, str(_vendor))
