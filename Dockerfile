FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /backend_app

COPY requirements.txt requirements.txt
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .

RUN useradd --create-home --shell /bin/sh appuser \
    && chmod +x entrypoint.sh \
    && chown -R appuser:appuser /backend_app

USER appuser

EXPOSE 8000

ENTRYPOINT ["/backend_app/entrypoint.sh"]

CMD ["uvicorn", "backend.asgi:application", "--host", "0.0.0.0", "--port", "8000"]
