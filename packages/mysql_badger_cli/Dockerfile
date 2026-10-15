FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY setup.py README.md ./
COPY src ./src
COPY templates ./templates

# Editable install: the report generator resolves templates/ relative to src/
RUN pip install --no-cache-dir -e .

EXPOSE 8080

# Mount logs and the output directory here
WORKDIR /data

ENTRYPOINT ["mysql-badger"]

# Web server mode (lists slow logs in MinIO, generates reports on demand, stores them in MinIO):
#   docker run --entrypoint mysql-badger-serve -p 8080:8080 \
#     -e MINIO_ENDPOINT=minio:9000 -e MINIO_ACCESS_KEY=... -e MINIO_SECRET_KEY=... \
#     -e MINIO_BUCKET=logs [-e MINIO_PREFIX=mysql/] [-e MINIO_SECURE=true] mysql-badger
