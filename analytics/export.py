"""Combined analytics export: every table the platform produces in one Excel workbook.

    python main.py export [path]          (CLI)
    GET /api/export.xlsx                  (dashboard "Export" button)

Sheets
  Summary        KPIs, thresholds, sources, sheet index, and two charts
  Trends         every trend with its latest prediction
  Trend history  hourly mentions/engagement per trend (engagement_metrics)
  Predictions    full prediction history
  Alerts         alert log with the scores at alert time
  Content ideas  generated hooks, captions and hashtags
  Keywords       term volumes: current window vs. baseline, growth
  Activity       posts per hour per platform (last 7 days)
  Posts          most recent posts (up to 5,000) with engagement and keywords
  Pipeline runs  every collection / pipeline run with its result
"""
import datetime as dt
import io
import json
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Union

from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy import text

import config
from database.db_connection import get_engine

INK = "111210"
LIME = "CDF264"
SOFT = "F2F6E9"
MAX_POSTS = 5000

HEADER_FONT = Font(bold=True, color="FFFFFF")
HEADER_FILL = PatternFill("solid", fgColor=INK)
TITLE_FONT = Font(bold=True, size=18)
SECTION_FONT = Font(bold=True, size=12)
KPI_FILL = PatternFill("solid", fgColor=LIME)
NOTE_FONT = Font(italic=True, color="6B7066")


def _rows(conn, sql: str, **params) -> List[Dict]:
    return [dict(r) for r in conn.execute(text(sql), params).mappings()]


def _clean(value):
    """Make database values Excel-friendly."""
    if isinstance(value, dt.datetime):
        return value.astimezone(dt.timezone.utc).replace(tzinfo=None) if value.tzinfo else value
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value)
    if isinstance(value, dict):
        return json.dumps(value, default=str)
    if isinstance(value, Decimal):
        return float(value)
    return value


def _table(ws, columns: List[tuple], rows: List[Dict], note: Optional[str] = None) -> None:
    """Write a header + rows. ``columns`` is a list of (key, header, width, number_format)."""
    start = 1
    if note:
        ws.cell(row=1, column=1, value=note).font = NOTE_FONT
        start = 3
    for c, (_, header, width, _) in enumerate(columns, start=1):
        cell = ws.cell(row=start, column=c, value=header)
        cell.font, cell.fill = HEADER_FONT, HEADER_FILL
        cell.alignment = Alignment(vertical="center")
        ws.column_dimensions[get_column_letter(c)].width = width
    for r, row in enumerate(rows, start=start + 1):
        for c, (key, _, _, fmt) in enumerate(columns, start=1):
            cell = ws.cell(row=r, column=c, value=_clean(row.get(key)))
            if fmt:
                cell.number_format = fmt
    ws.freeze_panes = ws.cell(row=start + 1, column=1)
    if rows:
        ws.auto_filter.ref = f"A{start}:{get_column_letter(len(columns))}{start + len(rows)}"
    ws.sheet_view.showGridLines = False


DATE = "yyyy-mm-dd hh:mm"
PCT = "0.0"
INT = "#,##0"
DEC = "0.00"


def collect(conn) -> Dict[str, List[Dict]]:
    d = config.section("detection")
    current = int(d.get("current_window_hours", 3))
    span = int(d.get("baseline_window_hours", 24)) + current
    return {
        "trends": _rows(conn, """
            SELECT t.id, t.trend_name, t.source, t.platforms, t.is_active, t.detected_at, t.last_seen_at, t.z_score,
                   p.trend_score, p.virality_probability, p.trend_momentum, p.estimated_lifespan_days, p.model,
                   p.predicted_at, t.description,
                   (SELECT COUNT(*) FROM alerts a WHERE a.trend_id = t.id) AS alerts,
                   (SELECT COUNT(*) FROM content_ideas c WHERE c.trend_id = t.id) AS ideas
            FROM trends t LEFT JOIN latest_trend_predictions p ON p.trend_id = t.id
            ORDER BY t.is_active DESC, p.virality_probability DESC NULLS LAST"""),
        "history": _rows(conn, """
            SELECT t.trend_name, m.timestamp, m.mentions, m.total_engagement, m.growth_rate
            FROM engagement_metrics m JOIN trends t ON t.id = m.trend_id
            ORDER BY t.trend_name, m.timestamp"""),
        "predictions": _rows(conn, """
            SELECT t.trend_name, p.predicted_at, p.trend_score, p.virality_probability, p.trend_momentum,
                   p.estimated_lifespan_days, p.model
            FROM trend_predictions p JOIN trends t ON t.id = p.trend_id
            ORDER BY p.predicted_at DESC"""),
        "alerts": _rows(conn, """
            SELECT a.alerted_at, t.trend_name, a.alert_type, a.channels_sent, t.platforms,
                   (SELECT trend_score FROM trend_predictions p WHERE p.trend_id = a.trend_id
                      AND p.predicted_at <= a.alerted_at ORDER BY p.predicted_at DESC LIMIT 1) AS score_at_alert,
                   (SELECT virality_probability FROM trend_predictions p WHERE p.trend_id = a.trend_id
                      AND p.predicted_at <= a.alerted_at ORDER BY p.predicted_at DESC LIMIT 1) AS virality_at_alert
            FROM alerts a JOIN trends t ON t.id = a.trend_id ORDER BY a.alerted_at DESC"""),
        "ideas": _rows(conn, """
            SELECT c.generated_at, t.trend_name, c.suggested_format, c.hook, c.suggested_caption,
                   c.suggested_hashtags, c.generator
            FROM content_ideas c JOIN trends t ON t.id = c.trend_id ORDER BY c.generated_at DESC"""),
        "keywords": _rows(conn, """
            WITH w AS (
                SELECT word,
                       SUM(mentions) FILTER (WHERE bucket >= date_trunc('hour', now()) - make_interval(hours => :c - 1))
                           AS cur,
                       SUM(mentions) FILTER (WHERE bucket < date_trunc('hour', now()) - make_interval(hours => :c - 1))
                           AS base,
                       COUNT(DISTINCT platform) AS platforms
                FROM keyword_mentions
                WHERE bucket >= date_trunc('hour', now()) - make_interval(hours => :span - 1)
                GROUP BY word)
            SELECT w.word, COALESCE(cur, 0) AS current, COALESCE(base, 0) AS baseline, platforms,
                   ROUND(((COALESCE(cur, 0) + 1.0) / (COALESCE(base, 0) * :c / GREATEST(:span - :c, 1) + 1.0))::numeric, 2)
                       AS growth,
                   k.frequency AS lifetime_mentions, k.first_seen, k.last_seen
            FROM w LEFT JOIN keywords k ON k.word = w.word
            ORDER BY current DESC, growth DESC LIMIT 2000""", c=current, span=span),
        "activity": _rows(conn, """
            WITH hours AS (
                SELECT generate_series(date_trunc('hour', now()) - interval '167 hours', date_trunc('hour', now()),
                                       interval '1 hour') AS bucket)
            SELECT h.bucket,
                   COUNT(p.id) FILTER (WHERE p.platform = 'reddit') AS reddit,
                   COUNT(p.id) FILTER (WHERE p.platform = 'twitter') AS twitter,
                   COUNT(p.id) FILTER (WHERE p.platform = 'youtube') AS youtube,
                   COUNT(p.id) FILTER (WHERE p.platform = 'google_trends') AS google_trends,
                   COUNT(p.id) AS total
            FROM hours h LEFT JOIN posts p ON date_trunc('hour', COALESCE(p.posted_at, p.collected_at)) = h.bucket
            GROUP BY h.bucket ORDER BY h.bucket"""),
        "posts": _rows(conn, """
            SELECT id, platform, posted_at, collected_at, author, COALESCE(NULLIF(title, ''), body) AS text,
                   likes, comments, shares, views, engagement_score, keywords, url
            FROM posts ORDER BY COALESCE(posted_at, collected_at) DESC LIMIT :n""", n=MAX_POSTS),
        "runs": _rows(conn, """
            SELECT started_at, task, trigger, status, EXTRACT(EPOCH FROM (finished_at - started_at)) AS duration_s,
                   summary, error
            FROM pipeline_runs ORDER BY started_at DESC"""),
        "counts": _rows(conn, """
            SELECT (SELECT COUNT(*) FROM posts) AS posts_total,
                   (SELECT COUNT(*) FROM posts WHERE collected_at > now() - interval '24 hours') AS posts_24h,
                   (SELECT COUNT(*) FROM trends) AS trends_total,
                   (SELECT COUNT(*) FROM trends WHERE is_active) AS trends_active,
                   (SELECT COUNT(*) FROM alerts) AS alerts_total,
                   (SELECT COUNT(*) FROM alerts WHERE alerted_at > now() - interval '24 hours') AS alerts_24h,
                   (SELECT COUNT(*) FROM content_ideas) AS ideas_total,
                   (SELECT COUNT(*) FROM keywords) AS keywords_tracked,
                   (SELECT COUNT(*) FROM pipeline_runs) AS runs_total,
                   (SELECT COUNT(*) FROM pipeline_runs WHERE status = 'failed') AS runs_failed""")[0],
    }


SHEETS = [
    ("Trends", "trends", "Every trend with its latest prediction. Scores are 0-100.", [
        ("id", "ID", 6, None), ("trend_name", "Trend", 30, None), ("source", "Source", 15, None),
        ("platforms", "Platforms", 24, None), ("is_active", "Active", 8, None),
        ("trend_score", "Trend score", 12, PCT), ("virality_probability", "Virality %", 11, PCT),
        ("trend_momentum", "Momentum", 11, "0.000"), ("estimated_lifespan_days", "Lifespan (days)", 14, None),
        ("z_score", "Spike z-score", 12, DEC), ("alerts", "Alerts", 8, None), ("ideas", "Ideas", 8, None),
        ("detected_at", "Detected (UTC)", 17, DATE), ("last_seen_at", "Last seen (UTC)", 17, DATE),
        ("predicted_at", "Last scored (UTC)", 17, DATE), ("model", "Model", 16, None),
        ("description", "Signal", 80, None)]),
    ("Trend history", "history", "Hourly mentions and engagement per trend (input to the prediction model).", [
        ("trend_name", "Trend", 30, None), ("timestamp", "Hour (UTC)", 17, DATE), ("mentions", "Mentions", 10, INT),
        ("total_engagement", "Engagement", 12, INT), ("growth_rate", "Growth vs prev hour", 18, DEC)]),
    ("Predictions", "predictions", "Every score the prediction agent produced (newest first).", [
        ("trend_name", "Trend", 30, None), ("predicted_at", "Scored at (UTC)", 17, DATE),
        ("trend_score", "Trend score", 12, PCT), ("virality_probability", "Virality %", 11, PCT),
        ("trend_momentum", "Momentum", 11, "0.000"), ("estimated_lifespan_days", "Lifespan (days)", 14, None),
        ("model", "Model", 18, None)]),
    ("Alerts", "alerts", "Alerts sent when a trend crossed both thresholds.", [
        ("alerted_at", "Sent at (UTC)", 17, DATE), ("trend_name", "Trend", 30, None),
        ("score_at_alert", "Score at alert", 13, PCT), ("virality_at_alert", "Virality at alert %", 17, PCT),
        ("channels_sent", "Channels", 22, None), ("platforms", "Platforms", 24, None), ("alert_type", "Type", 15, None)]),
    ("Content ideas", "ideas", "Generated content angles for high-potential trends.", [
        ("generated_at", "Generated (UTC)", 17, DATE), ("trend_name", "Trend", 26, None),
        ("suggested_format", "Format", 24, None), ("hook", "Hook", 50, None), ("suggested_caption", "Caption", 70, None),
        ("suggested_hashtags", "Hashtags", 34, None), ("generator", "Generator", 14, None)]),
    ("Keywords", "keywords", "Term volume in the current window vs. the baseline average (growth = x times usual).", [
        ("word", "Term", 30, None), ("current", "Current window", 14, INT), ("baseline", "Baseline total", 14, INT),
        ("growth", "Growth (x)", 11, DEC), ("platforms", "Platforms", 10, None),
        ("lifetime_mentions", "Lifetime mentions", 16, INT), ("first_seen", "First seen (UTC)", 17, DATE),
        ("last_seen", "Last seen (UTC)", 17, DATE)]),
    ("Activity", "activity", "Posts per hour per platform, last 7 days.", [
        ("bucket", "Hour (UTC)", 17, DATE), ("reddit", "Reddit", 10, INT), ("twitter", "X", 10, INT),
        ("youtube", "YouTube", 10, INT), ("google_trends", "Google Trends", 14, INT), ("total", "Total", 10, INT)]),
    ("Posts", "posts", f"Most recent posts (up to {MAX_POSTS:,}).", [
        ("id", "ID", 8, None), ("platform", "Platform", 13, None), ("posted_at", "Posted (UTC)", 17, DATE),
        ("author", "Author", 18, None), ("text", "Text", 70, None), ("likes", "Likes", 9, INT),
        ("comments", "Comments", 10, INT), ("shares", "Shares", 9, INT), ("views", "Views", 11, INT),
        ("engagement_score", "Engagement score", 15, DEC), ("keywords", "Keywords", 50, None), ("url", "URL", 40, None),
        ("collected_at", "Collected (UTC)", 17, DATE)]),
    ("Pipeline runs", "runs", "Every collection and pipeline run.", [
        ("started_at", "Started (UTC)", 17, DATE), ("task", "Task", 16, None), ("trigger", "Trigger", 12, None),
        ("status", "Status", 10, None), ("duration_s", "Duration (s)", 12, DEC), ("summary", "Result", 80, None),
        ("error", "Error", 40, None)]),
]


def _summary(ws, data: Dict, generated: dt.datetime) -> None:
    t = config.section("thresholds")
    d = config.section("detection")
    c = data["counts"]
    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 22
    ws.column_dimensions["C"].width = 4
    ws.column_dimensions["D"].width = 30
    ws.column_dimensions["E"].width = 14
    ws.column_dimensions["F"].width = 14

    ws["A1"] = "Trend Intelligence · Analytics export"
    ws["A1"].font = TITLE_FONT
    ws["A2"] = (f"Generated {generated:%Y-%m-%d %H:%M} UTC · "
                f"{'demo data' if config.demo_mode_enabled() else 'live sources'}")
    ws["A2"].font = NOTE_FONT

    ws["A4"] = "Key figures"
    ws["A4"].font = SECTION_FONT
    kpis = [("Posts stored", c["posts_total"]), ("Posts collected · last 24h", c["posts_24h"]),
            ("Trends detected (all time)", c["trends_total"]), ("Active trends", c["trends_active"]),
            ("Alerts sent (all time)", c["alerts_total"]), ("Alerts · last 24h", c["alerts_24h"]),
            ("Content ideas", c["ideas_total"]), ("Keywords tracked", c["keywords_tracked"]),
            ("Pipeline / collection runs", c["runs_total"]), ("Failed runs", c["runs_failed"])]
    for i, (k, v) in enumerate(kpis, start=5):
        ws.cell(row=i, column=1, value=k)
        cell = ws.cell(row=i, column=2, value=v)
        cell.number_format, cell.font, cell.fill = INT, Font(bold=True), KPI_FILL

    r = 5 + len(kpis) + 1
    ws.cell(row=r, column=1, value="Settings used").font = SECTION_FONT
    settings = [
        ("Alert: trend score ≥", config.as_percent(t.get("trend_score_alert_threshold", 80))),
        ("Alert: virality ≥ (%)", config.as_percent(t.get("virality_probability_alert_threshold", 70))),
        ("Content ideas: virality ≥ (%)", config.as_percent(t.get("insight_virality_threshold", 60))),
        ("Spike: z-score ≥", d.get("z_score_threshold")), ("Spike: or growth ≥ (x)", d.get("growth_ratio_threshold")),
        ("Current window (h)", d.get("current_window_hours")), ("Baseline window (h)", d.get("baseline_window_hours")),
    ]
    for i, (k, v) in enumerate(settings, start=r + 1):
        ws.cell(row=i, column=1, value=k)
        ws.cell(row=i, column=2, value=v).font = Font(bold=True)

    r = r + len(settings) + 2
    ws.cell(row=r, column=1, value="Sheets in this file").font = SECTION_FONT
    for i, (name, _, note, _) in enumerate(SHEETS, start=r + 1):
        ws.cell(row=i, column=1, value=name).font = Font(bold=True, color=INK)
        ws.cell(row=i, column=2, value=note).font = NOTE_FONT

    # Top active trends table (feeds the chart)
    ws["D4"] = "Top active trends"
    ws["D4"].font = SECTION_FONT
    for col, h in zip("DEF", ("Trend", "Virality %", "Trend score")):
        cell = ws[f"{col}5"]
        cell.value, cell.font, cell.fill = h, HEADER_FONT, HEADER_FILL
    top = [t_ for t_ in data["trends"] if t_["is_active"] and t_["virality_probability"] is not None][:10]
    for i, tr in enumerate(top, start=6):
        ws.cell(row=i, column=4, value=tr["trend_name"])
        ws.cell(row=i, column=5, value=round(tr["virality_probability"], 1)).number_format = PCT
        ws.cell(row=i, column=6, value=round(tr["trend_score"], 1)).number_format = PCT
    if top:
        chart = BarChart()
        chart.type, chart.style, chart.title = "bar", 10, "Top trends: virality vs. trend score"
        chart.add_data(Reference(ws, min_col=5, max_col=6, min_row=5, max_row=5 + len(top)), titles_from_data=True)
        chart.set_categories(Reference(ws, min_col=4, min_row=6, max_row=5 + len(top)))
        chart.y_axis.scaling.min, chart.y_axis.scaling.max = 0, 100
        chart.height, chart.width = 7.5, 16
        chart.series[0].graphicalProperties.solidFill = LIME
        chart.series[1].graphicalProperties.solidFill = INK
        ws.add_chart(chart, "H4")


def _activity_chart(ws, n_rows: int) -> None:
    if not n_rows:
        return
    start = 3  # header row (note in row 1)
    chart = BarChart()
    chart.type, chart.grouping, chart.overlap = "col", "stacked", 100
    chart.title, chart.height, chart.width = "Posts per hour by platform", 8, 26
    chart.add_data(Reference(ws, min_col=2, max_col=5, min_row=start, max_row=start + n_rows), titles_from_data=True)
    chart.set_categories(Reference(ws, min_col=1, min_row=start + 1, max_row=start + n_rows))
    for s, color in zip(chart.series, (INK, "B9E34A", "6B7066", "C9CCC3")):
        s.graphicalProperties.solidFill = color
    chart.x_axis.number_format = "dd hh:mm"
    ws.add_chart(chart, "H3")


def build_workbook(target: Union[str, Path, io.BytesIO, None] = None) -> Union[Path, io.BytesIO]:
    """Write the analytics workbook to ``target`` (path or buffer). Returns the target."""
    engine = get_engine()
    with engine.connect() as conn:
        data = collect(conn)
    generated = dt.datetime.now(dt.timezone.utc)

    wb = Workbook()
    summary = wb.active
    summary.title = "Summary"
    _summary(summary, data, generated)
    for name, key, note, columns in SHEETS:
        ws = wb.create_sheet(name)
        _table(ws, columns, data[key], note=note)
        if key == "activity":
            _activity_chart(ws, len(data[key]))

    if target is None:
        target = Path(f"trend-analytics-{generated:%Y%m%d-%H%M}.xlsx")
    wb.save(target)
    return target
