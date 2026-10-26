FROM python:3.13.9-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AGENT_STATE_DIR=/data

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir . \
    && useradd --create-home --uid 10001 agent \
    && mkdir -p /data \
    && chown agent /data

USER agent
VOLUME ["/data"]

# With no arguments the container recovers interrupted tasks, so a restart doubles as crash recovery.
ENTRYPOINT ["agent-worker"]
CMD ["recover"]
