import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from evals.runner import run_eval

THRESHOLDS = {
    "retrieval_hit_rate": 0.9,
    "citation_precision": 0.9,
    "answer_keyword_rate": 0.75,
    "abstain_rate": 1.0,
}


class Command(BaseCommand):
    help = "Run the golden-question eval against the configured LLM provider. Exits non-zero on regression."

    def add_arguments(self, parser):
        parser.add_argument("--verbose-cases", action="store_true", help="print every question and answer")

    def handle(self, *args, **options):
        report = run_eval()
        summary = report.as_dict()
        summary["provider"] = settings.LLM_PROVIDER
        if options["verbose_cases"]:
            for c in report.cases:
                self.stdout.write(f"- {c.question}\n    -> {c.answer}")
        self.stdout.write(json.dumps(summary, indent=2))
        failed = {k: summary[k] for k, floor in THRESHOLDS.items() if summary[k] < floor}
        if failed:
            raise CommandError(f"eval below threshold: {failed}")
        self.stdout.write(self.style.SUCCESS("eval passed"))
