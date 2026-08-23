
# Architect Blueprint Production Pipeline V1 — Handoff

## What is automated now
- Intake validation
- FULL/PARTIAL mode decision
- Existing validated chart-record ingestion
- Raw AstrologyAPI bundle normalization
- Live known-time AstrologyAPI calls
- Live unknown-time conservative multi-sample stability strategy
- Detailed Content Library lookup
- Wrong-sign filtering
- Selector scoring
- Source trace
- Personalization Context Builder
- Deterministic source-bound report generation
- Optional AI HTTP writing adapter that receives ONLY the locked context
- PDF rendering
- Word-count QA
- Page-density QA
- PARTIAL omission QA
- Source-boundary QA
- Per-run manifest and machine-readable artifacts

## Regression proof
T01 FULL:
- selector VALID
- source boundary PASS
- 10,165 words
- 31 pages
- final regression status PASS

T02 synthetic PARTIAL:
- selector VALID
- Rising OMITTED_BY_MODE
- Houses OMITTED_BY_MODE
- source boundary PASS
- 8,333 words
- 26 pages
- final regression status PASS

The T02 chart values are synthetic and exist only to test unknown-time mode gating.

## One production run creates
00_manifest.json
01_chart_record.json
02_selector_trace.json
03_personalization_context.json
04_report_payload.json
05_architect_blueprint.pdf
06_qa.json

## Premium AI writer
The pipeline ships with a deterministic writer so the system can run end-to-end without allowing the writing stage to invent unselected astrology.

For premium prose, use:
`--writer ai-http --ai-endpoint <your secure writer endpoint>`

The AI endpoint is sent only:
- the locked personalization context
- the writing contract
- the report ID

It is NOT sent:
- raw provider payloads
- the full unfiltered library
- unavailable Rising/houses in PARTIAL mode

## Launch rule
Do not send a customer PDF unless `00_manifest.json` says `PASS`.
