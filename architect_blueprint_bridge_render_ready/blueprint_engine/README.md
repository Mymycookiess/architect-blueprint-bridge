
# The Architect Blueprint — Reusable Production Pipeline V1

This package turns the successful T01 test into a reusable production workflow.

## Pipeline
1. Intake validation
2. Chart calculation / chart-record ingestion
3. AstrologyAPI normalization
4. FULL vs PARTIAL mode gating
5. Detailed Content Library selector
6. Source trace
7. Personalization Context Builder
8. Source-bound report composer
9. Architect-style PDF rendering
10. End-to-end QA + manifest

## Production rules built in
- Unknown birth time => PARTIAL mode.
- PARTIAL mode never exposes Rising or houses.
- Content selection is restricted to `Audit Status = KEEP`.
- Wrong-sign placement rows are rejected.
- Dynamic templates are only allowed when an exact placement/sign match exists.
- The report can only cite/use source IDs that exist in the locked selector trace.
- Raw provider payloads never enter the writing stage.
- Superseded T01 values such as Los Angeles, UTC-7, 3.66°, and 5.86° are QA-blocked.

## Run with an existing validated chart record
From this folder:

```bash
python pipeline.py   --intake fixtures/T01_intake.json   --chart-record fixtures/T01_FULL_Architect_Chart_Record_CORRECTED.json   --out-dir outputs/T01_regression
```

## Run from a raw provider bundle
```bash
python pipeline.py   --intake path/to/customer_intake.json   --provider-bundle path/to/provider_bundle.json   --out-dir outputs/customer_name
```

## Live AstrologyAPI mode
Set the environment variables configured in `config/pipeline_config.json`, then:

```bash
python pipeline.py   --intake path/to/customer_intake.json   --live-provider   --out-dir outputs/customer_name
```

Live provider mode is currently implemented for known birth times. Unknown-time PARTIAL provider calculation should use the deterministic multi-time stability strategy from Phase 2C before live launch.

## Output folder
Every run creates:
- `00_manifest.json`
- `01_chart_record.json`
- `02_selector_trace.json`
- `03_personalization_context.json`
- `04_report_payload.json`
- `05_architect_blueprint.pdf`
- `06_qa.json`

## Important production note
The built-in writer is a source-bound deterministic composer. This is intentional: it proves the pipeline can complete without introducing unselected astrology content.

For the premium prose experience, replace `architect_engine/writer.py` with an AI writer adapter that is given **only** `03_personalization_context.json`. Keep the same QA boundary: the AI must never receive raw provider responses or the entire library.

## Current readiness
- T01 regression path: implemented
- Selector/source trace: implemented
- FULL/PARTIAL gating: implemented
- Deterministic report output: implemented
- PDF renderer: implemented
- Final QA manifest: implemented
- Live known-time AstrologyAPI hook: implemented, requires credentials
- Live unknown-time stability calculator: implemented (conservative 4-sample strategy)
- Premium AI prose adapter: implemented as a source-bound HTTP adapter; requires your chosen secure model endpoint/token
- T01 FULL regression: PASS — 10,165 words / 31 pages
- T02 synthetic PARTIAL regression: PASS — 8,333 words / 26 pages; Rising and houses omitted
