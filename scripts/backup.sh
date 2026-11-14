#!/usr/bin/env bash
# eggent-plus: резервная копия данных экземпляра.
#
#   ./scripts/backup.sh <каталог-данных> <каталог-назначения>
#   пример: ./scripts/backup.sh /srv/eggent/data /srv/backup
#
# Кладёт <назначение>/eggent-data-<UTC>.tar.gz и рядом .sha256.
# Каталог данных не покидает машину; секреты внутри архива — архив не публикуется.
set -euo pipefail

data="${1:-}"
out="${2:-}"
if [[ -z "$data" || -z "$out" ]]; then
  echo "usage: $0 <data-dir> <out-dir>" >&2
  exit 2
fi
[[ -d "$data" ]] || { echo "нет каталога данных: $data" >&2; exit 2; }
mkdir -p "$out"

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
archive="$out/eggent-data-$stamp.tar.gz"

tar -czf "$archive" -C "$(cd "$data/.." && pwd)" "$(basename "$data")"
(cd "$out" && sha256sum "$(basename "$archive")" > "$(basename "$archive").sha256")

echo "готово: $archive"
cat "$archive.sha256"
