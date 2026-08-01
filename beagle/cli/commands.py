from __future__ import annotations

import json
import uuid
from pathlib import Path

from ..config import ConfigProvider, load_config
from ..eval.harness import EvalHarness, load_cases
from ..pipeline.events import EventStream
from ..pipeline.runner import ReviewRequest
from ..server.guide import guide_text
from ..report import render_markdown
from ..server.service import BeagleService
from .output import exit_code_for, print_doctor, print_eval, print_review, read_diff


class open_service:
    """Opens the service for a one-shot command and always closes it."""

    def __init__(self, args):
        self.path = Path(args.config)

    def __enter__(self) -> BeagleService:
        self.service = BeagleService(ConfigProvider(load_config(self.path)), self.path.parent)
        return self.service

    def __exit__(self, *exc_info) -> None:
        self.service.close()


def serve(args) -> int:
    import logging
    import uvicorn

    from ..server.app import build_app

    config = load_config(args.config).config
    # Without this only uvicorn talks, and the poller, the poster and every
    # warning about GitHub go nowhere.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    uvicorn.run(build_app(args.config), host="0.0.0.0", port=config.server.port, log_level="info")
    return 0


def index(args) -> int:
    with open_service(args) as service:
        print(json.dumps(service.run_index(full=args.full), indent=2))
    return 0


def doctor(args) -> int:
    with open_service(args) as service:
        print_doctor(service.report.doctor())
    return 0


def review(args) -> int:
    with open_service(args) as service:
        request = ReviewRequest(
            review_id=f"cli-{uuid.uuid4().hex[:8]}",
            base=args.base,
            head=args.ref,
            diff=read_diff(args.diff),
            fresh=args.fresh,
        )
        service.sync_index_for(request)
        result = service.runner().run(request, EventStream())

        if args.format == "json":
            print(json.dumps(result.to_dict(), indent=2))
        elif args.format == "md":
            print(render_markdown(result.to_dict()))
        else:
            print_review(result)
        return exit_code_for(result, service)


def evaluate(args) -> int:
    with open_service(args) as service:
        summary = EvalHarness(service).run(load_cases(args.path)).to_dict()
        if args.format == "json":
            print(json.dumps(summary, indent=2))
        else:
            print_eval(summary)
        return 0 if summary["passed"] == summary["cases"] else 1


def guide(args) -> int:
    print(guide_text(args.topic))
    return 0


COMMANDS = {
    "serve": serve,
    "index": index,
    "doctor": doctor,
    "review": review,
    "eval": evaluate,
    "guide": guide,
}
