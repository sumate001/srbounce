FROM python:3.12-slim

WORKDIR /app

# Build context = repo root (see docker-compose.yml) so srbounce installs
# straight from the monorepo — the exact validated strategy code.
COPY pyproject.toml /srbounce-src/
COPY srbounce/ /srbounce-src/srbounce/
RUN pip install --no-cache-dir /srbounce-src

COPY livesignal/pyproject.toml /app/
COPY livesignal/livesignal/ /app/livesignal/
RUN pip install --no-cache-dir .

COPY livesignal/config.yaml /app/config.yaml

VOLUME /app/data
CMD ["python", "-m", "livesignal.trader"]
