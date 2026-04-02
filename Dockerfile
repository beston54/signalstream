# Signalstream — Local-first sentiment analysis
# Build: docker build -t signalstream .
# Run:   docker run -p 5001:5001 signalstream

FROM python:3.12-slim

# Non-root user
RUN useradd -m -r -s /bin/false signalstream

# Install application
COPY . /app
WORKDIR /app
RUN pip install --no-cache-dir .

# Data directory with correct permissions
RUN mkdir -p /app/data && chown signalstream:signalstream /app/data

USER signalstream

ENV SIGNALSTREAM_HOST=0.0.0.0
ENV SIGNALSTREAM_PORT=5001

EXPOSE 5001

CMD ["python", "-m", "signalstream"]
