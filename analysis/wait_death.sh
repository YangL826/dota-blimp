#!/bin/bash
# wait until a death folder newer than marker appears (max ~165s)
cd "$(dirname "$0")/.."
touch -a analysis/.seen 2>/dev/null
for i in $(seq 1 55); do
  n=$(ls -d deaths/*_death 2>/dev/null | sort | tail -1)
  last=$(cat analysis/.seen 2>/dev/null)
  if [ -n "$n" ] && [ "$n" != "$last" ] && [ -f "$n/log.csv" ]; then sleep 2; echo "NEW $n"; echo "$n" > analysis/.seen; tail -3 scores.csv; exit 0; fi
  sleep 3
done
echo "none yet"; tail -3 bot_log.txt
