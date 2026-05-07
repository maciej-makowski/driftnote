#!/usr/bin/env bash
# Monthly backup: tar.zst of data/entries + config.toml.
# Writes a row into /var/driftnote/data/index.sqlite job_runs.
# Optionally encrypts the archive via age if BACKUP_ENCRYPT=true.
#
# Invoked by /etc/systemd/system/driftnote-backup.service (oneshot timer).

set -euo pipefail

DATA_ROOT="${DATA_ROOT:-/var/driftnote}"
BACKUP_DIR="$DATA_ROOT/backups"
NOW_ISO="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
MONTH_TAG="$(date -u +%Y-%m)"
ARCHIVE="$BACKUP_DIR/driftnote-$MONTH_TAG.tar.zst"
RETAIN_MONTHS="${RETAIN_MONTHS:-12}"
ENCRYPT="${BACKUP_ENCRYPT:-false}"
AGE_KEY_PATH="${AGE_KEY_PATH:-}"

mkdir -p "$BACKUP_DIR"

cd "$DATA_ROOT"
tar --zstd -cf "$ARCHIVE" config.toml data/entries

if [[ "$ENCRYPT" == "true" ]]; then
    if [[ -z "$AGE_KEY_PATH" || ! -f "$AGE_KEY_PATH" ]]; then
        echo "BACKUP_ENCRYPT=true but AGE_KEY_PATH unset/missing" >&2
        exit 2
    fi
    age -R "$AGE_KEY_PATH" -o "$ARCHIVE.age" "$ARCHIVE"
    rm -f "$ARCHIVE"
    ARCHIVE="$ARCHIVE.age"
fi

# Prune older than retention.
find "$BACKUP_DIR" -maxdepth 1 -type f \( -name 'driftnote-*.tar.zst' -o -name 'driftnote-*.tar.zst.age' \) \
    -printf '%T@ %p\n' \
  | sort -nr \
  | tail -n +"$((RETAIN_MONTHS + 1))" \
  | awk '{print $2}' \
  | xargs -r rm -f

# Record success row in SQLite.
SIZE=$(stat -c%s "$ARCHIVE")
DETAIL=$(printf '{"archive":"%s","size_bytes":%s}' "$(basename "$ARCHIVE")" "$SIZE")
sqlite3 "$DATA_ROOT/data/index.sqlite" \
    "INSERT INTO job_runs(job, started_at, finished_at, status, detail) \
     VALUES('backup', '$NOW_ISO', '$NOW_ISO', 'ok', '$DETAIL');"

echo "backup ok: $ARCHIVE ($SIZE bytes)"
