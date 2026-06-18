"""ctypes wrapper for privacy-filter.cpp (libpf.so / libpf.dylib).

Provides a thread-safe singleton PFBackend that loads the GGUF model once
and exposes a simple classify() API.  Handles:
  - C API binding (pf_load / pf_classify / pf_free / …)
  - 217 model labels → 8 app-level categories
  - Adjacent same-category entity merging (e.g. FIRSTNAME + LASTNAME → person)
  - Byte-offset → char-offset conversion for Python strings
  - Thread-safe classify (Lock, GGML is single-threaded per ctx)
"""

from __future__ import annotations

import ctypes
import os
import sys
import threading
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Label mapping: 217 model labels → 8 app categories
# ---------------------------------------------------------------------------

_LABEL_MAP: dict[str, str] = {}

def _fill_label_map() -> dict[str, str]:
    """Build the 217→8 mapping table.  Called once at module load."""
    m: dict[str, str] = {}

    # person
    for tag in ("FIRSTNAME", "MIDDLENAME", "LASTNAME",
                "GIVENNAME", "NICKNAME", "PREFIXNAME", "SUFFIXNAME"):
        m[tag] = "private_person"

    # phone
    for tag in ("PHONE", "TELEPHONENUMBER", "FAXNUMBER"):
        m[tag] = "private_phone"

    # email
    for tag in ("EMAIL", "EMAILADDRESS"):
        m[tag] = "private_email"

    # url / ip
    for tag in ("URL", "IPADDRESS", "IPV4", "IPV6", "DOMAIN"):
        m[tag] = "private_url"

    # address
    for tag in ("STREET", "CITY", "STATE", "ZIPCODE", "COUNTRY",
                "BUILDINGNUMBER", "APARTMENT", "FLOOR",
                "STREETADDRESS", "FULLADDRESS"):
        m[tag] = "private_address"

    # date
    for tag in ("DATE", "DATEOFBIRTH", "TIME", "DATETIME"):
        m[tag] = "private_date"

    # id card / account number
    for tag in ("SSN", "ACCOUNTNAME", "IBAN", "NATIONALID",
                "DRIVERLICENSE", "PASSPORTNUMBER", "TAXID",
                "SOCIAL_SECURITY_NUMBER", "ACCOUNTNUMBER"):
        m[tag] = "account_number"

    # bank card
    for tag in ("CREDITCARD", "BANKACCOUNT", "CARDNUMBER",
                "CREDITCARDCVV", "ROUTINGNUMBER"):
        m[tag] = "private_bankcard"

    # secret
    for tag in ("PASSWORD", "CVV", "PIN", "APIKEY", "TOKEN",
                "SECRET", "PASSPHRASE", "AUTHCODE"):
        m[tag] = "secret"

    # organization
    for tag in ("ORGANIZATION", "COMPANY", "ORG"):
        m[tag] = "organization"

    # explicitly dropped (not PII)
    for tag in ("AMOUNT", "CURRENCY", "GENDER", "AGE", "NATIONALITY",
                "RELIGION", "POLITICAL", "HEALTH", "O"):
        m[tag] = ""  # empty = drop

    return m


_LABEL_MAP = _fill_label_map()


def _map_label(raw: str) -> str | None:
    """Map a model label to app category.  Returns None to drop."""
    # Strip BIO prefix (B-, I-) if present
    label = raw
    if label.startswith("B-") or label.startswith("I-"):
        label = label[2:]

    mapped = _LABEL_MAP.get(label)
    if mapped is not None:
        return mapped or None  # "" → None (drop)

    # Unknown label — try lowercase match, else drop
    return _LABEL_MAP.get(label.upper()) or None


# ---------------------------------------------------------------------------
# Merge adjacent same-category entities
# ---------------------------------------------------------------------------

def _merge_adjacent(spans: list[dict], max_gap: int = 1) -> list[dict]:
    """Merge adjacent entities of the same category if gap ≤ max_gap chars.

    Examples:
      FIRSTNAME("靳晓") + LASTNAME("鹏") → private_person("靳晓鹏")
      STREET("沙子口路甲") + BUILDINGNUMBER("48号") → private_address("沙子口路甲48号")
    """
    if not spans:
        return spans

    # Sort by start offset
    spans = sorted(spans, key=lambda s: (s["start"], -s["end"]))

    merged: list[dict] = [spans[0].copy()]
    for cur in spans[1:]:
        prev = merged[-1]
        # Same category and adjacent or overlapping
        if cur["label"] == prev["label"] and cur["start"] - prev["end"] <= max_gap:
            # Extend
            prev["end"] = max(prev["end"], cur["end"])
            prev["text"] = prev["text"] + cur["text"]
            prev["score"] = max(prev.get("score", 0), cur.get("score", 0))
        else:
            merged.append(cur.copy())

    return merged


# ---------------------------------------------------------------------------
# Byte-offset → char-offset conversion
# ---------------------------------------------------------------------------

def _byte_to_char_offsets(text: str, start_b: int, end_b: int) -> tuple[int, int]:
    """Convert UTF-8 byte offsets to Python str (char) offsets."""
    encoded = text.encode("utf-8")
    # Count chars before start_b
    char_start = len(encoded[:start_b].decode("utf-8", errors="replace"))
    char_end = len(encoded[:end_b].decode("utf-8", errors="replace"))
    return char_start, char_end


# ---------------------------------------------------------------------------
# C API structures
# ---------------------------------------------------------------------------

class _PFEntity(ctypes.Structure):
    """Mirror of pf_entity from pf.h."""
    _fields_ = [
        ("start", ctypes.c_int32),
        ("end", ctypes.c_int32),
        ("score", ctypes.c_float),
        ("label", ctypes.c_char_p),
    ]


# ---------------------------------------------------------------------------
# PFBackend — thread-safe singleton
# ---------------------------------------------------------------------------

class PFBackend:
    """Thread-safe singleton wrapper around privacy-filter.cpp.

    Usage:
        pf = PFBackend.get()
        spans = pf.classify("张三的手机号是13800138000", threshold=0.5)
        # [{"label": "private_person", "start": 0, "end": 2, "text": "张三", "score": 0.9},
        #  {"label": "private_phone",  "start": 7, "end": 18, "text": "13800138000", "score": 0.99}]
    """

    _instance: Optional["PFBackend"] = None
    _lock_init = threading.Lock()

    def __init__(self) -> None:
        # Should not be called directly — use PFBackend.get()
        self._lib: ctypes.CDLL | None = None
        self._ctx: ctypes.c_void_p | None = None
        self._classify_lock = threading.Lock()
        self._loaded = False

    @classmethod
    def get(cls) -> "PFBackend":
        """Get (or create) the singleton instance."""
        if cls._instance is None:
            with cls._lock_init:
                if cls._instance is None:
                    inst = cls()
                    inst._load()
                    cls._instance = inst
        return cls._instance

    # ---- Internal: locate and load the shared library ----

    def _find_lib(self) -> Path:
        """Find libpf.so or libpf.dylib."""
        # 1. Environment variable
        env_path = os.environ.get("PF_LIB_PATH")
        if env_path:
            p = Path(env_path)
            if p.is_file():
                return p

        # 2. Common locations
        candidates = [
            # Docker / Linux
            Path("/usr/local/lib/pf/libpf.so"),
            # Local build (release-portable)
            Path.home() / "dev/privacy-filter.cpp/build/release-portable/bin/libpf.dylib",
            # macOS standard
            Path("/usr/local/lib/libpf.dylib"),
        ]

        for c in candidates:
            if c.is_file():
                return c

        raise FileNotFoundError(
            "Cannot find libpf.so / libpf.dylib. "
            "Set PF_LIB_PATH or compile privacy-filter.cpp."
        )

    def _find_model(self) -> str:
        """Find the GGUF model file."""
        # 1. Environment variable
        env_path = os.environ.get("PF_MODEL_PATH")
        if env_path:
            p = Path(env_path)
            if p.is_file():
                return str(p)

        # 2. Common locations
        candidates = [
            # Docker volume mount
            Path("/models/privacy-filter-multilingual-f16.gguf"),
            # Local
            Path.home() / "dev/privacy-filter.cpp/models/privacy-filter-multilingual-f16.gguf",
        ]

        for c in candidates:
            if c.is_file():
                return str(c)

        raise FileNotFoundError(
            "Cannot find privacy-filter GGUF model. "
            "Set PF_MODEL_PATH or place model in models/."
        )

    def _load(self) -> None:
        """Load the shared library and model."""
        lib_path = self._find_lib()
        model_path = self._find_model()

        # Load shared library
        self._lib = ctypes.CDLL(str(lib_path))

        # Bind C functions
        lib = self._lib

        lib.pf_abi_version.argtypes = []
        lib.pf_abi_version.restype = ctypes.c_int

        lib.pf_load.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]
        lib.pf_load.restype = ctypes.c_void_p

        lib.pf_free.argtypes = [ctypes.c_void_p]
        lib.pf_free.restype = None

        lib.pf_last_error.argtypes = [ctypes.c_void_p]
        lib.pf_last_error.restype = ctypes.c_char_p

        lib.pf_set_window.argtypes = [ctypes.c_void_p, ctypes.c_int32]
        lib.pf_set_window.restype = None

        lib.pf_classify.argtypes = [
            ctypes.c_void_p,           # ctx
            ctypes.c_char_p,           # text
            ctypes.c_size_t,           # len
            ctypes.c_float,            # threshold
            ctypes.POINTER(ctypes.POINTER(_PFEntity)),  # out
            ctypes.POINTER(ctypes.c_size_t),             # n_out
        ]
        lib.pf_classify.restype = ctypes.c_int

        lib.pf_entities_free.argtypes = [ctypes.POINTER(_PFEntity), ctypes.c_size_t]
        lib.pf_entities_free.restype = None

        # Check ABI
        ver = lib.pf_abi_version()
        if ver < 1:
            raise RuntimeError(f"libpf ABI version {ver} too old (need ≥ 1)")

        # Load model (heavy operation, ~2-3s)
        n_threads = os.environ.get("PF_THREADS", "0")
        self._ctx = lib.pf_load(
            model_path.encode("utf-8"),
            None,  # device = auto
            int(n_threads),
        )
        if not self._ctx:
            err = lib.pf_last_error(None)
            raise RuntimeError(f"pf_load failed: {err or 'unknown error'}")

        # Set window size (default 4096, enough for most docs)
        window = int(os.environ.get("PF_WINDOW", "4096"))
        lib.pf_set_window(self._ctx, window)

        self._loaded = True

    # ---- Public API ----

    def classify(self, text: str, threshold: float = 0.5) -> list[dict]:
        """Classify text and return PII spans.

        Returns list of dicts: [{"label", "start", "end", "text", "score"}]
        Label is one of: private_person, private_phone, private_email,
        private_url, private_address, private_date, account_number,
        private_bankcard, secret, organization.
        """
        if not self._loaded or not self._ctx:
            raise RuntimeError("PFBackend not loaded")

        if not text or not text.strip():
            return []

        text_bytes = text.encode("utf-8")

        with self._classify_lock:
            out_ptr = ctypes.POINTER(_PFEntity)()
            n_out = ctypes.c_size_t(0)

            ret = self._lib.pf_classify(
                self._ctx,
                text_bytes,
                len(text_bytes),
                ctypes.c_float(threshold),
                ctypes.byref(out_ptr),
                ctypes.byref(n_out),
            )

            if ret != 0:
                err = self._lib.pf_last_error(self._ctx)
                raise RuntimeError(f"pf_classify failed: {err or 'unknown error'}")

            # Extract results
            raw_spans: list[dict] = []
            for i in range(n_out.value):
                ent = out_ptr[i]
                raw_label = ent.label.decode("utf-8", errors="replace") if ent.label else ""

                mapped = _map_label(raw_label)
                if mapped is None:
                    continue  # dropped label

                # Convert byte offsets to char offsets
                char_start, char_end = _byte_to_char_offsets(text, ent.start, ent.end)
                span_text = text[char_start:char_end]

                raw_spans.append({
                    "label": mapped,
                    "start": char_start,
                    "end": char_end,
                    "text": span_text,
                    "score": round(ent.score, 4),
                })

            # Free C-side memory
            self._lib.pf_entities_free(out_ptr, n_out)

        # Merge adjacent same-category entities
        spans = _merge_adjacent(raw_spans, max_gap=1)

        return spans

    @property
    def loaded(self) -> bool:
        return self._loaded

    def __del__(self) -> None:
        if self._ctx and self._lib:
            try:
                self._lib.pf_free(self._ctx)
            except Exception:
                pass
