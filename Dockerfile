# MedResearch AI — container image (Phase 24).
#
# Pinned to Python 3.12 to exactly match the environment this project was
# built and tested against (see requirements.txt for pinned dependency
# versions). If this base image tag isn't available yet on your registry,
# see DEPLOYMENT.md for the Streamlit Community Cloud alternative, which
# uses whatever Python version that platform currently supports.
FROM python:3.12-slim

WORKDIR /app

# curl is only for the HEALTHCHECK below.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# The LanceDB directory is fine to be ephemeral here: the app retrieves and
# re-indexes evidence during each research run, so it never depends on this
# surviving a container restart or redeploy (see DEPLOYMENT.md).
RUN mkdir -p data/lancedb

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD curl --fail http://localhost:8501/_stcore/health || exit 1

ENTRYPOINT ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
