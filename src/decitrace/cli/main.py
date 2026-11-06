"""DeciTrace command-line entry point."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from decitrace.core.config import AppConfig, load_config
from decitrace.core.importer import Importer
from decitrace.core.models import RiskLevel, SourceTool
from decitrace.core.storage import Store
from decitrace.decision.models import DecisionRequest
from decitrace.decision.providers import OpenAICompatibleProvider, ProviderUnavailable
from decitrace.decision.proxy import DecisionProxy
from decitrace.decision.rules import build_rules, export_rules
from decitrace.evaluation.replay import ReplayEvaluator, write_report
from decitrace.extraction.heuristics import Extractor
from decitrace.extraction.review import apply_review, export_review


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="decitrace")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--db", type=Path, help="override SQLite database path")
    sub = parser.add_subparsers(dest="command", required=True)

    importer = sub.add_parser("import", help="import local transcripts read-only")
    importer.add_argument("--codex-root", action="append", type=Path)
    importer.add_argument("--claude-root", action="append", type=Path)
    importer.add_argument("--stepgo-root", action="append", type=Path)
    importer.add_argument("--batch-id")
    importer.add_argument("--max-files", type=int)

    sub.add_parser("extract", help="extract reviewable decision candidates")

    review_export = sub.add_parser("review-export", help="write editable decision JSONL")
    review_export.add_argument("path", type=Path)
    review_apply = sub.add_parser("review-apply", help="apply edited decision JSONL")
    review_apply.add_argument("path", type=Path)

    report = sub.add_parser("quality-report", help="emit aggregate data quality JSON")
    report.add_argument("--batch-id")
    report.add_argument("--output", type=Path)

    policy = sub.add_parser("policy-build", help="materialize personal rules")
    policy.add_argument("--include-pending", action="store_true")
    policy.add_argument("--output", type=Path)

    decide = sub.add_parser("decide", help="ask the offline Decision Proxy")
    decide.add_argument("question")
    decide.add_argument("--baseline", choices=["rule", "case", "case_llm"], default="case")
    decide.add_argument("--context")
    decide.add_argument("--option", action="append", default=[])
    decide.add_argument("--constraint", action="append", default=[])
    decide.add_argument("--risk", choices=[item.value for item in RiskLevel], default="unknown")
    decide.add_argument("--include-pending", action="store_true")

    evaluate = sub.add_parser("evaluate", help="run chronological replay benchmark")
    evaluate.add_argument("--test-fraction", type=float, default=0.3)
    evaluate.add_argument("--include-pending", action="store_true")
    evaluate.add_argument("--output-json", type=Path, required=True)
    evaluate.add_argument("--output-md", type=Path)
    return parser


def _roots(args: argparse.Namespace, config: AppConfig) -> dict[SourceTool, list[Path]]:
    return {
        SourceTool.CODEX: args.codex_root or config.sources.codex,
        SourceTool.CLAUDE: args.claude_root or config.sources.claude,
        SourceTool.STEPGO: args.stepgo_root or config.sources.stepgo,
    }


def _provider(config: AppConfig):
    if not config.llm.enabled:
        return None
    return OpenAICompatibleProvider(config.llm)


def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = load_config(args.config)
    db_path = args.db.expanduser() if args.db else config.data_dir / "decitrace.sqlite3"
    with Store(db_path) as store:
        if args.command == "import":
            _print(Importer(store).run(
                _roots(args, config), batch_id=args.batch_id, max_files=args.max_files,
            ))
        elif args.command == "extract":
            _print(Extractor(store).run())
        elif args.command == "review-export":
            _print({"exported": export_review(store, args.path), "path": str(args.path)})
        elif args.command == "review-apply":
            _print(apply_review(store, args.path))
        elif args.command == "quality-report":
            result = store.quality_report(args.batch_id)
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            _print(result)
        elif args.command == "policy-build":
            result = build_rules(store, include_pending=args.include_pending)
            if args.output:
                result["exported"] = export_rules(store, args.output)
                result["path"] = str(args.output)
            _print(result)
        elif args.command == "decide":
            request = DecisionRequest(
                question=args.question,
                project_context=args.context,
                options=args.option,
                constraints=args.constraint,
                risk=RiskLevel(args.risk),
            )
            result = DecisionProxy(
                store, include_pending=args.include_pending, provider=_provider(config),
            ).decide(request, args.baseline)
            _print(result.model_dump(mode="json"))
        elif args.command == "evaluate":
            proxy = DecisionProxy(
                store, include_pending=args.include_pending, provider=_provider(config),
            )
            result = ReplayEvaluator(store, proxy).run(test_fraction=args.test_fraction)
            write_report(result, args.output_json, args.output_md)
            _print(result)
        else:  # pragma: no cover - argparse enforces choices
            parser.error("unknown command")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
