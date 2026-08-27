
#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from pathlib import Path

from architect_engine.intake import validate_intake
from architect_engine.normalizer import normalize_provider_bundle
from architect_engine.provider import fetch_live_bundle
from architect_engine.selector import select_sources
from architect_engine.context_builder import build_context
from architect_engine.writer import compose_report
from architect_engine.ai_writer_adapter import compose_report_with_ai
from architect_engine.renderer import render_pdf
from architect_engine.qa import run_qa

def load_json(path): return json.loads(Path(path).read_text())
def save_json(path,obj): Path(path).write_text(json.dumps(obj,indent=2))

def main():
    ap=argparse.ArgumentParser(description="Architect Blueprint automated production pipeline V1")
    ap.add_argument("--intake", required=True)
    ap.add_argument("--chart-record")
    ap.add_argument("--provider-bundle")
    ap.add_argument("--live-provider", action="store_true")
    ap.add_argument("--writer", choices=["deterministic","ai-http"], default="deterministic")
    ap.add_argument("--ai-endpoint")
    ap.add_argument("--config", default="config/pipeline_config.json")
    ap.add_argument("--out-dir", default="outputs/run")
    args=ap.parse_args()

    base=Path(__file__).resolve().parent
    cfg=load_json(base/args.config)
    intake=load_json(args.intake)
    iv=validate_intake(intake)
    if iv["status"]!="VALID":
        raise SystemExit("INTAKE INVALID: "+", ".join(iv["errors"]))
    out=Path(args.out_dir); out.mkdir(parents=True,exist_ok=True)
    slug="".join(ch.lower() if ch.isalnum() else "_" for ch in intake["customer_name"]).strip("_")

    if args.chart_record:
        chart=load_json(args.chart_record)
    else:
        if args.provider_bundle:
            raw=load_json(args.provider_bundle)
        elif args.live_provider:
            raw=fetch_live_bundle(intake,cfg)
        else:
            raise SystemExit("Provide --chart-record, --provider-bundle, or --live-provider")
        chart=normalize_provider_bundle(raw,intake,f"ACR_{slug}")
    save_json(out/"01_chart_record.json",chart)

    selector=select_sources(chart,str(base/cfg["content_library"]),cfg["library_sheet"])
    save_json(out/"02_selector_trace.json",selector)

    context=build_context(chart,selector,f"CTX_{slug}")
    save_json(out/"03_personalization_context.json",context)

    if args.writer=="ai-http":
        endpoint=args.ai_endpoint or cfg.get("ai_writer",{}).get("http_endpoint","")
        report=compose_report_with_ai(context,f"RPT_{slug}",endpoint,cfg.get("ai_writer",{}).get("token_env","ARCHITECT_AI_TOKEN"))
    else:
        report=compose_report(context,f"RPT_{slug}")
    save_json(out/"04_report_payload.json",report)

    pdf=out/"05_architect_blueprint.pdf"
    pages,render_diagnostics=render_pdf(report,str(pdf),return_diagnostics=True)
    qa=run_qa(
        chart,selector,context,report,cfg,
        rendered_pages=pages,render_diagnostics=render_diagnostics
    )
    save_json(out/"06_qa.json",qa)

    final_pass=(
        qa["status"]=="PASS" and qa["word_target"]["status"]=="PASS"
        and qa["page_target"]["status"]=="PASS" and qa["source_boundary"]=="PASS"
    )
    manifest={
        "pipeline_version":cfg["pipeline_version"],
        "customer":intake["customer_name"],
        "mode":chart["calculation"]["mode"],
        "writer":args.writer,
        "status":"PASS" if final_pass else "REVIEW_REQUIRED",
        "artifacts":{
            "chart_record":"01_chart_record.json","selector_trace":"02_selector_trace.json",
            "personalization_context":"03_personalization_context.json","report_payload":"04_report_payload.json",
            "pdf":"05_architect_blueprint.pdf","qa":"06_qa.json"
        }
    }
    save_json(out/"00_manifest.json",manifest)
    print(json.dumps(manifest,indent=2))

if __name__=="__main__":
    main()
