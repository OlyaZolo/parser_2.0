
import argparse
import csv
import os
import sys
import time
from datetime import datetime, timezone

# Fetch, CSV and Sheets helpers are shared with the matches scraper
from scrape_cybershoke_matches import (
    DEFAULT_CREDS, DEFAULT_SHEET_ID, ERROR_LOG, HERE, LOBBIES_CSV, STATUSES,
    _append_csv, _append_gsheet, _fetch, _open_sheet,
)

# Custom matches (praki) grouped by SERVER country: lobby.data_center.country.
# The live list is shorter than stats_data.count_active_matches, so treat totals as a lower bound.
PRAKI_CSV = os.path.join(HERE, "cybershoke_praki_country.csv")
PRAKI_WS = "cybershoke_praki_country"
PRAKI_COLUMNS = ["timestamp_utc", "state", "country", "players", "lobbies"]


def aggregate(ts, lobbies):
    """lobbies: iterable of (state, country, count_players) -> rows per (state, country)."""
    agg = {}
    for state, country, players in lobbies:
        a = agg.setdefault((state, country or "unknown"), [0, 0])
        a[0] += players
        a[1] += 1
    return [{"timestamp_utc": ts, "state": s, "country": c, "players": p, "lobbies": n}
            for (s, c), (p, n) in sorted(agg.items(), key=lambda kv: (kv[0][0], -kv[1][0]))]


def take_snapshot():
    # live only: waiting lobbies are mostly 1-player rooms that may never start
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    lobbies = [("live", (lb.get("data_center") or {}).get("country"), lb.get("count_players") or 0)
               for lb in _fetch(STATUSES["live"]).get("list_lobbys") or []]
    return aggregate(ts, lobbies)


def backfill_rows():
    """Rebuild country rows from the per-lobby CSV written by scrape_cybershoke_matches.py."""
    by_ts = {}
    with open(LOBBIES_CSV, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["state"] != "live":
                continue
            by_ts.setdefault(r["timestamp_utc"], []).append((r["state"], r["country"], int(r["count_players"] or 0)))
    return [row for ts in sorted(by_ts) for row in aggregate(ts, by_ts[ts])]


def write(rows, do_print, gsheet):
    _append_csv(PRAKI_CSV, PRAKI_COLUMNS, rows)
    if do_print:
        for r in rows:
            print("  %s %-3s %5s players in %s lobbies" % (r["timestamp_utc"], r["country"], r["players"], r["lobbies"]))
    if not gsheet:
        return True
    try:
        _append_gsheet(_open_sheet(*gsheet), PRAKI_WS, PRAKI_COLUMNS, rows)
        print("Wrote %d rows to Google Sheets (%s / %s)" % (len(rows), gsheet[0], PRAKI_WS))
        return True
    except Exception as e:
        msg = "error: failed to write to Google Sheets (CSV is saved): %s" % e
        print(msg, file=sys.stderr)
        with open(ERROR_LOG, "a", encoding="utf-8") as f:  # pythonw has no console to show it
            f.write("%s %s\n" % (datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), msg))
        return False


def run_once(do_print, gsheet):
    try:
        rows = take_snapshot()
    except Exception as e:
        print("error: %s" % e, file=sys.stderr)
        return False
    return write(rows, do_print, gsheet)


def main():
    parser = argparse.ArgumentParser(description="Snapshot CyberShoke custom matches (praki) by server country.")
    parser.add_argument("--print", dest="do_print", action="store_true", help="print summary to stdout")
    parser.add_argument("--loop", type=float, default=0, help="repeat every N minutes (0 = run once)")
    parser.add_argument("--backfill", action="store_true",
                        help="aggregate existing cybershoke_lobbies.csv instead of calling the API")
    parser.add_argument("--no-gsheet", dest="gsheet", action="store_false", help="CSV only, skip Google Sheets")
    parser.add_argument("--sheet-id", default=os.environ.get("GSHEET_ID") or DEFAULT_SHEET_ID,
                        help="Google Sheet ID (or env GSHEET_ID)")
    parser.add_argument("--creds", default=os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or DEFAULT_CREDS,
                        help="service-account JSON (or env GOOGLE_APPLICATION_CREDENTIALS)")
    args = parser.parse_args()
    gsheet = (args.sheet_id, args.creds) if args.gsheet else None

    if args.backfill:
        return 0 if write(backfill_rows(), args.do_print, gsheet) else 1
    if not args.loop:
        return 0 if run_once(args.do_print, gsheet) else 1
    while True:
        run_once(True, gsheet)
        time.sleep(args.loop * 60)


if __name__ == "__main__":
    sys.exit(main())
