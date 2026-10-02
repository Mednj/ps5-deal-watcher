FROM python:3.13-slim@sha256:7c61056e61ac89e852de05f3dc6fa51a6dd2181797bceed46aa725dd7cb2cd3b
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/data
WORKDIR /app
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock && groupadd -g 10001 watcher && useradd -u 10001 -g watcher -M watcher && mkdir /data /backups && chown watcher:watcher /data /backups
COPY --chown=watcher:watcher app ./app
COPY --chown=watcher:watcher scripts ./scripts
COPY --chown=watcher:watcher tests ./tests
USER 10001:10001
EXPOSE 8765
CMD ["python", "-m", "uvicorn", "app.web:app", "--host", "0.0.0.0", "--port", "8765", "--no-access-log"]
