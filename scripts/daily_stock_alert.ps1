[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$envPath = Join-Path $PSScriptRoot "..\.env"
$botToken = $env:TELEGRAM_BOT_TOKEN
$chatId = $env:TELEGRAM_CHAT_ID

if (Test-Path $envPath) {
    Get-Content $envPath -Encoding UTF8 | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
            $parts = $line.Split("=", 2)
            $key = $parts[0].Trim()
            $val = $parts[1].Trim().Trim('"').Trim("'")
            if ($key -eq "TELEGRAM_BOT_TOKEN" -and $val) { $botToken = $val }
            if ($key -eq "TELEGRAM_CHAT_ID" -and $val) { $chatId = $val }
        }
    }
}

$watchlist = @(
    @{ Ticker = "KDH"; Sector = "Bat dong san"; BuyLow = 13700; BuyHigh = 14100; Target = 15500; StopLoss = 13000 },
    @{ Ticker = "TPB"; Sector = "Ngan hang";    BuyLow = 11700; BuyHigh = 12000; Target = 13200; StopLoss = 11200 },
    @{ Ticker = "MBB"; Sector = "Ngan hang";    BuyLow = 19300; BuyHigh = 19700; Target = 21200; StopLoss = 18500 },
    @{ Ticker = "HSG"; Sector = "Thep/Ton ma";  BuyLow = 10000; BuyHigh = 10350; Target = 11800; StopLoss = 9500  },
    @{ Ticker = "SSI"; Sector = "Chung khoan";  BuyLow = 18800; BuyHigh = 19400; Target = 21000; StopLoss = 18000 },
    @{ Ticker = "VCI"; Sector = "Chung khoan";  BuyLow = 18400; BuyHigh = 18900; Target = 20600; StopLoss = 17800 },
    @{ Ticker = "SZC"; Sector = "BDS KCN";      BuyLow = 16900; BuyHigh = 17350; Target = 18800; StopLoss = 16100 },
    @{ Ticker = "DBC"; Sector = "Nong nghiep";  BuyLow = 15300; BuyHigh = 15650; Target = 17200; StopLoss = 14700 },
    @{ Ticker = "HHV"; Sector = "Dau tu cong";  BuyLow = 9100;  BuyHigh = 9400;  Target = 10500; StopLoss = 8600  },
    @{ Ticker = "VCG"; Sector = "Xay dung/DTC"; BuyLow = 14300; BuyHigh = 14800; Target = 16500; StopLoss = 13800 }
)

$nowStr = (Get-Date).ToString("yyyy-MM-dd HH:mm")
$results = @()
$buySignals = @()

foreach ($item in $watchlist) {
    $t = $item.Ticker
    try {
        $url = "https://query1.finance.yahoo.com/v8/finance/chart/$t.VN?range=3mo&interval=1d"
        $res = Invoke-RestMethod -Uri $url -Headers @{"User-Agent"="Mozilla/5.0"} -TimeoutSec 6
        $meta = $res.chart.result[0].meta
        $q = $res.chart.result[0].indicators.quote[0]
        $closes = @($q.close | Where-Object { $_ -ne $null })
        $vols = @($q.volume | Where-Object { $_ -ne $null })

        $price = [math]::Round($meta.regularMarketPrice, 0)
        $dayPct = [math]::Round($meta.regularMarketChangePercent, 2)
        $sma20 = [math]::Round(($closes[-20..-1] | Measure-Object -Average).Average, 0)

        $gains = 0.0; $losses = 0.0
        for ($i = $closes.Count - 14; $i -lt $closes.Count; $i++) {
            $diff = $closes[$i] - $closes[$i-1]
            if ($diff -gt 0) { $gains += $diff } else { $losses -= $diff }
        }
        $rs = if ($losses -eq 0) { 100 } else { ($gains / 14) / ($losses / 14) }
        $rsi = [math]::Round(100 - (100 / (1 + $rs)), 1)
        $volRatio = [math]::Round($vols[-1] / (($vols[-20..-1] | Measure-Object -Average).Average), 2)

        $status = "CHO DIEU CHINH"
        $icon = "[CHO]"
        if ($price -ge $item.BuyLow -and $price -le $item.BuyHigh) {
            if ($volRatio -ge 1.3) {
                $status = "MUA NGAY (NO VOL)"
                $icon = "[MUA MANH]"
            } else {
                $status = "TRONG VUNG MUA DEP"
                $icon = "[VUNG MUA]"
            }
            $buySignals += "$icon *$t* ($price d | $dayPct% | RSI: $rsi | Vol: ${volRatio}x) -> Vung mua: $($item.BuyLow)-$($item.BuyHigh)"
        } elseif ($price -gt $item.StopLoss -and $price -lt $item.BuyLow) {
            $status = "GIA RE HON VUNG MUA (CANH GOM)"
            $icon = "[GOM RE]"
            $buySignals += "$icon *$t* ($price d | $dayPct% | RSI: $rsi) -> Thap hon vung mua ($($item.BuyLow)-$($item.BuyHigh)), tren cat lo $($item.StopLoss)"
        } elseif ($price -le ($item.BuyHigh * 1.01) -and $price -gt $item.BuyHigh) {
            $status = "SAT VUNG MUA (lech <= 1%)"
            $icon = "[SAT VUNG MUA]"
            $buySignals += "$icon *$t* ($price d | $dayPct% | RSI: $rsi | Vol: ${volRatio}x) -> Sat vung mua $($item.BuyLow)-$($item.BuyHigh)"
        } elseif ($price -ge $item.Target) {
            $status = "CHAM CHOT LOI"
            $icon = "[CHOT LOI]"
        } elseif ($price -le $item.StopLoss) {
            $status = "VI PHAM CAT LO"
            $icon = "[CAT LO]"
        }

        $results += [PSCustomObject]@{
            Ticker   = $t
            Price    = $price
            DayPct   = $dayPct
            BuyZone  = "$($item.BuyLow)-$($item.BuyHigh)"
            Target   = $item.Target
            StopLoss = $item.StopLoss
            SMA20    = $sma20
            RSI14    = $rsi
            VolRatio = $volRatio
            Status   = $status
        }
    } catch {
        Write-Warning "Failed to fetch $t : $_"
    }
}

$results | Format-Table -AutoSize | Out-String -Width 200

$reportsDir = Join-Path $PSScriptRoot "..\reports"
if (-not (Test-Path $reportsDir)) { New-Item -ItemType Directory -Path $reportsDir | Out-Null }
$reportFile = Join-Path $reportsDir "latest_alert.md"

$msgLines = @(
    "*BAO CAO QUET CO PHIEU (<= 20.000d) - $nowStr*",
    "----------------------------------------"
)
if ($buySignals.Count -gt 0) {
    $msgLines += "*CAC MA DANG O VUNG MUA / SAT VUNG MUA:*"
    $msgLines += $buySignals
} else {
    $msgLines += "Hien chua co ma nao lot vao vung mua toi uu."
}
$msgLines += ""
$msgLines += "*BANG TONG HOP 10 MA MUC TIEU:*"
foreach ($r in $results) {
    $msgLines += "- *$($r.Ticker)*: $($r.Price)d ($($r.DayPct)%) | Mua: $($r.BuyZone) | RSI: $($r.RSI14) | Vol: $($r.VolRatio)x -> _$($r.Status)_"
}

$fullText = $msgLines -join "`n"
Set-Content -Path $reportFile -Value $fullText -Encoding UTF8
Write-Output "`nSaved report to: $reportFile"

if ($botToken -and $chatId) {
    try {
        $tgUrl = "https://api.telegram.org/bot$botToken/sendMessage"
        $body = @{
            chat_id    = $chatId
            text       = $fullText
            parse_mode = "Markdown"
        } | ConvertTo-Json -Compress
        $tgRes = Invoke-RestMethod -Uri $tgUrl -Method Post -ContentType "application/json; charset=utf-8" -Body ([System.Text.Encoding]::UTF8.GetBytes($body)) -TimeoutSec 10
        if ($tgRes.ok) {
            Write-Output "TELEGRAM_STATUS: Sent successfully to chat_id $chatId"
        }
    } catch {
        Write-Warning "TELEGRAM_ERROR: Failed to send Telegram message: $_"
    }
} else {
    Write-Output "TELEGRAM_STATUS: Skipped (TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not configured in .env yet)"
}

