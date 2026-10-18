---
name: trading-agents
description: >-
  Orchestrate, run, customize, and debug the TradingAgents multi-agent financial trading framework.
  Use this skill whenever the user asks to analyze stocks or crypto, run market/sentiment/news/fundamentals analysis,
  simulate trading debates, execute backtests, manage portfolio risk, or configure LLM trading models.
---

# TradingAgents Framework Skill

Chuyên môn hóa và quy trình thao tác chuẩn (SOP) để vận hành, cấu hình, và phát triển hệ thống đa tác tử tài chính **TradingAgents**.

---

## 1. Kiến trúc hệ thống tác tử (Agent Architecture)

TradingAgents chia quy trình phân tích và ra quyết định thành 4 giai đoạn nối tiếp:

1. **Analyst Team (Chạy song song)**:
   - `Market Analyst`: Phân tích kỹ thuật (SMA, EMA, MACD, RSI, Bollinger Bands, ATR, VWMA) với snapshot giá xác thực.
   - `Sentiment Analyst`: Đo lường tâm lý thị trường từ Yahoo News, StockTwits và Reddit (có thể lọc qua TypeSafe Jev).
   - `News Analyst`: Tổng hợp tin tức doanh nghiệp, kinh tế vĩ mô toàn cầu, chỉ số FRED và thị trường dự đoán Polymarket.
   - `Fundamentals Analyst`: Bóc tách báo cáo tài chính từ SEC EDGAR (chuẩn ngày nộp filing) và Yahoo Finance.
   - `Memory Log Node`: Đối soát kết quả các quyết định quá khứ và rút ra bài học kinh nghiệm (*Self-reflection*).

2. **Research Team Debate**:
   - `Bull Researcher` và `Bear Researcher` tranh biện phản biện đa vòng đối kháng.
   - `Research Manager` (Deep tier LLM) phân xử và lập bản kế hoạch đầu tư `ResearchPlan` (Buy / Overweight / Hold / Underweight / Sell).

3. **Trader Agent**:
   - Chuyển `ResearchPlan` thành đề xuất giao dịch cụ thể `TraderProposal` (Hướng lệnh, Giá vào lệnh, Cắt lỗ, Tỷ trọng).

4. **Risk Management & Portfolio Manager**:
   - `Aggressive`, `Conservative`, `Neutral Debators` thẩm định rủi ro đa chiều.
   - `Portfolio Manager` (Deep tier LLM) kết hợp ngữ cảnh danh mục hiện tại (`PortfolioContext`) và bài học quá khứ (`past_context`) để phê chuẩn quyết định cuối cùng `PortfolioDecision`.

---

## 2. Cấu hình biến môi trường (`.env`)

Các biến cấu hình quan trọng nhất trong file `.env`:

```bash
# Model Providers
OPENAI_API_KEY=...
GOOGLE_API_KEY=...
ANTHROPIC_API_KEY=...
DEEPSEEK_API_KEY=...

# Two-Tier Model Architecture (Quản lý cấp cao vs Phân tích/Tranh biện)
TRADINGAGENTS_DEEP_THINK_LLM=gpt-6-sol        # hoặc claude-opus-5-5, gemini-2.5-pro
TRADINGAGENTS_QUICK_THINK_LLM=gpt-6-luna      # hoặc gpt-4o, claude-3-7-sonnet
TRADINGAGENTS_LLM_PROVIDER=openai             # openai, google, anthropic, deepseek, ollama, etc.

# Dữ liệu bên ngoài (Tùy chọn)
FRED_API_KEY=...                              # Lấy chỉ số vĩ mô Mỹ/EU
ALPHA_VANTAGE_API_KEY=...                     # Dữ liệu tài chính/kỹ thuật nâng cao
TYPESAFE_API_KEY=...                          # Lọc bài đăng MXH qua Jev AI

# Dữ liệu chứng khoán Việt Nam (TCBS / TCInvest)
# Tùy chọn: Bearer token hoặc Cookie nếu dùng tài khoản TCBS có xác thực
TCBS_BEARER_TOKEN=
TCBS_COOKIE=
```

---

## 3. Các quy trình tác vụ thông dụng

### A. Phân tích cổ phiếu qua CLI
- **Giao diện tương tác trực tiếp**:
  ```bash
  python -m cli.main
  ```
- **Chế độ tự động / Unattended (chạy theo kịch bản)**:
  ```bash
  python -m cli.main --ticker NVDA --date 2026-09-01 --analysts market,news,fundamentals --save --no-show
  ```
- **Kèm danh mục hiện có để tính toán tỷ trọng**:
  ```bash
  python -m cli.main --ticker AAPL --portfolio path/to/portfolio.json
  ```

### B. Sử dụng trực tiếp bằng mã Python (Programmatic API)
```python
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph

config = DEFAULT_CONFIG.copy()
config["llm_provider"] = "openai"
config["deep_think_llm"] = "gpt-6-sol"
config["quick_think_llm"] = "gpt-6-luna"
config["output_language"] = "Vietnamese" # Hỗ trợ xuất báo cáo tiếng Việt

ta = TradingAgentsGraph(debug=True, config=config)

# Forward propagate
state, decision = ta.propagate("NVDA", "2026-09-01")
print(decision)

# Lưu bộ báo cáo hoàn chỉnh (Markdown + HTML)
ta.save_reports(state, "NVDA", html=True)
```

### C. Chạy Backtest đa mã & đa ngày
```bash
python -m cli.main backtest --tickers AAPL,MSFT,NVDA --start 2026-06-01 --end 2026-09-01 --every 5
```

### D. Kiểm tra kết quả & Nhật ký bài học
- **Báo cáo HTML khép kín**: Mở file `results/<ticker>/<trade_date>/complete_report.html` trên trình duyệt.
- **Nhật ký bộ nhớ đối soát**: Nằm tại `~/.tradingagents/memory/trading_memory.md`.
- **Trạng thái Checkpoint**: Nếu phiên chạy bị ngắt giữa chừng, có thể bật `--checkpoint` để khôi phục bước gần nhất.

---

## 4. Nguyên tắc dữ liệu Point-in-Time (Chống Lookahead Bias)
Khi phân tích một ngày trong quá khứ (`trade_date < today`):
1. Mọi truy vấn giá và chỉ báo kỹ thuật bị chốt chặn tối đa tại `trade_date`.
2. Dữ liệu tài chính SEC EDGAR chỉ lấy những báo cáo đã nộp trước hoặc đúng ngày đó.
3. Các bài học trong Memory Log chỉ được nạp nếu ngày giải quyết (`resolution_date`) diễn ra trước `trade_date`.

