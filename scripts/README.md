# Turtle Trading Operational Scripts

Essential maintenance and monitoring scripts for the Turtle Trading system.

## Quick Reference

| Script | Purpose | Frequency |
|--------|---------|-----------|
| `health_check.py` | System health verification | Daily (cron) |
| `list_positions.py` | View open/closed positions | On-demand |
| `validate_data.py` | Data integrity check | Weekly |
| `backup_data.sh` | Backup all data | Daily (before trading) |

---

## 1. health_check.py

System health check that verifies all components are working correctly.

### Usage

```bash
# Basic health check
python scripts/health_check.py

# In cron (daily at 8:00 AM)
0 8 * * * cd /Users/momo/dev/turtle_trading && .venv/bin/python3 scripts/health_check.py
```

### Checks Performed

1. **Data Directory** - Exists and writable
2. **Python Packages** - pandas, numpy, yfinance, FinanceDataReader importable
3. **Position Files** - Valid JSON format
4. **Environment** - Required variables set (.env)
5. **Data Freshness** - Cache updated within 7 days
6. **Disk Space** - At least 1GB free

### Exit Codes

- `0` - All checks passed
- `1` - One or more checks failed

### Example Output

```
=== Turtle Trading System Health Check ===

[OK]   Data directory: data/
[OK]   Python packages: pandas, numpy, yfinance, FinanceDataReader
[OK]   Position file: valid (2 open positions)
[WARN] Environment: TELEGRAM_CHAT_ID not set
[OK]   Data freshness: last update 2h ago
[OK]   Disk space: 691.8GB free

=== 5/6 checks passed ===
```

---

## 2. list_positions.py

Display open and closed positions with P&L summary.

### Usage

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

### Arguments

- `--all` - Include closed positions (shows recent 10)
- `--json` - Output as JSON
- `--symbol SYMBOL` - Filter by specific symbol

### Example Output

```
=== Open Positions ===

Symbol       | System | Direction | Entry      | Units | Stop Loss  | Last Update
------------------------------------------------------------------------------------------
SPY          | S1     | LONG      | $485.20    | 1/4   | $460.60    | 2026-02-17
005930.KS    | S2     | LONG      | ₩72,000    | 1/4   | ₩67,800    | 2026-02-17

Total Open: 2 positions

=== Summary ===
Total Positions: 2
Open: 2, Closed: 0
Total P&L: $0.00
Win Rate: 0.0% (0/0 wins)
Average R-Multiple: 0.00R
```

### JSON Output Format

```json
[
  {
    "position_id": "SPY_1_LONG_20260217_114529",
    "symbol": "SPY",
    "system": 1,
    "direction": "LONG",
    "entry_date": "2026-02-17",
    "entry_price": 485.2,
    "units": 1,
    "total_shares": 100,
    "stop_loss": 460.6,
    "status": "open"
  }
]
```

---

## 3. validate_data.py

Data integrity validation with auto-fix capability.

### Usage

```bash
# Check data integrity
python scripts/validate_data.py

# Check and auto-fix issues
python scripts/validate_data.py --fix
```

### Validations Performed

1. **Position JSON Schema** - All required fields present
2. **Entry JSON Schema** - Valid entry records
3. **Parquet Files** - Readable, not corrupted
4. **Data Consistency** - No duplicate position IDs
5. **Date Range** - No future dates
6. **Price Sanity** - No negative prices or extreme outliers

### Auto-Fix Capabilities

When `--fix` is used:
- Removes invalid position records
- Removes invalid entry records
- Removes duplicate position IDs (keeps most recent)

### Example Output

```
=== Data Validation Report ===

[OK]   Positions: 2 records, all valid
[OK]   Entries: 2 records, all valid
[WARN] Cache: 2 stale files (> 30 days)
[OK]   Signals: 0 records, all valid
[OK]   Consistency: no duplicate position IDs
[OK]   Date range: all dates valid
[OK]   Price sanity: all prices valid

=== Validation complete: 0 errors, 1 warning ===
```

### Exit Codes

- `0` - No errors
- `1` - Errors found

---

## 4. backup_data.sh

Backup all critical data to timestamped archive.

### Usage

```bash
# Backup to default location (data/backups/)
./scripts/backup_data.sh

# Backup to custom location
./scripts/backup_data.sh /path/to/backup/dir

# In cron (daily at 7:00 AM before trading)
0 7 * * * cd /Users/momo/dev/turtle_trading && ./scripts/backup_data.sh
```

### What Gets Backed Up

- `data/positions/` - All position records
- `data/entries/` - All entry records
- `data/cache/` - OHLCV cache files
- `data/signals/` - Signal history
- `data/trades/` - Trade history
- `config/` - Configuration files
- `.env` - Environment variables

### Features

- **Timestamped Archives** - `backup_YYYY-MM-DD_HHMMSS.tar.gz`
- **Compression** - tar.gz for space efficiency
- **Auto-Cleanup** - Keeps last 30 backups, deletes older
- **Size Reporting** - Shows backup file size

### Example Output

```
=== Turtle Trading Data Backup ===
Backup directory: data/backups/2026-02-17_114514

Backing up: data/positions
Backing up: data/entries
Backing up: data/cache
Backing up: .env

Compressing to: data/backups/backup_2026-02-17_114514.tar.gz
Backup complete!
  - Files backed up: 7
  - Archive size: 8.0K
  - Location: data/backups/backup_2026-02-17_114514.tar.gz

=== Backup Summary ===
Total backups: 1
Latest: data/backups/backup_2026-02-17_114514.tar.gz

To restore from this backup:
  tar -xzf data/backups/backup_2026-02-17_114514.tar.gz -C .
```

### Restore Data

```bash
# Restore from backup
tar -xzf data/backups/backup_2026-02-17_114514.tar.gz -C .

# Restore to specific directory
tar -xzf data/backups/backup_2026-02-17_114514.tar.gz -C /tmp/restore/
```

---

## Recommended Cron Schedule

Add to crontab (`crontab -e`):

```bash
# Turtle Trading System Automation
PROJECT_DIR="/Users/momo/dev/turtle_trading"

# Daily backup at 7:00 AM (before market open)
0 7 * * * cd $PROJECT_DIR && ./scripts/backup_data.sh

# Health check at 8:00 AM
0 8 * * * cd $PROJECT_DIR && .venv/bin/python3 scripts/health_check.py

# Data validation every Sunday at 6:00 PM
0 18 * * 0 cd $PROJECT_DIR && .venv/bin/python3 scripts/validate_data.py
```

---

## Troubleshooting

### health_check.py fails with import errors

```bash
# Install missing packages
.venv/bin/pip install pandas numpy yfinance FinanceDataReader
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

---

## Integration with Other Scripts

### Use in Python

```python
import subprocess
import json

# Run health check
result = subprocess.run(
    ['python', 'scripts/health_check.py'],
    capture_output=True,
    text=True
)
print(f"Health check: {'PASS' if result.returncode == 0 else 'FAIL'}")

# Get positions as JSON
result = subprocess.run(
    ['python', 'scripts/list_positions.py', '--json'],
    capture_output=True,
    text=True
)
positions = json.loads(result.stdout)
print(f"Open positions: {len(positions)}")
```

### Use in Shell Scripts

```bash
#!/bin/bash

# Backup before trading
./scripts/backup_data.sh

# Check health
if ! python scripts/health_check.py; then
    echo "Health check failed! Review errors before trading."
    exit 1
fi

# Your trading logic here
python scripts/daily_signal_check.py
```

---

## File Locations

All scripts assume the following structure:

```
turtle_trading/
├── scripts/
│   ├── health_check.py
│   ├── list_positions.py
│   ├── validate_data.py
│   └── backup_data.sh
├── data/
│   ├── positions/
│   │   └── positions.json
│   ├── entries/
│   │   └── entries.json
│   ├── cache/
│   ├── backups/
│   └── ...
├── config/
├── .env
└── src/
    ├── position_tracker.py
    └── utils.py
```

---

## Testing

Test all scripts after installation:

```bash
# Test health check
python scripts/health_check.py

# Test position listing
python scripts/list_positions.py

# Test validation
python scripts/validate_data.py

# Test backup
./scripts/backup_data.sh test_backup

# Verify backup
ls -lh test_backup/
```

---

## Other Scripts

### run_backtest.py
Backtest Turtle Trading strategy. See backtest documentation for details.

### check_positions.py
Check current open positions.

### test_notifications.py
Test notification system (Telegram/Discord/Email).

---

## Version History

- **v1.0** (2026-02-17) - Initial release with 4 essential operational scripts
