/**
 * Online scraper for Mongolian CS2 competitors (1st.mn, lanndy.mn).
 * Runs inside a Google Sheet via an hourly time-driven trigger.
 * Appends one row per site per run. No PC / no MCP required.
 *
 * Setup:
 *   1) Open the target Google Sheet.
 *   2) Extensions -> Apps Script, paste this file, Save.
 *   3) Run setup() once (grants permissions + writes header + one test row).
 *   4) Run installHourlyTrigger() once to schedule hourly collection.
 */

var SHEET_NAME = 'online_log';
var HEADER = ['timestamp_utc', 'site', 'online', 'servers_online', 'servers_total', 'online_raw', 'status'];
var UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36';

function getSheet_() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sh = ss.getSheetByName(SHEET_NAME);
  if (!sh) { sh = ss.insertSheet(SHEET_NAME); }
  if (sh.getLastRow() === 0) { sh.appendRow(HEADER); sh.setFrozenRows(1); }
  return sh;
}

function utcStamp_() {
  return Utilities.formatDate(new Date(), 'UTC', 'yyyy-MM-dd HH:mm:ss');
}

// 1st.mn: exact online = sum of players across all servers (public JSON API)
function scrape1st_(ts) {
  var row = { timestamp_utc: ts, site: '1st.mn', online: '', servers_online: '', servers_total: '', online_raw: '', status: 'ok' };
  try {
    var resp = UrlFetchApp.fetch('https://1st.mn/api/servers', {
      headers: { 'User-Agent': UA, 'Accept': 'application/json' },
      muteHttpExceptions: true, followRedirects: true
    });
    if (resp.getResponseCode() !== 200) throw new Error('HTTP ' + resp.getResponseCode());
    var servers = JSON.parse(resp.getContentText());
    var players = 0, online = 0;
    for (var i = 0; i < servers.length; i++) {
      players += Number(servers[i].players) || 0;
      if (servers[i].status === 'online') online++;
    }
    row.online = players;
    row.servers_total = servers.length;
    row.servers_online = online;
    row.online_raw = String(players);
  } catch (e) { row.status = 'error: ' + e.message; }
  return row;
}

// lanndy.mn: rounded online from SSR landing HTML
function scrapeLanndy_(ts) {
  var row = { timestamp_utc: ts, site: 'lanndy.mn', online: '', servers_online: '', servers_total: '', online_raw: '', status: 'ok' };
  try {
    var resp = UrlFetchApp.fetch('https://lanndy.mn/', {
      headers: { 'User-Agent': UA }, muteHttpExceptions: true, followRedirects: true
    });
    if (resp.getResponseCode() !== 200) throw new Error('HTTP ' + resp.getResponseCode());
    var html = resp.getContentText();
    var m = html.match(/([\d.,]+\s*[kK]?)\s*<!-- --> <!-- -->Online/);
    if (m) {
      var raw = m[1].replace(/\s/g, '');
      row.online_raw = raw;
      if (/[kK]$/.test(raw)) { row.online = Math.round(parseFloat(raw) * 1000); }
      else { row.online = Math.round(parseFloat(raw.replace(/,/g, ''))); }
    } else { row.status = 'error: online marker not found (markup changed?)'; }
  } catch (e) { row.status = 'error: ' + e.message; }
  return row;
}

// Main job — called by the hourly trigger
function collect() {
  var sh = getSheet_();
  var ts = utcStamp_();
  [scrape1st_(ts), scrapeLanndy_(ts)].forEach(function (r) {
    sh.appendRow([r.timestamp_utc, r.site, r.online, r.servers_online, r.servers_total, r.online_raw, r.status]);
  });
}

function setup() { collect(); }

function installHourlyTrigger() {
  // remove old triggers for collect() to avoid duplicates
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'collect') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('collect').timeBased().everyHours(1).create();
}
