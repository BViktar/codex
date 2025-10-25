## Broken Motor Parser

This repository now includes `broken_motor_parser.py`, a Selenium + BeautifulSoup tool that compares German car listings with engine damage to road-ready vehicles priced above €10,000. It supports AutoScout24.de and Mobile.de, with dasparking.de as a fallback when scraping protections block access.

### Quick Start
1. Create and activate a virtual environment.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Run the scraper (example command):
   ```bash
   python broken_motor_parser.py --pages 3 --delay 2 5 --output data --plot -v
   ```

Detailed setup guidance, ChromeDriver notes, and usage tips are available in [`docs/SETUP.md`](docs/SETUP.md).
