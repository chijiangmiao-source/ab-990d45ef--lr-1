FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8080

WORKDIR /app

COPY app ./app
COPY tests ./tests
COPY scripts ./scripts
COPY verify ./verify
RUN chmod +x verify

EXPOSE 8080

HEALTHCHECK --interval=5s --timeout=3s --retries=10 --start-period=3s \
  CMD python3 -c "import json,urllib.request,sys; r=urllib.request.urlopen('http://127.0.0.1:8080/healthz',timeout=2); sys.exit(0 if json.load(r).get('status')=='ok' else 1)"

CMD ["python3", "-m", "app.server"]
