# ==============================================================================
# Multi-stage build: privacy-filter.cpp + OPF Web App
# Stage 1: Compile libpf.so from source (release-portable, all CPU variants)
# Stage 2: Python runtime with OnnxOCR + pf_backend
# ==============================================================================

# ---- Stage 1: Build privacy-filter.cpp ----
FROM ubuntu:24.04 AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential cmake git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Clone and build privacy-filter.cpp (release-portable preset = all CPU ISA variants)
ARG PF_REPO=https://github.com/localai-org/privacy-filter.cpp.git
ARG PF_REF=master
RUN git clone --depth 1 --recurse-submodules --shallow-submodules --branch ${PF_REF} ${PF_REPO} /build/pf || \
    git clone --depth 1 --recurse-submodules --shallow-submodules ${PF_REPO} /build/pf

WORKDIR /build/pf
# Build pf as shared library (default is STATIC, we need .so for ctypes)
RUN sed -i 's/add_library(pf STATIC/add_library(pf SHARED/' CMakeLists.txt
# Simple release build (OrbStack is ARM64, no need for portable x86 variants)
RUN cmake -B build/release \
        -DCMAKE_BUILD_TYPE=Release \
        -DGGML_NATIVE=OFF \
        -DCMAKE_LIBRARY_OUTPUT_DIRECTORY=/build/pf/build/release/bin \
        -DCMAKE_RUNTIME_OUTPUT_DIRECTORY=/build/pf/build/release/bin \
    && cmake --build build/release -j$(nproc)

# ---- Stage 2: Python runtime ----
FROM python:3.12-slim

WORKDIR /app

# System deps for OnnxOCR (OpenCV needs libgl1) + CJK fonts
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 fonts-noto-cjk libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Copy compiled privacy-filter shared libraries
COPY --from=builder /build/pf/build/release/bin/libpf.so* /usr/local/lib/pf/
COPY --from=builder /build/pf/build/release/bin/libggml*.so* /usr/local/lib/pf/
RUN ldconfig /usr/local/lib/pf

# Environment for pf_backend
ENV PF_LIB_PATH=/usr/local/lib/pf/libpf.so
ENV PF_MODEL_PATH=/models/privacy-filter-multilingual-f16.gguf
ENV PF_THREADS=0
ENV PF_WINDOW=4096

# Python dependencies
COPY requirements.txt .
ENV HTTP_PROXY= HTTPS_PROXY= http_proxy= https_proxy= ALL_PROXY= NO_PROXY="*"
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download Magika models for offline use
RUN python -c "from magika import Magika; Magika()"

# Download privacy-filter model (~2.7GB)
RUN mkdir -p /models && \
    curl -L -o /models/privacy-filter-multilingual-f16.gguf \
    "https://huggingface.co/LocalAI-io/privacy-filter-multilingual-GGUF/resolve/main/privacy-filter-multilingual-f16.gguf"

# Copy application code
COPY . .

RUN mkdir -p /tmp/opf-uploads /app/whitelist /models

EXPOSE 8080

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
