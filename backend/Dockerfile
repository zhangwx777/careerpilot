FROM python:3.12-slim

WORKDIR /workspace
COPY requirements.lock /workspace/backend/requirements.lock
RUN pip install --no-cache-dir -r /workspace/backend/requirements.lock setuptools==84.0.0
COPY . /workspace/backend
RUN pip install --no-cache-dir --no-deps --no-build-isolation "/workspace/backend[test]" \
    && pip check

ENV PYTHONUNBUFFERED=1
