#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
python pipeline.py --intake fixtures/T01_intake.json --chart-record fixtures/T01_FULL_Architect_Chart_Record_CORRECTED.json --out-dir outputs/T01_regression
