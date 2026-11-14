#!/usr/bin/env bash
# Собрать тестовый экземпляр из репозитория и заменить работающий контейнер.
#
#   ./docker/deploy-test.sh [каталог-репозитория] [порт]
#
# Что делает:
#   1. берёт чистый клон upstream на теге из .github/workflows/patches.yml;
#   2. накладывает patches/*.patch по порядку;
#   3. собирает образ eggent-plus:test;
#   4. перезапускает контейнер на порту (по умолчанию 3100), данные — в томах,
#      поэтому вход и настройки переживают замену образа.
#
# Запускать на сборщике (LXC <номер>), не на машине с живым Eggent.

set -euo pipefail

repo="$(cd "${1:-$(dirname "${BASH_SOURCE[0]}")/..}" && pwd)"
port="${2:-3100}"
container="${TEST_CONTAINER:-eggent-ru}"
image="${TEST_IMAGE:-eggent-plus:test}"
data="${TEST_DATA:-$repo/testdata-ru}"
workdir="${TEST_WORKDIR:-$repo/.build}"

cd "$repo"
tag="$(sed -n 's/^  UPSTREAM_TAG: //p' .github/workflows/patches.yml | head -1)"
if [[ -z "$tag" ]]; then
  echo "не нашёл UPSTREAM_TAG в .github/workflows/patches.yml" >&2
  exit 2
fi

shopt -s nullglob
patches=(patches/*.patch)
if [[ ${#patches[@]} -eq 0 ]]; then
  echo "patches/: нет .patch" >&2
  exit 2
fi

echo "upstream $tag, патчей: ${#patches[@]}"
rm -rf "$workdir"
git clone --depth 1 --branch "$tag" https://github.com/eggent-ai/eggent.git "$workdir"
for p in "${patches[@]}"; do
  git -C "$workdir" apply --check "$repo/$p" || { echo "не ложится: $p" >&2; exit 1; }
  git -C "$workdir" apply "$repo/$p"
  echo "  + $p"
done

# Что именно попадёт в образ: тег, число патчей и коммит. Подставляется в Dockerfile
# (патч 0015) и остаётся внутри образа, поэтому цифра в настройках не может отстать
# от кода; файл в data/ ниже — отметка о развёртывании, она вторая.
commit="$(git -C "$repo" rev-parse --short HEAD 2>/dev/null || echo "")"
built_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

echo "сборка образа $image"
start=$(date +%s)
docker build -t "$image" \
  --build-arg "EGGENT_UPSTREAM_TAG=$tag" \
  --build-arg "EGGENT_PATCH_COUNT=${#patches[@]}" \
  --build-arg "EGGENT_SOURCE_COMMIT=$commit" \
  --build-arg "EGGENT_BUILT_AT=$built_at" \
  "$workdir"
echo "собрано за $(( $(date +%s) - start )) с"

mkdir -p "$data"
# Отметка о развёртывании рядом с данными. Страница настроек спрашивает сначала
# образ и только потом этот файл: он переживает замену образа, поэтому главным быть
# не может (патч 0015).
cat > "$data/build-info.json" <<JSON
{"upstream":"$tag","patches":${#patches[@]},"commit":"$commit","builtAt":"$built_at"}
JSON

# Почта: если рядом лежит настроенный адаптер (mail-data/accounts.json + adapter.env), поднимаем его
# на хосте и говорим Eggent, где он. Секреты живут в adapter.env с правами 600, не в командной строке.
mail_dir="${MAIL_DIR:-$repo/mail-data}"
mail_args=()
if [[ -f "$mail_dir/accounts.json" && -f "$mail_dir/adapter.env" ]]; then
  mode="$(stat -c %a "$mail_dir/adapter.env" 2>/dev/null || echo 600)"
  if [[ "$mode" != "600" ]]; then
    echo "$mail_dir/adapter.env открыт другим (права $mode), нужно 600" >&2
    exit 1
  fi
  # shellcheck disable=SC1091
  set -a; . "$mail_dir/adapter.env"; set +a
  pkill -f "python3 -m adapter" >/dev/null 2>&1 || true
  ( cd "$repo/mail-adapter" && EGGENT_MAIL_DIR="$mail_dir" EGGENT_MAIL_HOST=0.0.0.0 \
      nohup python3 -m adapter >"$mail_dir/adapter.log" 2>&1 & )
  echo "адаптер почты: запущен на :8787"
  # Адрес адаптера берём из adapter.env, если он там задан: адаптер может стоять
  # на отдельной машине, и тогда host.docker.internal ни при чём.
  mail_url="${EGGENT_EMAIL_API_URL:-http://host.docker.internal:8787}"
  mail_args=(
    --add-host=host.docker.internal:host-gateway
    -e "EGGENT_EMAIL_API_URL=$mail_url"
    -e "EGGENT_SERVICES_TOKEN=${EGGENT_MAIL_ADAPTER_TOKEN:-}"
    -e "EGGENT_EMAIL_ADDRESS=${EGGENT_EMAIL_ADDRESS:-}"
  )
fi

docker rm -f "$container" >/dev/null 2>&1 || true
docker run -d --name "$container" -p "$port:3000" -v "$data:/app/data" "${mail_args[@]}" "$image" >/dev/null

for _ in $(seq 1 30); do
  if docker exec "$container" node -e 'fetch("http://127.0.0.1:3000/api/health").then((r) => process.exit(r.ok ? 0 : 1)).catch(() => process.exit(1))' >/dev/null 2>&1; then
    echo "http://127.0.0.1:$port — health 200"
    exit 0
  fi
  sleep 2
done

echo "контейнер поднялся, но health не ответил за 60 с" >&2
docker logs --tail 30 "$container" >&2 || true
exit 1
