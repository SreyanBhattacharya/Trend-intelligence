"""Trend Intelligence Platform command-line interface.

    python main.py init-db            create / upgrade the database schema
    python main.py collect [SOURCE]   collect once (all | reddit | twitter | youtube | google_trends | demo)
    python main.py run-once           collect from every source, then run the full pipeline once
    python main.py schedule           run continuously with the built-in scheduler (no Celery needed)
    python main.py report             show the current top trends
"""
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def cmd_init_db(_args):
    from database.db_connection import init_db

    init_db()
    print("Database schema is up to date.")


def cmd_collect(args):
    from workflows.pipeline import collect

    print(collect(args.source))


def cmd_run_once(args):
    from database.db_connection import init_db
    from workflows.pipeline import collect, run_pipeline

    init_db()
    if args.demo:
        import os

        os.environ["DEMO_MODE"] = "true"
    print("Collected:", collect("all"))
    print("Pipeline:", run_pipeline())


def cmd_schedule(_args):
    from database.db_connection import init_db
    from workflows import scheduler

    init_db()
    scheduler.main()


def cmd_report(args):
    from sqlalchemy import text

    from database.db_connection import get_engine

    rows = get_engine().connect().execute(text("""
        SELECT t.trend_name, t.source, array_to_string(t.platforms, ',') AS platforms,
               p.trend_score, p.virality_probability, p.trend_momentum, p.estimated_lifespan_days,
               (SELECT COUNT(*) FROM alerts a WHERE a.trend_id = t.id) AS alerts
        FROM trends t JOIN latest_trend_predictions p ON p.trend_id = t.id
        WHERE t.is_active
        ORDER BY p.virality_probability DESC, p.trend_score DESC
        LIMIT :limit
    """), {"limit": args.limit}).mappings().fetchall()
    if not rows:
        print("No scored trends yet. Run: python main.py run-once")
        return
    print(f"{'Trend':32} {'Source':14} {'Platforms':24} {'Score':>6} {'Viral%':>7} {'Mom':>6} {'Days':>4} {'Alerts':>6}")
    for r in rows:
        print(f"{r['trend_name'][:32]:32} {r['source'] or '':14} {(r['platforms'] or '')[:24]:24} "
              f"{r['trend_score']:6.1f} {r['virality_probability']:7.1f} {r['trend_momentum']:6.2f} "
              f"{r['estimated_lifespan_days']:4d} {r['alerts']:6d}")


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    parser = argparse.ArgumentParser(description="Trend Intelligence Platform")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("init-db", help="create or upgrade the database schema").set_defaults(func=cmd_init_db)

    p = sub.add_parser("collect", help="collect data once")
    p.add_argument("source", nargs="?", default="all",
                   choices=["all", "reddit", "twitter", "youtube", "google_trends", "demo"])
    p.set_defaults(func=cmd_collect)

    p = sub.add_parser("run-once", help="collect + run the full pipeline once")
    p.add_argument("--demo", action="store_true", help="force synthetic demo data")
    p.set_defaults(func=cmd_run_once)

    sub.add_parser("schedule", help="run continuously without Celery").set_defaults(func=cmd_schedule)

    p = sub.add_parser("report", help="print the top active trends")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(func=cmd_report)

    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 1
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
