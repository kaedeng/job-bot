FROM python:3.11-slim

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency files first for layer caching
COPY pyproject.toml uv.lock ./

# Install production dependencies into the project venv
RUN uv sync --frozen --no-dev

# Copy source
COPY bot/ ./bot/

# Persistent volume for SQLite (mount at /data in Railway)
RUN mkdir -p /data

CMD ["uv", "run", "python", "-m", "bot.main"]
