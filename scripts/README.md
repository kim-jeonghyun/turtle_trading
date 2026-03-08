# Turtle Trading Scripts Reference (v2.0)

Complete reference for all operational scripts in the Turtle Trading system.

## Quick Reference

| Script | Category | Purpose | Frequency |
|--------|----------|---------|-----------|
| `collect_daily_ohlcv.py` | Data | OHLCV daily batch collection (~350 symbols) | Daily 16:00 cron |
| `check_positions.py` | Signal & Position | Entry/exit signals, stop-loss, pyramiding | Daily cron (KR 16:00, US 07:00) |
| `monitor_positions.py` | Signal & Position | Intraday stop-loss and P&L monitoring via KIS API | Every 5 min cron (market hours) |
| `check_risk_limits.py` | Risk | Portfolio risk limit monitoring with warnings | Hourly cron (market hours) |
| `auto_trade.py` | Trading | Automated order execution (dry-run default) | Manual |
| `toggle_trading.py` | Trading | Kill switch — enable/disable trading | Manual |
| `daily_report.py` | Reporting | Daily summary with positions, signals, and risk | Daily 08:00 cron |
| `weekly_report.py` | Reporting | Weekly performance summary with trade analysis | Saturday 09:00 cron |
| `fetch_universe_charts.py` | Chart | mplfinance chart generation for all universe symbols | Saturday 06:00 cron |
| `weekly_charts.sh` | Chart | Bash wrapper for local cron (logging, notification) | Saturday 06:00 cron |
| `performance_review.py` | Reporting | Historical performance analysis with statistics | Manual |
| `run_backtest.py` | Reporting | Strategy backtesting with equity curves | Manual |
| `health_check.py` | Operations | System health verification (core + external APIs) | Every 4 hours cron |
| `validate_data.py` | Operations | Data integrity check with auto-fix | Manual |
| `backup_data.sh` | Operations | Timestamped data backup with compression | Daily 02:00 cron |
| `cleanup_old_data.py` | Operations | Interactive cleanup of cache, logs, and backups | Manual |
| `security_check.py` | Operations | Credential and permission audit | Manual |
| `list_positions.py` | Query | View open/closed positions with P&L | Manual |
| `test_notifications.py` | Testing | Telegram, Discord, Email channel test | Manual |
| `deploy-v3.2.1.sh` | Legacy | One-time v3.2.1 deployment script | N/A |

---

## Category Details

### Data Pipeline

#### collect_daily_ohlcv.py

OHLCV daily batch collection for KOSPI 200 + KOSDAQ 150 (~350 symbols). Uses FDR primary, yfinance fallback with market-hint suffix ordering.

##### Usage

```bash
# Full collection
python scripts/collect_daily_ohlcv.py

# Dry-run (simulate without saving)
python scripts/collect_daily_ohlcv.py --dry-run

# Specific symbols only
python scripts/collect_daily_ohlcv.py --symbols 005930 000660

# Collect for a specific date
python scripts/collect_daily_ohlcv.py --date 2026-02-28
```

##### Key Arguments

| Argument | Description |
|----------|-------------|
| `--dry-run` | Simulate collection without saving to disk |
| `--symbols SYMBOL [SYMBOL ...]` | Override target symbols (ignores config file) |
| `--date YYYY-MM-DD` | Collect data for a specific date |

> Full argument list: `python scripts/collect_daily_ohlcv.py --help`

##### Cron Schedule

```
0 16 * * 1-5  # Mon-Fri after KR market close
```

> See [cron 작업 스케줄](../docs/operations-guide.md#cron-작업-스케줄) for the full schedule.

---

### Signal & Position

#### check_positions.py

Integrated position and signal check script -- detects new entry signals, exit signals, pyramiding opportunities, and stop-loss triggers for all universe symbols.

##### Usage

```bash
python scripts/check_positions.py
```

##### Key Arguments

None. This script has no CLI arguments; it loads configuration from `config/universe.yaml` and processes all enabled symbols automatically.

> This script uses file-based locking to prevent concurrent execution.

##### Cron Schedule

```
0 16 * * 1-5  # KR market close (Mon-Fri)
0 7 * * 2-6   # US market close in KST (Tue-Sat)
```

> See [cron 작업 스케줄](../docs/operations-guide.md#cron-작업-스케줄) for the full schedule.

---

#### monitor_positions.py

Intraday position monitoring via KIS API real-time prices. Checks stop-loss breaches and unrealized P&L thresholds with duplicate alert prevention (MonitorState). Only runs during market hours (internal `is_market_open` gate).

##### Usage

```bash
# Default monitoring
python scripts/monitor_positions.py

# With verbose logging
python scripts/monitor_positions.py --verbose

# Custom P&L warning threshold (default: 5%)
python scripts/monitor_positions.py --threshold 0.03

# Custom warning cooldown (default: 60 minutes)
python scripts/monitor_positions.py --warning-cooldown 30
```

##### Key Arguments

| Argument | Description |
|----------|-------------|
| `--threshold FLOAT` | Unrealized loss warning threshold (default: 0.05 = 5%) |
| `--warning-cooldown INT` | Minutes between repeated P&L warnings (default: 60) |
| `--verbose` | Enable debug-level logging |

> Full argument list: `python scripts/monitor_positions.py --help`

##### Cron Schedule

```
# KR market hours: 09:00-15:25 KST, Mon-Fri
*/5 9-14 * * 1-5
0,5,10,15,20,25 15 * * 1-5

# US market hours: DST-aware coverage 22:00-06:25 KST
*/5 22-23 * * 1-5
*/5 0-5 * * 2-6
0,5,10,15,20,25 6 * * 2-6
```

> See [cron 작업 스케줄](../docs/operations-guide.md#cron-작업-스케줄) for the full schedule.

---

### Risk Management

#### check_risk_limits.py

Portfolio risk limit monitor. Loads open positions, calculates current risk metrics (long/short units, N exposure, correlation group usage), and warns when approaching limits (>80%).

##### Usage

```bash
# Standard risk check
python scripts/check_risk_limits.py

# Custom warning threshold (default: 80%)
python scripts/check_risk_limits.py --warn-threshold 0.7

# Export metrics to JSON
python scripts/check_risk_limits.py --json data/risk_snapshot.json
```

##### Key Arguments

| Argument | Description |
|----------|-------------|
| `--warn-threshold FLOAT` | Warning threshold ratio (default: 0.8 = 80%) |
| `--json PATH` | Export risk metrics to JSON file |

> Full argument list: `python scripts/check_risk_limits.py --help`

##### Cron Schedule

```
# KR market hours: hourly 09-15 KST, Mon-Fri
0 9-15 * * 1-5

# US market hours: hourly 23-06 KST
0 23 * * 1-5
0 0-6 * * 2-6
```

> See [cron 작업 스케줄](../docs/operations-guide.md#cron-작업-스케줄) for the full schedule.

---

### Trading

#### auto_trade.py

Automated order execution based on Turtle Trading signals. **Dry-run is the default mode** -- use `--live` to execute real orders through the KIS API.

##### Usage

```bash
# Dry-run (default, safe)
python scripts/auto_trade.py

# Specific symbols, System 1 only
python scripts/auto_trade.py --symbols SPY QQQ --system 1

# Live trading (caution: real orders!)
python scripts/auto_trade.py --live --symbols SPY

# With order amount limit and verbose logging
python scripts/auto_trade.py --max-amount 1000000 --verbose
```

##### Key Arguments

| Argument | Description |
|----------|-------------|
| `--live` | Enable live trading mode (default: dry-run). Real orders will be placed! |
| `--symbols SYMBOL [SYMBOL ...]` | Target symbols (default: universe from config) |
| `--system {1,2}` | Trading system selection (1=20-day, 2=55-day, default: both) |
| `--max-amount FLOAT` | Maximum single order amount in KRW (default: 5,000,000) |
| `--verbose` | Verbose log output |

> Full argument list: `python scripts/auto_trade.py --help`

#### toggle_trading.py

Kill switch CLI — enable/disable all new trading entries. When disabled, BUY orders are blocked system-wide while SELL/exit orders (stop-loss, position closure) proceed normally.

> **Note**: This script is introduced in the kill switch feature (PR #110). It will be available after that PR merges to main.

##### Usage

```bash
# Disable trading (emergency stop)
python scripts/toggle_trading.py --disable --reason "시장 급변"

# Re-enable trading
python scripts/toggle_trading.py --enable

# Check current status
python scripts/toggle_trading.py --status
```

##### Key Arguments

| Argument | Description |
|----------|-------------|
| `--enable` | Resume trading |
| `--disable` | Halt all new entries (sells still allowed) |
| `--status` | Show current kill switch state |
| `--reason TEXT` | Reason for disabling (default: "수동 킬 스위치") |

> `--enable`, `--disable`, `--status` are mutually exclusive (exactly one required).

> Full argument list: `python scripts/toggle_trading.py --help`

##### Notes

- State is persisted in `config/system_status.yaml` via `KillSwitch` class in `src/kill_switch.py`
- Kill switch behavior and fail-open policy는 PR #110 머지 후 [운영 가이드](../docs/operations-guide.md)에 추가 예정

---

### Reporting & Analysis

#### daily_report.py

Daily summary report generation and delivery. Includes today's signals, open positions, risk summary, 30-day trade statistics, R-multiple distribution, and cache status.

##### Usage

```bash
python scripts/daily_report.py
```

##### Key Arguments

None. This script generates and sends the report automatically using the configured notification channels.

##### Cron Schedule

```
0 8 * * *  # Every day at 08:00 KST
```

> See [cron 작업 스케줄](../docs/operations-guide.md#cron-작업-스케줄) for the full schedule.

---

#### weekly_report.py

Weekly performance report with signals, closed trades, open positions, and risk status. Without `--send`, the report is generated but not delivered.

##### Usage

```bash
# Generate report (preview only, no delivery)
python scripts/weekly_report.py

# Generate and send via notification channels
python scripts/weekly_report.py --send

# With console output
python scripts/weekly_report.py --send --verbose
```

##### Key Arguments

| Argument | Description |
|----------|-------------|
| `--send` | Actually send the report via notification channels (default: preview only) |
| `--verbose` | Print report to console and enable detailed logging |

> Full argument list: `python scripts/weekly_report.py --help`

##### Cron Schedule

```
0 9 * * 6  # Saturday 09:00 KST (uses --send flag)
```

> See [cron 작업 스케줄](../docs/operations-guide.md#cron-작업-스케줄) for the full schedule.

---

#### performance_review.py

Historical trading performance analysis over a configurable period. Calculates total P&L, win rate, R-multiples, profit factor, and provides System 1 vs System 2 comparison.

##### Usage

```bash
# Default: 3-month review, all systems
python scripts/performance_review.py

# Last month, System 1 only
python scripts/performance_review.py --period 1m --system 1

# Full history with trade details
python scripts/performance_review.py --period all --verbose

# Export to CSV
python scripts/performance_review.py --period 6m --csv data/performance.csv
```

##### Key Arguments

| Argument | Description |
|----------|-------------|
| `--period {1m,3m,6m,1y,all}` | Analysis period (default: 3m) |
| `--system {1,2,all}` | System to analyze (default: all) |
| `--csv PATH` | Export closed trades to CSV |
| `--verbose` | Print individual trade details |

> Full argument list: `python scripts/performance_review.py --help`

---

#### run_backtest.py

Turtle Trading strategy backtester CLI. Runs historical simulations and outputs performance metrics, with optional equity curve charts and CSV trade exports.

##### Usage

```bash
# Basic backtest
python scripts/run_backtest.py --symbols SPY QQQ --period 2y --system 1

# With equity curve chart
python scripts/run_backtest.py --symbols SPY --system 2 --plot

# Custom capital and risk, export trades
python scripts/run_backtest.py --symbols AAPL NVDA TSLA --capital 500000 --risk 0.02 --csv results.csv
```

##### Key Arguments

| Argument | Description |
|----------|-------------|
| `--symbols SYMBOL [SYMBOL ...]` | Ticker symbols to backtest (required) |
| `--period PERIOD` | Data period: 1y, 2y, 5y, max, etc. (default: 2y) |
| `--system {1,2}` | Turtle system: 1=20/10-day, 2=55/20-day (default: 1) |
| `--capital FLOAT` | Initial capital (default: 100,000) |
| `--risk FLOAT` | Risk per unit as ratio (default: 0.01 = 1%) |
| `--commission FLOAT` | Commission rate (default: 0.001 = 0.1%) |
| `--no-filter` | Disable System 1 last-trade-profitable filter |
| `--plot` | Generate equity curve and drawdown chart (PNG) |
| `--csv PATH` | Export trade history to CSV |
| `--verbose` | Verbose logging |

> Full argument list: `python scripts/run_backtest.py --help`

---

### Chart Generation

#### fetch_universe_charts.py

mplfinance-based chart generation for all active universe symbols. Produces 3-panel PNG charts (candlestick + MA, volume, MACD) for each symbol.

##### Usage

```bash
# Generate charts for all universe symbols
python scripts/fetch_universe_charts.py

# Limit to first 5 symbols
python scripts/fetch_universe_charts.py --limit 5
```

##### Key Arguments

| Argument | Description |
|----------|-------------|
| `--limit INT` | Maximum number of symbols to render (default: all) |

> Output directory: `data/charts/YYYY-MM-DD/`

##### Cron Schedule

```
0 6 * * 6  # Saturday 06:00 KST (after US Friday close)
```

> See [cron 작업 스케줄](../docs/operations-guide.md#cron-작업-스케줄) for the full schedule.

---

#### weekly_charts.sh

Bash wrapper for local (non-Docker) cron execution of `fetch_universe_charts.py`. Adds logging, venv validation, failure notification via notifier, and automatic log cleanup (30 days).

##### Usage

```bash
# Direct execution
bash scripts/weekly_charts.sh

# Cron registration (local host)
crontab -e
# Add: 0 6 * * 6 /path/to/turtle_trading/scripts/weekly_charts.sh
```

##### Notes

- Docker environment uses `crontab` file directly (supercronic)
- Local environment uses this wrapper for logging and notification
- Logs are saved to `logs/weekly_charts/YYYY-MM-DD_HHMMSS.log`
- On failure, sends ERROR notification via configured channels (Telegram/Discord/Email)

---

### Operations & Maintenance

#### health_check.py

System health verification covering core checks (Python version, data directory, packages, position files, environment, data freshness, disk space) and external API connectivity (KIS, Telegram, yfinance).

##### Usage

```bash
python scripts/health_check.py
```

##### Key Arguments

None. All checks run automatically. Exit code 0 if all core checks pass, 1 otherwise. External API failures produce warnings but do not affect the exit code.

##### Cron Schedule

```
0 */4 * * *  # Every 4 hours
```

> See [cron 작업 스케줄](../docs/operations-guide.md#cron-작업-스케줄) for the full schedule.

---

#### validate_data.py

Data integrity validation for positions, entries, parquet cache files, and consistency checks. Supports auto-fix mode to remove invalid records and resolve duplicates.

##### Usage

```bash
# Check data integrity
python scripts/validate_data.py

# Check and auto-fix issues
python scripts/validate_data.py --fix
```

##### Key Arguments

| Argument | Description |
|----------|-------------|
| `--fix` | Auto-fix issues: remove invalid records, resolve duplicate position IDs |

> Full argument list: `python scripts/validate_data.py --help`

---

#### backup_data.sh

Backup positions, entries, cache, signals, trades, and config to a timestamped compressed archive. Automatically cleans up old backups (keeps last 30).

##### Usage

```bash
# Backup to default location (data/backups/)
bash scripts/backup_data.sh

# Backup to custom location
bash scripts/backup_data.sh /path/to/backup/dir
```

##### Key Arguments

| Argument | Description |
|----------|-------------|
| `$1` (positional) | Custom backup base directory (default: `data/backups`) |

> Note: `.env` is excluded from backups for security. Use a secrets manager or manual backup for credentials.

##### Cron Schedule

```
0 2 * * *  # Every day at 02:00 KST
```

> See [cron 작업 스케줄](../docs/operations-guide.md#cron-작업-스케줄) for the full schedule.

---

#### cleanup_old_data.py

Targeted, interactive cleanup of old cache files, log files, and backup archives. **Dry-run is the default** -- use `--execute` to actually delete files.

This script complements the crontab `find`-based cleanup commands:
- Crontab handles routine deletion: cache 7d+, logs 14d+, signals/trades parquet 90d+
- `cleanup_old_data.py` provides targeted, interactive cleanup with `--dry-run` preview and configurable thresholds

##### Usage

```bash
# Preview what would be deleted (default: dry-run)
python scripts/cleanup_old_data.py

# Actually delete old files
python scripts/cleanup_old_data.py --execute

# Custom thresholds
python scripts/cleanup_old_data.py --cache-days 14 --log-days 60 --keep-backups 10
```

##### Key Arguments

| Argument | Description |
|----------|-------------|
| `--dry-run` | Preview mode, no deletions (default) |
| `--execute` | Actually delete files (irreversible) |
| `--cache-days INT` | Delete cache files older than N days (default: 30) |
| `--log-days INT` | Delete log files older than N days (default: 90) |
| `--keep-backups INT` | Number of recent backups to keep (default: 30) |

> Full argument list: `python scripts/cleanup_old_data.py --help`

---

#### security_check.py

Security audit script that verifies `.env` file permissions and required credentials (KIS API keys, Telegram tokens) before live trading.

##### Usage

```bash
# Basic security check
python scripts/security_check.py

# Strict mode (warnings treated as failures)
python scripts/security_check.py --strict

# Auto-fix .env permissions (chmod 600)
python scripts/security_check.py --fix

# Strict + fix
python scripts/security_check.py --strict --fix
```

##### Key Arguments

| Argument | Description |
|----------|-------------|
| `--strict` | Treat warnings as failures (exit code 1) |
| `--fix` | Auto-fix `.env` file permissions to 600 (rw-------) |

> Full argument list: `python scripts/security_check.py --help`

---

### Query

#### list_positions.py

Display open and closed positions with P&L summary. Supports JSON output for scripting.

##### Usage

```bash
# Show open positions only (default)
python scripts/list_positions.py

# Include closed positions
python scripts/list_positions.py --all

# Filter by symbol
python scripts/list_positions.py --symbol SPY
python scripts/list_positions.py --symbol 005930.KS

# JSON output (for scripting)
python scripts/list_positions.py --json
```

##### Key Arguments

| Argument | Description |
|----------|-------------|
| `--all` | Include closed positions (shows recent 10) |
| `--json` | Output as JSON |
| `--symbol SYMBOL` | Filter by specific symbol |

> Full argument list: `python scripts/list_positions.py --help`

---

### Testing

#### test_notifications.py

Tests all notification channels (Telegram, Discord, Email) by sending test messages. Skips channels that are not configured.

##### Usage

```bash
python scripts/test_notifications.py
```

##### Key Arguments

None. The script automatically tests all configured channels based on environment variables.

---

### Legacy

#### deploy-v3.2.1.sh

One-time deployment script for v3.2.1 release. Not used in current workflow.

---

## Running in Docker

All scripts can be executed inside the Docker container:

```bash
# General pattern
docker compose exec turtle-cron python scripts/<script_name>.py [args]

# Examples
docker compose exec turtle-cron python scripts/check_positions.py
docker compose exec turtle-cron python scripts/health_check.py
docker compose exec turtle-cron python scripts/collect_daily_ohlcv.py --dry-run
docker compose exec turtle-cron python scripts/list_positions.py --all --json
docker compose exec turtle-cron bash scripts/backup_data.sh
```

---

## Cron vs Manual Scripts

Scripts fall into two categories based on execution mode:

**Cron scripts** run automatically on schedule inside the Docker container (managed by `supercronic`). See the "Frequency" column in the Quick Reference table for each script's schedule. Cron scripts can also be run manually at any time for debugging or ad-hoc execution.

**Manual scripts** are run on-demand by the operator. These include analysis tools (`performance_review.py`, `run_backtest.py`), query tools (`list_positions.py`), maintenance utilities (`validate_data.py`, `cleanup_old_data.py`, `security_check.py`), testing (`test_notifications.py`), trading execution (`auto_trade.py`), and the kill switch (`toggle_trading.py`).

> For the full cron schedule, see [cron 작업 스케줄](../docs/operations-guide.md#cron-작업-스케줄) in the operations guide.

---

## Troubleshooting

### health_check.py fails with import errors

```bash
# Install missing packages
pip install pandas numpy yfinance FinanceDataReader
```

### validate_data.py finds corrupted data

```bash
# Auto-fix corrupted data
python scripts/validate_data.py --fix

# If fix fails, restore from backup
tar -xzf data/backups/backup_LATEST.tar.gz -C .
```

### backup_data.sh fails with permission denied

```bash
# Make script executable
chmod +x scripts/backup_data.sh
```

### monitor_positions.py exits immediately

The script uses an internal `is_market_open()` gate. If no market is currently open, it exits silently. Check the current market status or run `check_positions.py` for end-of-day processing instead.

### Scripts fail with lock file errors

Scripts that use file-based locking (`check_positions.py`, `monitor_positions.py`, `auto_trade.py`, `collect_daily_ohlcv.py`) prevent concurrent execution. If a script terminates abnormally, stale lock files may remain:

```bash
# Remove stale lock files
rm -f data/.check_positions.lock
rm -f data/.monitor_positions.lock
rm -f data/.auto_trade.lock
rm -f /tmp/collect_daily_ohlcv.lock
```

---

## Version History

- **v2.0** (2026-03-03): Complete overhaul -- all 18 scripts documented, categorical organization, Docker integration
- **v1.0** (2026-02-17): Initial version -- 4 scripts documented
