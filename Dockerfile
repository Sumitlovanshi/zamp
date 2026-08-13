FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .
# the gallery, the ground truth and the published evidence ship in the image:
# the deployed app needs no database, no volume and no network to render
COPY samples ./samples
COPY eval/summary.json ./eval/summary.json
EXPOSE 8080
# shell form so Railway's injected $PORT is honored; 8080 for local docker run
CMD uvicorn tallyproof.app.main:app --app-dir src --host 0.0.0.0 --port ${PORT:-8080}
