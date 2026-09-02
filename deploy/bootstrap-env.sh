#!/usr/bin/env bash
# 初始化部署私密配置。仅在 ZHIDA_ENC_KEY 缺失或仍为模板值时生成一次，绝不覆盖已有值。
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${1:-$ROOT_DIR/.env}"
TEMPLATE_FILE="$ROOT_DIR/.env.production.example"

if [[ ! -f "$ENV_FILE" ]]; then
  cp "$TEMPLATE_FILE" "$ENV_FILE"
  echo "已从生产模板创建 $ENV_FILE"
fi

chmod 600 "$ENV_FILE"
current_key="$(sed -n 's/^ZHIDA_ENC_KEY=//p' "$ENV_FILE" | tail -n 1 | tr -d '\r')"

case "$current_key" in
  ''|replace-with-*)
    new_key="$(openssl rand -hex 32)"
    tmp_file="$(mktemp "${ENV_FILE}.tmp.XXXXXX")"
    trap 'rm -f "$tmp_file"' EXIT
    awk -v key="$new_key" '
      /^ZHIDA_ENC_KEY=/ {
        if (!written) {
          print "ZHIDA_ENC_KEY=" key
          written = 1
        }
        next
      }
      { print }
      END {
        if (!written) print "ZHIDA_ENC_KEY=" key
      }
    ' "$ENV_FILE" > "$tmp_file"
    mv "$tmp_file" "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    trap - EXIT
    echo "已生成并持久化 ZHIDA_ENC_KEY。请备份 .env；后续部署与迁移均不得更换此值。"
    ;;
  *)
    echo "ZHIDA_ENC_KEY 已存在，保持不变。"
    ;;
esac
