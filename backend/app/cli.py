"""Operator CLI (run inside the container):

  python -m app.cli setup-token                # print a fresh one-time setup token (only if no owner exists)
  python -m app.cli reset-owner-password       # recovery: set a temporary owner password
  python -m app.cli migrate [--seed owner|demo]
  python -m app.cli index-help
  python -m app.cli replay-erasure-ledger [--path FILE]
  python -m app.cli verify-evidence            # recompute frozen-evidence hashes (used by restore); exit 1 on failure
  python -m app.cli purge
  python -m app.cli openapi                    # print the OpenAPI document (for frontend type generation)
"""

import argparse
import json
import sys
from pathlib import Path

from app.config import get_settings
from app.core.db import db_session
from app.core.logging import configure_logging


def cmd_setup_token(_args) -> None:
    from app.modules.identity.service import issue_setup_token

    with db_session() as db:
        token = issue_setup_token(db, force=True)
    print(token if token else "An owner account already exists; no setup token is needed.")


def cmd_reset(args) -> None:
    from app.modules.identity.service import reset_password_cli

    with db_session() as db:
        email, temp = reset_password_cli(db, args.email)
    print(f"Temporary password for {email}: {temp}\nSign in and change it immediately (Settings → Security). "
          "All sessions were signed out.")


def cmd_migrate(args) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "migrations"))
    command.upgrade(cfg, "head")
    print("Migrations applied.")
    if args.seed:
        from app.modules.help.service import index_articles
        from app.seed import seed_owner_samples, seed_reference

        with db_session() as db:
            seed_reference(db)
            n = index_articles(db)
        print(f"Reference data seeded; {n} help articles indexed.")
        if args.seed == "owner":
            from app.core.errors import AppError
            from app.modules.identity.service import bootstrap_owner

            try:
                with db_session() as db:
                    if bootstrap_owner(db):
                        print("Owner account created from OWNER_EMAIL / OWNER_PASSWORD.")
            except AppError as exc:  # e.g. weak password: fall back to the setup-token flow, never crash startup
                print(f"Owner bootstrap skipped: {exc.message} The first-run setup screen is used instead.")
            with db_session() as db:
                seed_owner_samples(db)
            print("Owner workspace samples seeded (synthetic).")
        elif args.seed == "demo":
            from app.seed_demo import seed_demo

            seed_demo()
            print("Demo workspace seeded (synthetic).")


def cmd_index_help(_args) -> None:
    from app.modules.help.service import index_articles

    with db_session() as db:
        print(f"{index_articles(db)} articles indexed.")


def cmd_replay(args) -> None:
    from app.modules.knowledge.deletion import replay_ledger

    with db_session() as db:
        result = replay_ledger(db, Path(args.path) if args.path else None)
    print(json.dumps(result))


def cmd_purge(_args) -> None:
    from app.modules.settings.data import purge

    with db_session() as db:
        print(json.dumps(purge(db)))


def cmd_verify_evidence(_args) -> None:
    from sqlalchemy import select

    from app.modules.decisions.evidence import verify
    from app.modules.decisions.models import EvidenceSnapshot

    with db_session() as db:
        results = [verify(db, s) for s in db.scalars(select(EvidenceSnapshot).where(EvidenceSnapshot.frozen.is_(True)))]
    summary = {"snapshots": len(results), "ok": sum(r["ok"] for r in results),
               "failed": sum(not r["ok"] for r in results), "items_verified": sum(r["items_verified"] for r in results),
               "items_redacted": sum(r["items_redacted"] for r in results)}
    print(json.dumps(summary))
    if summary["failed"]:
        sys.exit(1)


def cmd_openapi(_args) -> None:
    from app.main import app

    json.dump(app.openapi(), sys.stdout, indent=1)


def main() -> None:
    import app.models  # noqa: F401  (registers all tables; ORM flushes need every FK target mapped)

    configure_logging(get_settings().log_level)
    p = argparse.ArgumentParser(prog="app.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("setup-token").set_defaults(fn=cmd_setup_token)
    r = sub.add_parser("reset-owner-password")
    r.add_argument("--email")
    r.set_defaults(fn=cmd_reset)
    m = sub.add_parser("migrate")
    m.add_argument("--seed", choices=["owner", "demo"])
    m.set_defaults(fn=cmd_migrate)
    sub.add_parser("index-help").set_defaults(fn=cmd_index_help)
    rp = sub.add_parser("replay-erasure-ledger")
    rp.add_argument("--path")
    rp.set_defaults(fn=cmd_replay)
    sub.add_parser("verify-evidence").set_defaults(fn=cmd_verify_evidence)
    sub.add_parser("purge").set_defaults(fn=cmd_purge)
    sub.add_parser("openapi").set_defaults(fn=cmd_openapi)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
