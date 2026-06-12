FROM python:3.12-slim

WORKDIR /app

# System deps for OnnxOCR (OpenCV needs libgl1) + CJK fonts
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
ENV HTTP_PROXY= HTTPS_PROXY= http_proxy= https_proxy= ALL_PROXY= NO_PROXY="*"

RUN pip install --no-cache-dir -r requirements.txt

# Pre-download models for offline use
RUN python -c "from magika import Magika; Magika()"

COPY . .

RUN mkdir -p /tmp/opf-uploads /app/whitelist

EXPOSE 8080

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
