#!/usr/bin/env bash
set -e
if [ "$#" -lt 2 ]; then
  echo "Usage: ./produce_customer.sh <intake.json> <output_folder> [chart_record.json]"
  exit 1
fi
INTAKE="$1"
OUT="$2"
CHART="${3:-}"
cd "$(dirname "$0")"
if [ -n "$CHART" ]; then
  python pipeline.py --intake "$INTAKE" --chart-record "$CHART" --out-dir "$OUT"
else
  python pipeline.py --intake "$INTAKE" --live-provider --out-dir "$OUT"
fi
