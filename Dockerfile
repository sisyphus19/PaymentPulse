FROM python:3.11-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY config ./config
COPY pipelines ./pipelines
COPY mlops ./mlops

RUN pip install --no-cache-dir .

CMD ["python", "pipelines/run_pipeline.py"]
