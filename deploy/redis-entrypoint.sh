#!/bin/sh
# Redis 启动入口：将 REDIS_PASSWORD 写入 tmpfs 中权限受限的运行配置后再启动，
# 密码不进入命令行参数、镜像层或日志。容器以 redis 用户(999)只读根文件系统运行。
set -eu

: "${REDIS_PASSWORD:?REDIS_PASSWORD is required}"
POLICY=${REDIS_MAXMEMORY_POLICY:-noeviction}
case "$POLICY" in
  noeviction|allkeys-lru) ;;
  *) printf 'Unsupported Redis memory policy\n' >&2; exit 1 ;;
esac

CONFIG_DIR=/run/xunke-redis
CONFIG_FILE="$CONFIG_DIR/redis.conf"
umask 077
{
  printf 'bind 0.0.0.0\n'
  printf 'port 6379\n'
  printf 'requirepass %s\n' "$REDIS_PASSWORD"
  printf 'maxmemory 128mb\n'
  printf 'maxmemory-policy %s\n' "$POLICY"
  printf 'save ""\n'
  printf 'appendonly no\n'
  printf 'dir /tmp\n'
} > "$CONFIG_FILE"
chmod 600 "$CONFIG_FILE"

exec redis-server "$CONFIG_FILE"
