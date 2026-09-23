# Online scraper for Mongolian CS2 competitors (1st.mn, lanndy.mn)
# Writes one snapshot row to CSV with a UTC timestamp.
# Resilient: one site failing does not stop the other or block the CSV write.
#
# Manual run:   & scrape_competitors.ps1
# Scheduled:    via Task Scheduler (see setup command in chat / README)

$ErrorActionPreference = 'Stop'
$ua  = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
$csv = Join-Path $PSScriptRoot 'online_log.csv'
$ts  = (Get-Date).ToUniversalTime().ToString('yyyy-MM-dd HH:mm:ss')

$rows = @()

# --- 1st.mn: exact online = sum of players across all servers ---
$r = [ordered]@{ timestamp_utc=$ts; site='1st.mn'; online=$null; servers_online=$null; servers_total=$null; online_raw=''; status='ok' }
try {
    $srv = Invoke-RestMethod -Uri 'https://1st.mn/api/servers' -Headers @{ 'User-Agent'=$ua } -TimeoutSec 25
    $r.online         = [int]($srv | Measure-Object -Property players -Sum).Sum
    $r.servers_total  = $srv.Count
    $r.servers_online = ($srv | Where-Object { $_.status -eq 'online' }).Count
    $r.online_raw     = [string]$r.online
} catch { $r.status = 'error: ' + $_.Exception.Message }
$rows += [pscustomobject]$r

# --- lanndy.mn: rounded online from SSR landing HTML ---
$r = [ordered]@{ timestamp_utc=$ts; site='lanndy.mn'; online=$null; servers_online=$null; servers_total=$null; online_raw=''; status='ok' }
try {
    $html = (Invoke-WebRequest -Uri 'https://lanndy.mn/' -Headers @{ 'User-Agent'=$ua } -TimeoutSec 25 -UseBasicParsing).Content
    $m = [regex]::Match($html, '([\d.,]+\s*[kK]?)\s*<!-- --> <!-- -->Online')
    if ($m.Success) {
        $raw = ($m.Groups[1].Value -replace '\s','')
        $r.online_raw = $raw
        if ($raw -match '[kK]$') { $r.online = [int]([double]($raw -replace '[kK]$','') * 1000) }
        else                     { $r.online = [int]([double]($raw -replace ',','')) }
    } else { $r.status = 'error: online marker not found (markup changed?)' }
} catch { $r.status = 'error: ' + $_.Exception.Message }
$rows += [pscustomobject]$r

# --- append to CSV (creates header on first run) ---
$cols = 'timestamp_utc','site','online','servers_online','servers_total','online_raw','status'
if (-not (Test-Path $csv)) {
    $rows | Select-Object $cols | Export-Csv -Path $csv -NoTypeInformation -Encoding UTF8
} else {
    $rows | Select-Object $cols | ConvertTo-Csv -NoTypeInformation | Select-Object -Skip 1 | Add-Content -Path $csv -Encoding UTF8
}

$rows | Format-Table -AutoSize
"Written to $csv"
