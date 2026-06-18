"""FastAPI server for PII detection and redaction.

Thin wrapper around pf_backend (privacy-filter.cpp via ctypes).
"""

import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from pf_backend import PFBackend

logger = logging.getLogger("opf-server")

_pf: PFBackend | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _pf
    logger.info("Loading pf_backend model ...")
    start = time.monotonic()
    _pf = PFBackend.get()
    elapsed = time.monotonic() - start
    logger.info("Model loaded in %.1fs (loaded=%s)", elapsed, _pf.loaded)
    yield
    _pf = None


app = FastAPI(
    title="OPF Privacy Filter Service",
    description="PII detection and redaction powered by privacy-filter.cpp",
    version="0.2.0",
    lifespan=lifespan,
)


class RedactRequest(BaseModel):
    text: str = Field(..., description="Text to redact")


class RedactBatchRequest(BaseModel):
    texts: list[str] = Field(..., description="List of texts to redact")


class SpanOut(BaseModel):
    label: str
    start: int
    end: int
    text: str
    placeholder: str


class RedactResponse(BaseModel):
    schema_version: int
    text: str
    redacted_text: str
    detected_spans: list[SpanOut]
    summary: dict
    warning: str | None = None
    latency_ms: float


class RedactTextOnlyResponse(BaseModel):
    redacted_text: str
    latency_ms: float


class RedactBatchResponse(BaseModel):
    results: list[RedactResponse]
    total_latency_ms: float


class HealthResponse(BaseModel):
    status: str
    model_loaded: bool


@app.get("/health", response_model=HealthResponse)
def health():
    return HealthResponse(
        status="ok",
        model_loaded=_pf is not None and _pf.loaded,
    )


def _build_response(text: str, spans: list[dict], latency_ms: float) -> RedactResponse:
    """Build a RedactResponse from pf_backend classify() output.

    spans: [{"label", "start", "end", "text", "score"}]
    """
    # Build redacted_text by replacing spans with <label> placeholders
    redacted = text
    # Apply replacements from right to left so offsets stay valid
    sorted_spans = sorted(spans, key=lambda s: s["start"], reverse=True)
    placeholder_map: dict[int, str] = {}  # index in spans → placeholder
    for i, s in enumerate(reversed(sorted_spans)):
        placeholder = f"<{s['label']}>"
        redacted = redacted[: s["start"]] + placeholder + redacted[s["end"] :]
        placeholder_map[len(sorted_spans) - 1 - i] = placeholder

    # Build detected_spans with placeholder
    detected = []
    for i, s in enumerate(spans):
        detected.append(
            SpanOut(
                label=s["label"],
                start=s["start"],
                end=s["end"],
                text=s["text"],
                placeholder=placeholder_map.get(i, f"<{s['label']}>"),
            )
        )

    # Summary: counts by label
    summary: dict[str, int] = {}
    for s in spans:
        summary[s["label"]] = summary.get(s["label"], 0) + 1

    return RedactResponse(
        schema_version=1,
        text=text,
        redacted_text=redacted,
        detected_spans=detected,
        summary=summary,
        warning=None,
        latency_ms=latency_ms,
    )


def _classify_text(text: str) -> list[dict]:
    """Run pf_backend classify, ensuring backend is initialized."""
    global _pf
    if _pf is None:
        _pf = PFBackend.get()
    return _pf.classify(text, threshold=0.5)


@app.post("/redact", response_model=RedactResponse)
def redact(req: RedactRequest):
    start = time.perf_counter()
    spans = _classify_text(req.text)
    latency_ms = (time.perf_counter() - start) * 1000.0
    return _build_response(req.text, spans, latency_ms)


@app.post("/redact/text", response_model=RedactTextOnlyResponse)
def redact_text_only(req: RedactRequest):
    start = time.perf_counter()
    spans = _classify_text(req.text)
    latency_ms = (time.perf_counter() - start) * 1000.0
    # Build redacted text
    redacted = req.text
    for s in sorted(spans, key=lambda s: s["start"], reverse=True):
        redacted = redacted[: s["start"]] + f"<{s['label']}>" + redacted[s["end"] :]
    return RedactTextOnlyResponse(redacted_text=redacted, latency_ms=latency_ms)


@app.post("/redact/batch", response_model=RedactBatchResponse)
def redact_batch(req: RedactBatchRequest):
    """Batch redaction with parallel inference via ThreadPoolExecutor."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    batch_start = time.perf_counter()
    max_workers = min(8, len(req.texts))

    def _infer(text):
        start = time.perf_counter()
        spans = _classify_text(text)
        latency_ms = (time.perf_counter() - start) * 1000.0
        return _build_response(text, spans, latency_ms)

    results = [None] * len(req.texts)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_idx = {executor.submit(_infer, text): i for i, text in enumerate(req.texts)}
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            results[idx] = future.result()

    total_latency_ms = (time.perf_counter() - batch_start) * 1000.0
    return RedactBatchResponse(results=results, total_latency_ms=total_latency_ms)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
