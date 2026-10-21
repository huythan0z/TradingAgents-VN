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
    @{ Ticker = "KDH"; Sector = "Bất động sản";   BuyLow = 13700; BuyHigh = 14100; Target = 15500; StopLoss = 13000 },
    @{ Ticker = "TPB"; Sector = "Ngân hàng";      BuyLow = 11700; BuyHigh = 12000; Target = 13200; StopLoss = 11200 },
    @{ Ticker = "MBB"; Sector = "Ngân hàng";      BuyLow = 19300; BuyHigh = 19700; Target = 21200; StopLoss = 18500 },
    @{ Ticker = "HSG"; Sector = "Thép / Tôn mạ";  BuyLow = 10000; BuyHigh = 10350; Target = 11800; StopLoss = 9500  },
    @{ Ticker = "SSI"; Sector = "Chứng khoán";    BuyLow = 18800; BuyHigh = 19400; Target = 21000; StopLoss = 18000 },
    @{ Ticker = "VCI"; Sector = "Chứng khoán";    BuyLow = 18400; BuyHigh = 18900; Target = 20600; StopLoss = 17800 },
    @{ Ticker = "SZC"; Sector = "BĐS KCN";        BuyLow = 16900; BuyHigh = 17350; Target = 18800; StopLoss = 16100 },
    @{ Ticker = "DBC"; Sector = "Nông nghiệp";    BuyLow = 15300; BuyHigh = 15650; Target = 17200; StopLoss = 14700 },
    @{ Ticker = "HHV"; Sector = "Đầu tư công";    BuyLow = 9100;  BuyHigh = 9400;  Target = 10500; StopLoss = 8600  },
    @{ Ticker = "VCG"; Sector = "Xây dựng / ĐTC"; BuyLow = 14300; BuyHigh = 14800; Target = 16500; StopLoss = 13800 }
)

$nowStr = (Get-Date).ToString("yyyy-MM-dd HH:mm")
$results = @()
$buySignals = @()

# Chờ kết nối Internet tối đa 30 giây khi máy vừa thức dậy từ chế độ Sleep
for ($retry = 1; $retry -le 6; $retry++) {
    if (Test-Connection -ComputerName "8.8.8.8" -Count 1 -Quiet -ErrorAction SilentlyContinue) {
        break
    }
    Start-Sleep -Seconds 5
}

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

        $status = "CHỜ ĐIỀU CHỈNH"
        $icon = "⏳"
        if ($price -ge $item.BuyLow -and $price -le $item.BuyHigh) {
            if ($volRatio -ge 1.3) {
                $status = "MUA NGAY (NỔ VOL)"
                $icon = "🚀 [MUA MẠNH]"
            } else {
                $status = "TRONG VÙNG MUA ĐẸP"
                $icon = "🟢 [VÙNG MUA]"
            }
            $buySignals += "$icon *$t* ($price đ | $dayPct% | RSI: $rsi | Vol: ${volRatio}x) -> Vùng mua: $($item.BuyLow)-$($item.BuyHigh) đ"
        } elseif ($price -gt $item.StopLoss -and $price -lt $item.BuyLow) {
            $status = "RẺ HƠN VÙNG MUA (CANH GOM)"
            $icon = "💎 [GOM RẺ]"
            $buySignals += "$icon *$t* ($price đ | $dayPct% | RSI: $rsi) -> Thấp hơn vùng mua ($($item.BuyLow)-$($item.BuyHigh) đ), trên cắt lỗ $($item.StopLoss) đ"
        } elseif ($price -le ($item.BuyHigh * 1.01) -and $price -gt $item.BuyHigh) {
            $status = "SÁT VÙNG MUA (lệch <= 1%)"
            $icon = "🎯 [SÁT VÙNG MUA]"
            $buySignals += "$icon *$t* ($price đ | $dayPct% | RSI: $rsi | Vol: ${volRatio}x) -> Sát vùng mua $($item.BuyLow)-$($item.BuyHigh) đ"
        } elseif ($price -ge $item.Target) {
            $status = "CHẠM CHỐT LỜI"
            $icon = "💰 [CHỐT LỜI]"
        } elseif ($price -le $item.StopLoss) {
            $status = "VI PHẠM CẮT LỖ"
            $icon = "🛑 [CẮT LỖ]"
        }

        $results += [PSCustomObject]@{
            Ticker   = $t
            Sector   = $item.Sector
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
    "📊 *BÁO CÁO QUÉT CỔ PHIẾU (≤ 20.000đ) - $nowStr*",
    "----------------------------------------"
)
if ($buySignals.Count -gt 0) {
    $msgLines += "*CÁC MÃ ĐANG Ở VÙNG MUA / SÁT VÙNG MUA:*"
    $msgLines += $buySignals
} else {
    $msgLines += "Hiện chưa có mã nào lọt vào vùng mua tối ưu."
}
$msgLines += ""
$msgLines += "*BẢNG TỔNG HỢP 10 MÃ MỤC TIÊU:*"
foreach ($r in $results) {
    $msgLines += "- *$($r.Ticker)*: $($r.Price) đ ($($r.DayPct)%) | Mua: $($r.BuyZone) đ | RSI: $($r.RSI14) | Vol: $($r.VolRatio)x -> _$($r.Status)_"
}

$fullText = $msgLines -join "`n"
[System.IO.File]::WriteAllText($reportFile, $fullText, [System.Text.Encoding]::UTF8)
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