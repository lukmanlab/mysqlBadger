# MySQL Badger CLI

A command-line tool for MySQL slow query log analysis with HTML report generation.

## Installation

```bash
pip install -e .
```

## Usage

```bash
mysql-badger /path/to/mysql-slow.log
```

The HTML report will be generated in the current directory.

## Web server with MinIO

`mysql-badger-serve` lists the `*.log` files in a MinIO bucket and shows a **Generate** button per log. Generated reports are stored in the same bucket under `reports/`, so they are not regenerated on every visit.

```bash
# Needs an AIStor license saved as ./minio.license
podman-compose up --build        # or: docker compose up --build
```

Open http://localhost:8080 (MinIO console on http://localhost:9001).

| Variable | Default | Notes |
|---|---|---|
| `MINIO_ENDPOINT` | | e.g. `aistor-server:9000` |
| `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY` | | |
| `MINIO_BUCKET` | | created if missing |
| `MINIO_PREFIX` | empty | only list logs under this prefix |
| `MINIO_SECURE` | `false` | `true` for HTTPS |
| `PORT` | `8080` | |

The page has no authentication; do not expose it publicly as is.

### Uploading slow logs from the MySQL server (curl + cron)

Requires curl 7.75+ (`--aws-sigv4`). The script copies the slow log, uploads the copy as `<ip_address>_<original_name>_<date>_<time>.log` (so each upload shows up as a separate log in the list), and truncates the original only after checking that MinIO has the object with the same size.

`/usr/local/bin/upload-slow-log.sh`:

```bash
#!/bin/sh
set -eu

MINIO_URL="http://minio-host:9000"        # use https:// if TLS is enabled
BUCKET="slowlogs"
ACCESS_KEY="minioadmin"
SECRET_KEY="minioadmin"
LOG_FILE="/var/log/mysql/mysql-slow.log"

IP="$(hostname -I | cut -d' ' -f1 | tr . _)"      # e.g. 192_168_1_10
ORIGINAL="$(basename "$LOG_FILE" .log)"                # e.g. mysql-slow
NAME="${IP}_${ORIGINAL}_$(date +%Y%m%d_%H%M).log"
SNAPSHOT="$(mktemp)"
trap 'rm -f "$SNAPSHOT"' EXIT

cp "$LOG_FILE" "$SNAPSHOT"
HASH="$(sha256sum "$SNAPSHOT" | cut -d' ' -f1)"

# --fail + set -e: if the upload fails the script stops here and the log is kept
curl --fail --silent --show-error \
  -T "$SNAPSHOT" \
  --user "$ACCESS_KEY:$SECRET_KEY" \
  --aws-sigv4 "aws:amz:us-east-1:s3" \
  -H "x-amz-content-sha256: $HASH" \
  "$MINIO_URL/$BUCKET/$NAME"

# Verify: MinIO must answer 200 for the object, with exactly the size we uploaded
LOCAL_SIZE="$(wc -c < "$SNAPSHOT" | tr -d ' ')"
REMOTE_SIZE="$(curl --fail --silent --head \
  --user "$ACCESS_KEY:$SECRET_KEY" \
  --aws-sigv4 "aws:amz:us-east-1:s3" \
  -H "x-amz-content-sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855" \
  "$MINIO_URL/$BUCKET/$NAME" | tr -d '\r' | awk 'NR==1 {ok = ($2 == 200)} tolower($1)=="content-length:" {len = $2} END {if (ok) print len}')" || true
if [ "$REMOTE_SIZE" != "$LOCAL_SIZE" ]; then
  echo "Upload verification failed for $NAME (local=$LOCAL_SIZE remote=${REMOTE_SIZE:-none}); log not truncated" >&2
  exit 1
fi

# Upload verified: empty the original in place (same file, so mysqld keeps writing to it)
: > "$LOG_FILE"
```

Make it executable (`chmod 700`, since it holds the secret key) and add a cron entry, for example daily at 01:00 (`crontab -e`):

```cron
0 1 * * * /usr/local/bin/upload-slow-log.sh >> /var/log/upload-slow-log.log 2>&1
```

Notes:
- Run it as a user that can read and write the slow log (root, or a member of the `mysql` group with write permission).
- Queries logged between the copy and the truncate are lost. The window is small, but if you need zero loss, rotate instead: `mv` the log, run `mysqladmin flush-logs` (or `FLUSH SLOW LOGS`), then upload the moved file.
- Use a dedicated MinIO user with write access to the bucket instead of the root credentials.
- The upload appears in the web page on the next refresh; click **Generate** to build its report.

## Development

1. Create a virtual environment:
```bash
python -m venv .venv
source .venv/bin/activate  # On Linux/Mac
# or
.venv\Scripts\activate  # On Windows
```

2. Install development dependencies:
```bash
pip install -e ".[dev]"
```

3. Run tests:
```bash
pytest
``` 