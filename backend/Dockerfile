FROM python:3.12-slim

WORKDIR /workspace
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && install -d /usr/share/postgresql-common/pgdg \
    && python -c "from urllib.request import urlretrieve; urlretrieve('https://www.postgresql.org/media/keys/ACCC4CF8.asc', '/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc')" \
    && . /etc/os-release \
    && printf 'Types: deb\nURIs: https://apt.postgresql.org/pub/repos/apt\nSuites: %s-pgdg\nArchitectures: %s\nComponents: main\nSigned-By: /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc\n' \
        "$VERSION_CODENAME" "$(dpkg --print-architecture)" \
        > /etc/apt/sources.list.d/pgdg.sources \
    && apt-get update \
    && apt-get install -o Acquire::Retries=4 -y --no-install-recommends postgresql-client-18 \
    && pg_dump --version | grep -E ' 18\.' \
    && pg_restore --version | grep -E ' 18\.' \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.lock /workspace/backend/requirements.lock
RUN pip install --no-cache-dir -r /workspace/backend/requirements.lock setuptools==84.0.0
COPY . /workspace/backend
RUN pip install --no-cache-dir --no-deps --no-build-isolation "/workspace/backend[test]" \
    && pip check

ENV PYTHONUNBUFFERED=1
