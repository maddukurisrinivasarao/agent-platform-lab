FROM python:3.13.9-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AGENT_STATE_DIR=/data \
    AGENT_TICKETS_FILE=/app/data/tickets.xml

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
COPY data ./data
# Install the LLM SDKs so any AGENT_LLM_PROVIDER works; keys are supplied at run time.
RUN pip install --no-cache-dir ".[groq,openrouter,anthropic]" \
    && useradd --create-home --uid 10001 agent \
    && mkdir -p /data \
    && chown agent /data

USER agent
VOLUME ["/data"]

# With no arguments the container recovers interrupted tasks, so a restart doubles as crash recovery.
ENTRYPOINT ["agent-worker"]
CMD ["recover"]
