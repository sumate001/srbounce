FROM python:3.12-slim

WORKDIR /app

# srbounce (the validated strategy code) is vendored into srbounce-pkg/ by
# build.sh before the image build — livesignal imports it, never copies logic.
COPY srbounce-pkg/ /srbounce-pkg/
RUN pip install --no-cache-dir /srbounce-pkg

COPY pyproject.toml /app/
COPY livesignal/ /app/livesignal/
RUN pip install --no-cache-dir .

COPY config.yaml /app/config.yaml

VOLUME /app/data
CMD ["python", "-m", "livesignal.trader"]
