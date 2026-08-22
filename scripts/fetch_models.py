"""Download the two ONNX models the voice pipeline needs.

onnxruntime, not torch: the same two models run in ~50 MB of dependency
instead of ~2 GB.

  silero_vad.onnx  (~2 MB)  -- utterance segmentation, splits on silence
  ecapa.onnx       (~25 MB) -- 192-dim speaker embedding for the owner voiceprint

Run:  python -m scripts.fetch_models
"""

from __future__ import annotations

import sys
import urllib.error
import urllib.request
from pathlib import Path

# Pinned to a commit/tag rather than a moving branch: a silently different
# embedding model would shift every stored voiceprint's cosine scores and
# quietly break speaker identification for existing stores.
MODELS: dict[str, str] = {
    "silero_vad.onnx": (
        "https://raw.githubusercontent.com/snakers4/silero-vad/"
        "v5.1.2/src/silero_vad/data/silero_vad.onnx"
    ),
    # NOTE: set this to whichever ECAPA/WeSpeaker ONNX export you standardise
    # on, then record the checksum below. Left explicit rather than guessed --
    # the wrong export produces embeddings of the wrong dimension.
    "ecapa.onnx": "",
}

DEST = Path(__file__).resolve().parent.parent / "models"


def fetch(name: str, url: str) -> bool:
    target = DEST / name
    if target.exists() and target.stat().st_size > 0:
        print(f"  {name}: already present ({target.stat().st_size:,} bytes)")
        return True
    if not url:
        print(f"  {name}: NO URL CONFIGURED -- edit scripts/fetch_models.py", file=sys.stderr)
        return False
    print(f"  {name}: downloading...")
    try:
        with urllib.request.urlopen(url, timeout=60) as r, target.open("wb") as f:
            f.write(r.read())
    except (urllib.error.URLError, OSError) as e:
        target.unlink(missing_ok=True)
        print(f"  {name}: FAILED -- {e}", file=sys.stderr)
        return False
    print(f"  {name}: ok ({target.stat().st_size:,} bytes)")
    return True


def main() -> int:
    DEST.mkdir(parents=True, exist_ok=True)
    print(f"models -> {DEST}")
    ok = all(fetch(name, url) for name, url in MODELS.items())
    if not ok:
        print("\nSome models are missing. Phases 0-2 do not need them; the voice "
              "endpoints (phase 3+) do.", file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
