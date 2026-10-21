"""Embedding backends.

* ``demo``  - dependency-light stand-in used for the hackathon demo. Text = hashed keyword/bigram
              vectors (384-d), images = centre-weighted RGB colour histograms (512-d). It is NOT
              CLIP or SentenceTransformer; scores it produces are simulated.
* ``real``  - CLIP (clip-ViT-B-32, 512-d) for images + SentenceTransformer (all-MiniLM-L6-v2, 384-d)
              for text, via the ``sentence-transformers`` package (see requirements-ml.txt).

Both expose the same interface and return L2-normalised vectors of identical dimensions, so the
database schema and matching code are identical for either backend.
"""

import hashlib
import io
import math
import re
from functools import lru_cache
from typing import Optional

from ..config import settings
from ..constants import IMAGE_DIM, TEXT_DIM

_TOKEN = re.compile(r"[a-z0-9]+")

STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "in", "on", "at", "to", "with", "near", "by", "for", "from",
    "is", "was", "it", "its", "this", "that", "has", "have", "had", "my", "me", "i", "there", "some",
    "very", "are", "be", "been", "around", "inside", "outside", "into", "left", "please", "u",
}

_SYNONYM_GROUPS = {
    "phone": ["smartphone", "mobile", "cellphone", "iphone", "android", "handset"],
    "spectacles": ["glasses", "eyeglasses", "specs", "spectacle", "eyewear", "frames"],
    "backpack": ["rucksack", "bagpack", "schoolbag", "knapsack"],
    "key": ["keys", "keychain", "keyring", "keyholder"],
    "wallet": ["purse", "billfold"],
    "bottle": ["flask", "tumbler", "sipper"],
    "umbrella": ["brolly"],
    "notebook": ["notepad", "diary", "journal", "copy", "notebooks"],
    "handbag": ["tote", "sling", "satchel"],
    "gray": ["grey", "silver"],
    "blue": ["navy"],
    "red": ["maroon", "crimson"],
}
SYNONYMS = {alias: target for target, aliases in _SYNONYM_GROUPS.items() for alias in aliases}


def _canon(tok: str) -> str:
    if tok in SYNONYMS:
        return SYNONYMS[tok]
    if len(tok) > 3 and tok.endswith("s") and not tok.endswith("ss"):
        tok = tok[:-1]
    return SYNONYMS.get(tok, tok)


def canonical_tokens(text: str) -> list[str]:
    """Lower-cased keywords with stopwords removed, plurals folded and common synonyms merged."""
    return [_canon(t) for t in _TOKEN.findall(text.lower()) if t not in STOPWORDS]


def build_item_text(title: str, category: str, description: str, features: Optional[str]) -> str:
    # Title is repeated so the item name carries more weight than free-form description.
    return f"{title}. {title}. {category}. {description}. {features or ''}"


def _l2(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec))
    return [v / norm for v in vec] if norm else vec


def _hash(token: str) -> int:
    return int.from_bytes(hashlib.md5(token.encode()).digest()[:8], "big")


class DemoEmbedder:
    name = "demo-hash"
    is_simulated = True

    def embed_text(self, text: str) -> list[float]:
        tokens = canonical_tokens(text)
        vec = [0.0] * TEXT_DIM

        def add(tok: str, weight: float) -> None:
            h = _hash(tok)
            vec[h % TEXT_DIM] += weight if (h >> 40) & 1 else -weight

        for tok in tokens:
            add(tok, 1.0)
        for a, b in zip(tokens, tokens[1:]):
            add(f"{a}_{b}", 0.5)
        return _l2(vec)

    def embed_image(self, data: bytes) -> Optional[list[float]]:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as im:
            im = im.convert("RGB")
            w, h = im.size
            # Centre crop (60%) so the object dominates the histogram over the background.
            box = (int(w * 0.2), int(h * 0.2), int(w * 0.8), int(h * 0.8))
            small = im.crop(box).resize((48, 48))
            pixels = list(small.getdata())
        hist = [0.0] * IMAGE_DIM  # 8 x 8 x 8 colour bins
        for r, g, b in pixels:
            hist[((r >> 5) << 6) | ((g >> 5) << 3) | (b >> 5)] += 1.0
        return _l2([math.sqrt(v) for v in hist])  # Hellinger-style


class SentenceTransformerEmbedder:
    name = "clip+minilm"
    is_simulated = False

    def __init__(self) -> None:
        from sentence_transformers import SentenceTransformer

        self._clip = SentenceTransformer(settings.clip_model)
        self._text = SentenceTransformer(settings.text_model)

    def embed_text(self, text: str) -> list[float]:
        return self._text.encode(text, normalize_embeddings=True).tolist()

    def embed_image(self, data: bytes) -> Optional[list[float]]:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as im:
            return self._clip.encode(im.convert("RGB"), normalize_embeddings=True).tolist()


@lru_cache
def get_embedder():
    """Models are loaded once per process (never per request)."""
    if settings.embedding_backend == "real":
        return SentenceTransformerEmbedder()
    return DemoEmbedder()
