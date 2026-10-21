FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOST=0.0.0.0 \
    PORT=5000 \
    WAITRESS_THREADS=8

WORKDIR /app

COPY requirements.txt .
RUN python -m pip install --upgrade pip \
    && pip install -r requirements.txt

COPY . .

RUN chmod +x docker-entrypoint.sh \
    && groupadd --gid 10001 odc \
    && useradd --uid 10001 --gid odc --no-create-home odc \
    && mkdir -p logs uploads app/uploads app/static/uploads flask_session \
    && chown -R odc:odc logs uploads app/uploads app/static/uploads flask_session

USER odc

HEALTHCHECK --interval=30s --timeout=12s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/health', timeout=10)" || exit 1

EXPOSE 5000

ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["python", "run.py"]
