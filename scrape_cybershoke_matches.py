
import argparse
import csv
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone

URL = "https://cybershoke.net/api/api/v1/custom-matches/lobbys/list"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
TIMEOUT = 30
RETRIES = 3
RETRY_WAIT = 5
PAUSE_BETWEEN_REQUESTS = 2  # the API answers 429 when hammered

HERE = os.path.dirname(os.path.abspath(__file__))
SNAPSHOT_CSV = os.path.join(HERE, "cybershoke_snapshot.csv")
LOBBIES_CSV = os.path.join(HERE, "cybershoke_lobbies.csv")
DIST_CSV = os.path.join(HERE, "cybershoke_players_dist.csv")
ERROR_LOG = os.path.join(HERE, "cybershoke_errors.log")

DEFAULT_SHEET_ID = "1tqAvE6Ie6zzwpTYdeXB1BNq1aa0jYy6qKWrADPzxClY"  # same sheet as scrape_competitors.py
DEFAULT_CREDS = os.path.join(HERE, "service_account.json")
DIST_WS = "cybershoke_players_dist"

STATUSES = {"waiting": 0, "live": 1}

SNAPSHOT_COLUMNS = [
    "timestamp_utc",
    "waiting_lobbies", "waiting_players",
    "live_lobbies", "live_players",
    "site_count_new_matches", "site_count_active_matches", "site_count_end_matches",
    "status",
]
LOBBY_COLUMNS = [
    "timestamp_utc", "id_lobby", "state", "type_lobby", "mode", "map_name",
    "count_players", "max_players", "country", "city",
    "unixtime_create", "score_team_2", "score_team_3",
]
DIST_COLUMNS = ["timestamp_utc", "state", "players_in_match", "matches"]

# Public servers online by server country: GET main/data, module `servers`.
# Country is where the SERVER is, not where the player is (players have no country field).
# Sum over listed servers is lower than stats.countPlayersOnServers: part of servers is not listed.
MAIN_URL = "https://cybershoke.net/api/api/v2/main/data"
COUNTRY_CSV = os.path.join(HERE, "cybershoke_online_country.csv")
ONLINE_CSV = os.path.join(HERE, "cybershoke_online_total.csv")
COUNTRY_WS = "cybershoke_online_country"
COUNTRY_COLUMNS = ["timestamp_utc", "game", "country", "players", "servers", "servers_with_players"]
ONLINE_COLUMNS = [
    "timestamp_utc", "players_listed_servers", "site_players_on_servers", "site_users_on_site",
    "site_players_24h", "site_new_players_24h", "servers_listed", "site_count_servers", "status",
]


def _fetch(lobby_status):
    body = {
        "lobby_status": lobby_status,
        "only_my_matches": False,
        "type_lobby": [0, 1],
        "name_map": [],
        "enable_custom_modification": None,
        "id_data_center": [],
        "only_friends": False,
    }
    headers = {
        "User-Agent": UA,
        "Content-Type": "application/json",
        "Origin": "https://cybershoke.net",
        "Referer": "https://cybershoke.net/ru/matches",
    }
    last_err = None
    for attempt in range(RETRIES):
        try:
            req = urllib.request.Request(URL, data=json.dumps(body).encode(), headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                payload = json.loads(resp.read())
            if payload.get("result") != "success":
                raise RuntimeError("api result=%s" % payload.get("result"))
            return payload["data"]
        except Exception as e:
            last_err = e
            if attempt < RETRIES - 1:
                time.sleep(RETRY_WAIT * (attempt + 1))
    raise last_err


def _fetch_main():
    headers = {"User-Agent": UA, "Origin": "https://cybershoke.net", "Referer": "https://cybershoke.net/ru/cs2"}
    last_err = None
    for attempt in range(RETRIES):
        try:
            with urllib.request.urlopen(urllib.request.Request(MAIN_URL, headers=headers), timeout=TIMEOUT) as resp:
                return json.loads(resp.read())["data"]["modules"]
        except Exception as e:
            last_err = e
            if attempt < RETRIES - 1:
                time.sleep(RETRY_WAIT * (attempt + 1))
    raise last_err


def take_online_by_country(ts):
    """Players on public servers grouped by game and server country, plus site-wide counters."""
    total = {c: "" for c in ONLINE_COLUMNS}
    total["timestamp_utc"] = ts
    total["status"] = "ok"
    rows = []
    try:
        modules = _fetch_main()
        data = modules["servers"]["data"]
        stats = data.get("stats") or {}
        country_of = {l["location"]: l["country"] for l in modules["servers_locations"]["data"]}
        game_of = {k: v.get("name_short") for k, v in (modules.get("games_list", {}).get("data") or {}).items()}

        agg = {}
        for game_id, modes in (data.get("servers") or {}).items():
            game = game_of.get(game_id, game_id)
            for categories in modes.values():
                for servers in categories.values():
                    for sv in servers:
                        key = (game, country_of.get(sv.get("location"), sv.get("location") or "unknown"))
                        a = agg.setdefault(key, [0, 0, 0])
                        players = sv.get("players") or 0
                        a[0] += players
                        a[1] += 1
                        a[2] += 1 if players else 0
        rows = [{"timestamp_utc": ts, "game": g, "country": c, "players": p, "servers": n, "servers_with_players": nw}
                for (g, c), (p, n, nw) in sorted(agg.items(), key=lambda kv: -kv[1][0])]

        total["players_listed_servers"] = sum(r["players"] for r in rows)
        total["servers_listed"] = sum(r["servers"] for r in rows)
        total["site_players_on_servers"] = stats.get("countPlayersOnServers", "")
        total["site_users_on_site"] = stats.get("countUsersOnSite", "")
        total["site_players_24h"] = stats.get("countPlayers24h", "")
        total["site_new_players_24h"] = stats.get("countNewPlayers24h", "")
        total["site_count_servers"] = stats.get("countServers", "")
    except Exception as e:
        total["status"] = "error: %s" % e
    return total, rows


def _lobby_row(ts, state, lb):
    ms = lb.get("match_settings") or {}
    base = (lb.get("match_stats") or {}).get("base") or {}
    dc = lb.get("data_center") or {}
    return {
        "timestamp_utc": ts,
        "id_lobby": lb.get("id_lobby"),
        "state": state,
        "type_lobby": lb.get("type_lobby"),
        "mode": (lb.get("type_match") or {}).get("name"),
        "map_name": ms.get("map_name"),
        "count_players": lb.get("count_players") or 0,
        "max_players": (ms.get("max_players_2") or 0) + (ms.get("max_players_3") or 0),
        "country": dc.get("country"),
        "city": dc.get("city"),
        "unixtime_create": ms.get("unixtime_create"),
        "score_team_2": (base.get("team_2") or {}).get("score"),
        "score_team_3": (base.get("team_3") or {}).get("score"),
    }


def take_snapshot():
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    snap = {c: "" for c in SNAPSHOT_COLUMNS}
    snap["timestamp_utc"] = ts
    snap["status"] = "ok"
    lobbies = []
    try:
        for i, (state, code) in enumerate(STATUSES.items()):
            if i:
                time.sleep(PAUSE_BETWEEN_REQUESTS)
            data = _fetch(code)
            rows = [_lobby_row(ts, state, lb) for lb in data.get("list_lobbys") or []]
            lobbies.extend(rows)
            snap[state + "_lobbies"] = len(rows)
            snap[state + "_players"] = sum(r["count_players"] for r in rows)
            stats = data.get("stats_data") or {}
            for k in ("count_new_matches", "count_active_matches", "count_end_matches"):
                snap["site_" + k] = stats.get(k, "")
    except Exception as e:
        snap["status"] = "error: %s" % e
    return snap, lobbies


def _append_csv(path, columns, rows):
    is_new = not os.path.exists(path) or os.path.getsize(path) == 0
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        if is_new:
            w.writeheader()
        w.writerows(rows)


def _open_sheet(sheet_id, creds_path):
    import gspread
    from google.oauth2.service_account import Credentials

    creds = Credentials.from_service_account_file(
        creds_path, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    return gspread.authorize(creds).open_by_key(sheet_id)


def _append_gsheet(sh, ws_name, columns, rows):
    import gspread

    try:
        ws = sh.worksheet(ws_name)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=ws_name, rows=1000, cols=len(columns))
    if not ws.row_values(1):  # empty sheet -> header first
        ws.append_row(columns, value_input_option="USER_ENTERED")
    ws.append_rows([[r[c] for c in columns] for r in rows], value_input_option="USER_ENTERED")


def players_distribution(lobbies):
    """Collapse lobbies into (state, players_in_match) -> number of matches."""
    ts = lobbies[0]["timestamp_utc"]
    counts = {}
    for lb in lobbies:
        key = (lb["state"], lb["count_players"])
        counts[key] = counts.get(key, 0) + 1
    return [{"timestamp_utc": ts, "state": state, "players_in_match": players, "matches": n}
            for (state, players), n in sorted(counts.items())]


def run_once(do_print, gsheet=None):
    snap, lobbies = take_snapshot()
    dist = players_distribution(lobbies) if lobbies else []
    _append_csv(SNAPSHOT_CSV, SNAPSHOT_COLUMNS, [snap])
    if lobbies:
        _append_csv(LOBBIES_CSV, LOBBY_COLUMNS, lobbies)
        _append_csv(DIST_CSV, DIST_COLUMNS, dist)

    time.sleep(PAUSE_BETWEEN_REQUESTS)
    online, by_country = take_online_by_country(snap["timestamp_utc"])
    _append_csv(ONLINE_CSV, ONLINE_COLUMNS, [online])
    if by_country:
        _append_csv(COUNTRY_CSV, COUNTRY_COLUMNS, by_country)

    if do_print:
        for d in dist:
            print("  %-7s %2s players: %s matches" % (d["state"], d["players_in_match"], d["matches"]))
        for r in by_country:
            if r["players"]:
                print("  %-5s %-3s %5s players on %s/%s servers" % (
                    r["game"], r["country"], r["players"], r["servers_with_players"], r["servers"]))
        print("  online: listed servers %s | site players on servers %s | users on site %s | %s" % (
            online["players_listed_servers"], online["site_players_on_servers"],
            online["site_users_on_site"], online["status"]))
    if gsheet and (dist or by_country):
        try:
            sh = _open_sheet(*gsheet)
            # distribution only: per-lobby detail (~14k rows/day) would hit the Sheets cell limit in ~2 months
            # live only: waiting lobbies are mostly 1-player rooms that may never start
            live = [d for d in dist if d["state"] == "live"]
            if live:
                _append_gsheet(sh, DIST_WS, DIST_COLUMNS, live)
            if by_country:
                _append_gsheet(sh, COUNTRY_WS, COUNTRY_COLUMNS, by_country)
            print("Wrote %d + %d rows to Google Sheets (%s / %s, %s)" % (
                len(live), len(by_country), gsheet[0], DIST_WS, COUNTRY_WS))
        except Exception as e:
            msg = "error: failed to write to Google Sheets (CSV is saved): %s" % e
            print(msg, file=sys.stderr)
            with open(ERROR_LOG, "a", encoding="utf-8") as f:  # pythonw has no console to show it
                f.write("%s %s\n" % (snap["timestamp_utc"], msg))
            return False
    if do_print:
        print("%s waiting %s lobbies / %s players | live %s lobbies / %s players | "
              "site: new=%s active=%s ended_total=%s | %s" % (
                  snap["timestamp_utc"], snap["waiting_lobbies"], snap["waiting_players"],
                  snap["live_lobbies"], snap["live_players"], snap["site_count_new_matches"],
                  snap["site_count_active_matches"], snap["site_count_end_matches"], snap["status"]))
    return snap["status"] == "ok" and online["status"] == "ok"


def main():
    parser = argparse.ArgumentParser(description="Snapshot CyberShoke custom matches into local CSV.")
    parser.add_argument("--print", dest="do_print", action="store_true", help="print summary to stdout")
    parser.add_argument("--loop", type=float, default=0, help="repeat every N minutes (0 = run once)")
    parser.add_argument("--no-gsheet", dest="gsheet", action="store_false",
                        help="CSV only, skip Google Sheets")
    parser.add_argument("--sheet-id", default=os.environ.get("GSHEET_ID") or DEFAULT_SHEET_ID,
                        help="Google Sheet ID (or env GSHEET_ID)")
    parser.add_argument("--creds", default=os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or DEFAULT_CREDS,
                        help="service-account JSON (or env GOOGLE_APPLICATION_CREDENTIALS)")
    args = parser.parse_args()
    gsheet = (args.sheet_id, args.creds) if args.gsheet else None

    if not args.loop:
        return 0 if run_once(args.do_print, gsheet) else 1
    while True:
        run_once(True, gsheet)
        time.sleep(args.loop * 60)


if __name__ == "__main__":
    sys.exit(main())
