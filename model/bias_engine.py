"""
model/bias_engine.py — tools/bias_engine.py'ye yönlendirici.

Gerçek implementasyon tools/bias_engine.py içindedir.
main.py bu modülü tools/ üzerinden sys.path ile yükler;
bu dosya yalnızca 'from model.bias_engine import ...' şeklinde
doğrudan import edenler için uyumluluk katmanı sağlar.
"""
import sys
import os as _os

_tools_dir = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "tools")
if _tools_dir not in sys.path:
    sys.path.insert(0, _tools_dir)

from bias_engine import *          # noqa: F401, F403
from bias_engine import (          # noqa: F401
    derive_all,
    compute_diff,
    _compute_baseline,
)
