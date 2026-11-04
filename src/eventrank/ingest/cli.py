"""CLI tầng Thu thập: `python -m eventrank.ingest <lệnh>` (chạy bằng `uv run --group embed …`
hoặc các target `make`).

    sources sync                        configs/sources.yaml → bảng sources
    import-jsonl '<glob>' […]           nạp Silver JSONL có sẵn (idempotent)
    run --source X [--once | --loop --interval 600] [--force] [--limit 12]
                                        chạy crawler đã đăng ký của nguồn X
    replay --start 2026-08-01T00:00+07:00 --speed 60 [--until …] [--reset]
                                        phát lại Silver theo đồng hồ giả lập (thay crawler)
    status                              mỗi báo: lần chạy cuối, bài mới 1h/24h, lỗi; đồng hồ
    clock [--real]                      xem đồng hồ / đưa về giờ thật

Mọi lệnh nhận `--db-env TÊN_BIẾN` (mặc định DATABASE_URL): TÊN biến môi trường chứa URL, không
truyền URL trên dòng lệnh (lộ mật khẩu trong lịch sử shell). Bảng phải có trước: `make db-migrate`.
`import-jsonl`, `run`, `replay` tự đồng bộ configs/sources.yaml trước khi chạy.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import UTC, datetime

import psycopg

from eventrank.common import db
from eventrank.ingest import base, clock, jsonl, replay, sink, sources, status
from eventrank.ingest.fetch import CrawlerConfigError, PoliteClient

DEFAULT_SILVER = "data/lake/silver/*/*.jsonl"


class CliError(RuntimeError):
    pass


def _dt(s: str) -> datetime:
    d = datetime.fromisoformat(s)
    if d.tzinfo is None:
        raise argparse.ArgumentTypeError(f"cần múi giờ, ví dụ {s}+07:00")
    return d


def _sync(conn: psycopg.Connection) -> dict[str, int]:
    return sink.sync_sources(conn, sources.load_sources())


def _fmt(c: sink.UpsertResult) -> str:
    top = ", ".join(f"{k}={v}" for k, v in c.reject_reasons.most_common(5))
    return (f"inserted={c.inserted} updated={c.updated} unchanged={c.unchanged} "
            f"rejected={c.rejected}" + (f" (lý do: {top})" if top else ""))


# ---------------------------------------------------------------------- lệnh
def cmd_sources_sync(conn: psycopg.Connection, a: argparse.Namespace) -> int:
    print(f"sources: {_sync(conn)}")
    return 0


def cmd_import(conn: psycopg.Connection, a: argparse.Namespace) -> int:
    _sync(conn)
    t0 = time.perf_counter()
    res = jsonl.import_jsonl(conn, a.globs, batch_size=a.batch_size)
    print(f"import-jsonl xong trong {time.perf_counter() - t0:.1f} s: {_fmt(res)}")
    return 0


def cmd_run(conn: psycopg.Connection, a: argparse.Namespace) -> int:
    _sync(conn)
    if clock.read_clock(conn).mode == "replay":
        raise CliError("Đồng hồ DB này đang ở chế độ replay — không chạy crawler thật vào đây. "
                       "Dùng DB khác (--db-env) hoặc `ingest clock --real`.")
    row = conn.execute("SELECT enabled, crawler FROM sources WHERE source = %s",
                       (a.source,)).fetchone()
    if row is None:
        raise CliError(f"Không có nguồn {a.source!r} trong configs/sources.yaml")
    enabled, spec = row
    if not spec:
        raise CliError(f"{a.source}: chưa có crawler (trường `crawler:` trong "
                       "configs/sources.yaml)")
    if not enabled and not a.force:
        raise CliError(f"{a.source}: enabled = false. Bật sau checklist docs/tong-hop.md mục 17.4.8, "
                       "hoặc --force để chạy thử")
    crawler = sources.load_crawler(spec)
    if crawler.source != a.source:
        raise CliError(f"{spec} khai báo source={crawler.source!r}, khác {a.source!r}")
    worst = 0
    with PoliteClient() as client:
        while True:
            r = base.run_crawler(conn, crawler, client, max_articles=a.limit)
            print(f"[{datetime.now().astimezone():%d/%m %H:%M}] {a.source} lần chạy {r.run_id}: "
                  f"{r.status}, thấy {r.n_seen} — {_fmt(r.counts)}"
                  + (f"\n  lỗi: {r.error}" if r.error else ""), flush=True)
            worst = max(worst, 0 if r.status == "ok" else 1)
            if r.status == "blocked":
                print("BÁO CHẶN: dừng, báo người dùng, KHÔNG tìm cách vượt chặn.", file=sys.stderr)
                return 2
            if not a.loop:
                return worst
            time.sleep(a.interval)


def cmd_replay(conn: psycopg.Connection, a: argparse.Namespace) -> int:
    _sync(conn)
    known = sink.known_sources(conn)
    t0 = time.perf_counter()
    arts, rejected = replay.load_silver(a.globs or [DEFAULT_SILVER], known_sources=known,
                                        now=datetime.now(UTC))
    print(f"nạp {len(arts)} bài hợp lệ trong {time.perf_counter() - t0:.1f} s; loại "
          f"{rejected.rejected} ({dict(rejected.reject_reasons.most_common(5))})", flush=True)
    try:
        r = replay.run_replay(conn, arts, start=a.start, speed=a.speed, until=a.until,
                              tick=a.tick, reset=a.reset, allow_mixed=a.allow_mixed,
                              max_ticks=a.max_ticks, log=lambda m: print(m, flush=True))
    except KeyboardInterrupt:
        c = clock.read_clock(conn)
        print(f"\nĐã dừng ở sim_now = {c.sim_now}. Chạy lại cùng lệnh để tiếp tục "
              "(--reset để quay về --start).")
        return 0
    print(f"replay dừng ở {r.sim_now.isoformat()} sau {r.ticks} nhịp: {_fmt(r.counts)}")
    return 0


def cmd_status(conn: psycopg.Connection, a: argparse.Namespace) -> int:
    print(status.format_status(conn))
    return 0


def cmd_clock(conn: psycopg.Connection, a: argparse.Namespace) -> int:
    if a.real:
        clock.set_real(conn)
    c = clock.read_clock(conn)
    print(f"mode={c.mode} sim_now={c.sim_now} speed={c.speed:g} app_now={clock.app_now(conn)}")
    return 0


# ---------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--db-env", default="DATABASE_URL",
                        help="TÊN biến môi trường chứa URL Postgres (mặc định DATABASE_URL)")
    ap = argparse.ArgumentParser(prog="python -m eventrank.ingest",
                                 description="Tầng Thu thập: nạp bài vào Postgres")
    sub = ap.add_subparsers(dest="command", required=True)

    s = sub.add_parser("sources", parents=[common], help="đồng bộ configs/sources.yaml → DB")
    s.add_argument("action", choices=["sync"])
    s.set_defaults(fn=cmd_sources_sync)

    s = sub.add_parser("import-jsonl", parents=[common], help="nạp Silver JSONL có sẵn")
    s.add_argument("globs", nargs="+", help="file hoặc glob (đặt trong nháy: 'data/…/*.jsonl')")
    s.add_argument("--batch-size", type=int, default=1000)
    s.set_defaults(fn=cmd_import)

    s = sub.add_parser("run", parents=[common], help="chạy crawler đã đăng ký của một nguồn")
    s.add_argument("--source", required=True)
    g = s.add_mutually_exclusive_group()
    g.add_argument("--once", action="store_true", help="chạy một lần (mặc định)")
    g.add_argument("--loop", action="store_true", help="chạy lặp, nghỉ --interval giây")
    s.add_argument("--interval", type=float, default=600)
    s.add_argument("--force", action="store_true", help="chạy cả khi enabled = false (thử)")
    s.add_argument("--limit", type=int, default=None,
                   help="dừng sau N bài (lát cắt thử, vd 12)")
    s.set_defaults(fn=cmd_run)

    s = sub.add_parser("replay", parents=[common], help="phát lại Silver theo đồng hồ giả lập")
    s.add_argument("--start", type=_dt, required=True, help="vd 2026-08-01T00:00+07:00")
    s.add_argument("--speed", type=float, default=60, help="số giây giả lập mỗi giây thật")
    s.add_argument("--until", type=_dt, default=None, help="mặc định: bài cuối cùng")
    s.add_argument("--tick", type=float, default=5, help="giây thật giữa hai nhịp")
    s.add_argument("--glob", dest="globs", action="append", default=None,
                   help=f"Silver JSONL (mặc định {DEFAULT_SILVER}); lặp lại được")
    s.add_argument("--reset", action="store_true", help="bỏ sim_now cũ, bắt đầu lại từ --start")
    s.add_argument("--allow-mixed", action="store_true",
                   help="cho phép phát lại vào DB đã có bài import/crawler (không khuyên dùng)")
    s.add_argument("--max-ticks", type=int, default=None, help=argparse.SUPPRESS)
    s.set_defaults(fn=cmd_replay)

    s = sub.add_parser("status", parents=[common], help="tình trạng từng báo + đồng hồ")
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("clock", parents=[common], help="xem đồng hồ; --real để về giờ thật")
    s.add_argument("--real", action="store_true")
    s.set_defaults(fn=cmd_clock)
    return ap


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        with db.connect(env=a.db_env) as conn:
            return a.fn(conn, a)
    except (db.DatabaseConfigError, CliError, CrawlerConfigError, replay.ReplayError,
            base.CrawlerError, sources.SourceConfigError, FileNotFoundError) as e:
        print(f"LỖI: {e}", file=sys.stderr)
        return 1
    except psycopg.errors.UndefinedTable as e:
        print(f"LỖI: thiếu bảng ({e.diag.message_primary}) — chạy `make db-migrate` trước",
              file=sys.stderr)
        return 1
    except psycopg.OperationalError as e:
        print(f"LỖI kết nối Postgres: {e}", file=sys.stderr)
        return 1
