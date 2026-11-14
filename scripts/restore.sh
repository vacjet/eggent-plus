#!/usr/bin/env bash
# eggent-plus: восстановление данных из копии, сделанной backup.sh.
#
#   ./scripts/restore.sh <архив.tar.gz> <пустой-каталог-назначения>
#
# Отказывается работать, если контрольная сумма не сходится или каталог не пуст:
# восстановление поверх живых данных — отдельное решение человека, не скрипта.
set -euo pipefail

archive="${1:-}"
target="${2:-}"
if [[ -z "$archive" || -z "$target" ]]; then
  echo "usage: $0 <archive.tar.gz> <empty-target-dir>" >&2
  exit 2
fi
[[ -f "$archive" ]] || { echo "нет архива: $archive" >&2; exit 2; }

if [[ -f "$archive.sha256" ]]; then
  (cd "$(dirname "$archive")" && sha256sum --check --status "$(basename "$archive").sha256") \
    || { echo "контрольная сумма не сходится: $archive" >&2; exit 1; }
else
  echo "внимание: $archive.sha256 нет, целостность не проверена" >&2
fi

mkdir -p "$target"
if [[ -n "$(ls -A "$target")" ]]; then
  echo "каталог назначения не пуст: $target" >&2
  exit 1
fi

tar -xzf "$archive" -C "$target"
echo "восстановлено в $target"
find "$target" -maxdepth 1 -mindepth 1 | head -20
