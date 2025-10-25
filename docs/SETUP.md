# Broken Motor Parser Setup Guide

This project provides a Selenium-based scraper that compares German car listings with engine damage against drivable alternatives.

## Prerequisites
- Python 3.10 or newer
- Google Chrome 114+ (or Chromium) installed locally
- Internet access that allows browsing AutoScout24, Mobile.de, and optionally dasparking.de

> **Note:** Respect the terms of service for each marketplace. Limit scraping frequency and store only data you are legally permitted to keep.

## Installation Steps
1. **Clone the repository** and create a virtual environment:
   ```bash
   git clone <your-fork-url>
   cd codex
   python3 -m venv .venv
   source .venv/bin/activate
   ```

2. **Install dependencies** from `requirements.txt` (create it with the packages listed below) or directly via `pip`:
   ```bash
   pip install selenium webdriver-manager beautifulsoup4 pandas requests lxml matplotlib
   ```

3. **ChromeDriver management** is handled automatically through `webdriver-manager`. When the script runs for the first time it downloads the matching driver binary.

4. **Optional:** If you use a custom Chrome binary, point Selenium to it with:
   ```bash
   export CHROME_BINARY=/path/to/chrome
   ```
   and update `build_chrome_driver` in `broken_motor_parser.py` to include `options.binary_location = os.environ["CHROME_BINARY"]`.

## Usage
Run the scraper from the repository root after activating your virtual environment:
```bash
python broken_motor_parser.py --pages 3 --delay 3 6 --output data --plot -v
```

Arguments:
- `--pages`: Number of result pages per site to request (default: 2).
- `--delay MIN MAX`: Random delay range between page loads to reduce load (default: 2–4 seconds).
- `--output`: Destination directory for CSV files and optional charts (`output` by default).
- `--plot`: Generate a histogram chart comparing price distributions.
- `-v/--verbose`: Increase logging verbosity (`-vv` for debug output).

The script produces:
- `car_listings.csv`: Combined dataset of Motorschaden and Fahrbereit vehicles.
- `summary_by_model.csv`: Side-by-side comparison of aggregated metrics per make/model.
- `overall_summary.csv`: High-level statistics for each category.
- `price_distribution.png`: Optional histogram (when `--plot` is used).

## Handling Blocks & Retries
- The scraper rotates through multiple User-Agent strings and injects random delays.
- If AutoScout24 or Mobile.de reject Selenium traffic, the script retries with a fresh browser.
- When AutoScout24 Motorschaden listings cannot be fetched, the script falls back to dasparking.de to keep partial coverage.

## Legal & Ethical Use
Always review and respect the marketplaces' robots.txt and terms of service. Consider contacting the providers if you plan continuous or high-volume data collection.
