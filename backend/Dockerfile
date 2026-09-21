FROM python:3.12-slim

WORKDIR /workspace
COPY . /workspace/backend
RUN pip install --no-cache-dir "/workspace/backend[test]"

ENV PYTHONUNBUFFERED=1
