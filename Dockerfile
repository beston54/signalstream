# Signalstream — Local-first sentiment analysis
# Build: docker build -t signalstream .
# Run:   docker run -p 5001:5001 signalstream

FROM python:3.12-slim AS base

# WeasyPrint system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libcairo2 \
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
        libgdk-pixbuf2.0-0 \
        libffi-dev \
        shared-mime-info && \
    rm -rf /var/lib/apt/lists/*

# Non-root user (BOARD security requirement)
RUN useradd -m -r -s /bin/false signalstream

# Install application
COPY . /app
WORKDIR /app
RUN pip install --no-cache-dir ".[pdf]"

# Data directory with correct permissions
RUN mkdir -p /app/data && chown signalstream:signalstream /app/data

# Switch to non-root user
USER signalstream

# Bind to 0.0.0.0 inside container (container network isolation handles security)
ENV SIGNALSTREAM_HOST=0.0.0.0
ENV SIGNALSTREAM_PORT=5001

EXPOSE 5001

CMD ["python", "-m", "signalstream"]
