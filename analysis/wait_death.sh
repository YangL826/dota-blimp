#!/bin/bash
# 等新的死亡记录出现（按修改时间找最新的，最多等 ~165 秒）
cd "$(dirname "$0")/.."
touch -a analysis/.seen 2>/dev/null
for i in $(seq 1 55); do
  n=$(ls -dt deaths/*_death 2>/dev/null | head -1)
  last=$(cat analysis/.seen 2>/dev/null)
  if [ -n "$n" ] && [ "$n" != "$last" ] && [ -f "$n/log.csv" ]; then sleep 2; echo "NEW $n"; echo "$n" > analysis/.seen; tail -3 scores.csv; exit 0; fi
  sleep 3
done
echo "none yet"; tail -3 bot_log.txt
