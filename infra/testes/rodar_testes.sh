#!/usr/bin/env bash
# Roda a suíte em uma stack DESCARTÁVEL, sem tocar na produção (Git Bash, na raiz do projeto):
#
#     bash infra/testes/rodar_testes.sh                 # todos os testes
#     bash infra/testes/rodar_testes.sh -k fornecedor   # argumentos extras vão para o pytest
#
# Isolamento: projeto compose "erp-teste" (contêineres e volume próprios), imagem
# erp-giraffas/app:teste (a produção usa :latest), portas 55499/8199 e segredos
# gerados numa pasta temporária. No fim, tudo é removido, inclusive o volume.
set -euo pipefail
cd "$(dirname "$0")/../.."

TESTE_DIR="$(cygpath -m "${TEMP:-/tmp}")/erp-teste-$$"
export DATA_DIR="$TESTE_DIR" APP_VERSION=teste APP_ENV=teste POSTGRES_HOST_PORT=55499 API_HOST_PORT=8199
export MSYS_NO_PATHCONV=1
DC=(docker compose -p erp-teste)

limpar() {
  "${DC[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
  rm -rf "$TESTE_DIR"
}
trap limpar EXIT

mkdir -p "$TESTE_DIR"
py infra/secrets/gerar_segredos.py "$TESTE_DIR" >/dev/null
"${DC[@]}" build api
"${DC[@]}" up -d --wait postgres
"${DC[@]}" run --rm --no-deps -e LOGIN_MAX_FALHAS=3 api \
  sh -c 'alembic -c database/alembic.ini upgrade head && pytest -q "$@"' _ "$@"
