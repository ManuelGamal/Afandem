FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /bin/uv
# Hugging Face Spaces run the container as uid 1000; that user must own the writable cache.
RUN useradd -m -u 1000 user
WORKDIR /app
ENV PYTHONUTF8=1 UV_COMPILE_BYTECODE=1 PORT=7860
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY . .
RUN uv sync --frozen --no-dev && mkdir -p /app/cache && chown -R user /app/cache
USER user
EXPOSE 7860
CMD ["sh", "-c", "/app/.venv/bin/uvicorn --factory moderator.server:create_app --host 0.0.0.0 --port ${PORT}"]
