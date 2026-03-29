FROM python:3.12-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Copy dependency files first for better layer caching
COPY pyproject.toml uv.lock ./

# Install dependencies (no dev extras)
RUN uv sync --locked --no-dev

# Copy application code
COPY src/ src/
COPY templates/ templates/

# Set environment variables
ENV PYTHONPATH=src \
    FLASK_APP=pydiscogsqrcodegenerator \
    FLASK_ENV=production

EXPOSE 5001

# Run with gunicorn for production
RUN uv pip install gunicorn

CMD ["uv", "run", "gunicorn", "--bind", "0.0.0.0:5001", "--workers", "2", "--preload", "pydiscogsqrcodegenerator:create_app()"]
