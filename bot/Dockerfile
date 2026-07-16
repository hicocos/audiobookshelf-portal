FROM python:3.13-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir -e . \
    && useradd --create-home --uid 10002 botuser \
    && chown -R botuser:botuser /app

USER botuser
CMD ["python", "-m", "app.main"]
