#!/bin/bash
# 小说下载助手 · 守护脚本
# 用法: bash guard.sh start|stop|status
# start 后：脱离当前终端进程组独立驻留；若 server.py 意外退出会自动重启。
cd "$(dirname "$0")" || exit 1
PY="$HOME/.novelshell/bin/python"
PORT="${PORT:-8765}"
PIDFILE="/tmp/novel_guard.pid"
LOG="/tmp/novel_server.log"

is_running() {
  for pid in /proc/[0-9]*; do
    p=${pid#/proc/}
    if [ -r "$pid/cmdline" ] && tr '\0' ' ' < "$pid/cmdline" 2>/dev/null | grep -q "server.py --port $PORT"; then
      echo "$p"; return 0
    fi
  done
  return 1
}

case "$1" in
  start)
    old=$(is_running)
    if [ -n "$old" ]; then echo "已在运行 (pid $old)"; exit 0; fi
    # setsid 让守护循环脱离本终端的进程组，终端退出不再带走它
    setsid bash -c "
      while true; do
        \"$PY\" server.py --port $PORT >> \"$LOG\" 2>&1
        echo \"[\$(date '+%F %T')] server 退出，5 秒后重启\" >> \"$LOG\"
        sleep 5
      done
    " > /dev/null 2>&1 < /dev/null &
    echo $! > "$PIDFILE"
    disown 2>/dev/null || true
    sleep 3
    pid=$(is_running)
    if [ -n "$pid" ]; then
      echo "已启动 (server pid $pid, 守护 pid $(cat "$PIDFILE"))，地址 http://127.0.0.1:$PORT"
    else
      echo "启动失败，查看日志: $LOG"; tail -10 "$LOG"
    fi
    ;;
  stop)
    [ -f "$PIDFILE" ] && kill "$(cat "$PIDFILE")" 2>/dev/null && rm -f "$PIDFILE"
    # 先停守护循环，再停 server，避免被自动拉起
    for pid in /proc/[0-9]*; do
      p=${pid#/proc/}
      if [ -r "$pid/cmdline" ] && tr '\0' ' ' < "$pid/cmdline" 2>/dev/null | grep -q "server.py --port $PORT"; then
        kill "$p" 2>/dev/null && echo "已停止 server pid $p"
      fi
    done
    echo "已停止"
    ;;
  status)
    pid=$(is_running)
    if [ -n "$pid" ]; then echo "运行中 (pid $pid) http://127.0.0.1:$PORT"; else echo "未运行"; fi
    ;;
  *)
    echo "用法: bash guard.sh start|stop|status";;
esac
