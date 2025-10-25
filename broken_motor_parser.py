"""Script to scrape car listings with and without engine damage from AutoScout24 and Mobile.de.

The script uses Selenium for dynamic content, BeautifulSoup for parsing,
and pandas for analysis. It optionally falls back to dasparking.de when the
primary sources are unavailable.
"""
from __future__ import annotations

import argparse
import csv
import logging
import math
import os
import random
import sys
import time
from dataclasses import dataclass, asdict
from typing import Iterable, List, Optional, Sequence, Tuple

import pandas as pd
import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager


LOGGER = logging.getLogger("broken_motor_parser")

USER_AGENTS: Sequence[str] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.6261.129 Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.6312.80 Mobile Safari/537.36",
)

BROKEN_KEYWORDS = ("motorschaden", "engine damage", "motor defekt")


@dataclass
class CarListing:
    source: str
    category: str
    title: str
    make: Optional[str]
    model: Optional[str]
    year: Optional[int]
    mileage_km: Optional[int]
    price_eur: Optional[float]
    fuel_type: Optional[str]
    transmission: Optional[str]
    url: str

    def to_dict(self) -> dict:
        payload = asdict(self)
        return payload


def configure_logging(verbosity: int) -> None:
    level = logging.WARNING
    if verbosity == 1:
        level = logging.INFO
    elif verbosity >= 2:
        level = logging.DEBUG
    logging.basicConfig(level=level, format="%(asctime)s [%(levelname)s] %(message)s")


def random_user_agent() -> str:
    return random.choice(USER_AGENTS)


def build_chrome_driver(headless: bool = True, user_agent: Optional[str] = None) -> webdriver.Chrome:
    options = Options()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--lang=de-DE")
    options.add_argument("--window-size=1920,1080")
    ua = user_agent or random_user_agent()
    options.add_argument(f"--user-agent={ua}")
    LOGGER.debug("Using user-agent: %s", ua)

    driver_path = ChromeDriverManager().install()
    driver = webdriver.Chrome(driver_path, options=options)
    driver.set_page_load_timeout(45)
    return driver


def wait_for_results(driver: webdriver.Chrome, selector: str, delay: Tuple[float, float]) -> None:
    time.sleep(random.uniform(*delay))
    try:
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))
    except TimeoutException:
        LOGGER.warning("Timed out waiting for selector %s", selector)


def parse_price(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    digits = "".join(ch for ch in value if ch.isdigit() or ch in ",.")
    digits = digits.replace(".", "").replace(",", ".")
    try:
        return float(digits)
    except ValueError:
        return None


def parse_year(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    for token in text.replace("/", " ").split():
        if token.isdigit() and len(token) == 4:
            year = int(token)
            if 1950 <= year <= 2100:
                return year
    return None


def parse_mileage(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def extract_make_model(title: str) -> Tuple[Optional[str], Optional[str]]:
    if not title:
        return None, None
    tokens = title.split()
    if len(tokens) < 2:
        return tokens[0], None
    return tokens[0], " ".join(tokens[1:3])


def has_broken_keyword(text: str) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in BROKEN_KEYWORDS)


def parse_autoscout_card(card) -> Optional[CarListing]:
    title_elem = card.select_one('[data-testid="title"]') or card.select_one("a h2")
    title = title_elem.get_text(strip=True) if title_elem else ""
    url_elem = card.select_one('a[data-testid="result-list-entry"]') or card.select_one("a")
    url = url_elem["href"] if url_elem and url_elem.has_attr("href") else ""
    if url and url.startswith("/"):
        url = f"https://www.autoscout24.de{url}"

    price_elem = card.select_one('[data-testid="price"]') or card.select_one('.Price_price__C7NoO')
    price = parse_price(price_elem.get_text(strip=True) if price_elem else None)

    detail_text = " ".join(detail.get_text(strip=True) for detail in card.select('[data-testid="spec"]'))
    year = parse_year(detail_text)
    mileage = parse_mileage(detail_text)

    fuel_elem = card.select_one('[data-testid="fuel"]')
    transmission_elem = card.select_one('[data-testid="transmission"]')

    make, model = extract_make_model(title)

    return CarListing(
        source="AutoScout24",
        category="",
        title=title,
        make=make,
        model=model,
        year=year,
        mileage_km=mileage,
        price_eur=price,
        fuel_type=fuel_elem.get_text(strip=True) if fuel_elem else None,
        transmission=transmission_elem.get_text(strip=True) if transmission_elem else None,
        url=url,
    )


def parse_mobile_card(card) -> Optional[CarListing]:
    title_elem = card.select_one(".cBox-body--resultitem .headline-block a") or card.select_one("a.headline")
    title = title_elem.get_text(strip=True) if title_elem else ""
    url = title_elem["href"] if title_elem and title_elem.has_attr("href") else ""
    if url and url.startswith("/"):
        url = f"https://suchen.mobile.de{url}"

    price_elem = card.select_one(".price-block span")
    price = parse_price(price_elem.get_text(strip=True) if price_elem else None)

    details = card.select(".vehicle-data li")
    detail_text = " ".join(item.get_text(strip=True) for item in details)
    year = parse_year(detail_text)
    mileage = parse_mileage(detail_text)

    fuel_elem = None
    transmission_elem = None
    for item in details:
        text = item.get_text(strip=True)
        if "Schaltgetriebe" in text or "Automatik" in text:
            transmission_elem = item
        if any(fuel in text.lower() for fuel in ("diesel", "benzin", "hybrid", "elektro", "lpg", "cng")):
            fuel_elem = item

    make, model = extract_make_model(title)

    return CarListing(
        source="Mobile.de",
        category="",
        title=title,
        make=make,
        model=model,
        year=year,
        mileage_km=mileage,
        price_eur=price,
        fuel_type=fuel_elem.get_text(strip=True) if fuel_elem else None,
        transmission=transmission_elem.get_text(strip=True) if transmission_elem else None,
        url=url,
    )


def parse_dasparking_card(card) -> Optional[CarListing]:
    title_elem = card.select_one(".vehicleTitle a")
    title = title_elem.get_text(strip=True) if title_elem else ""
    url = title_elem["href"] if title_elem and title_elem.has_attr("href") else ""
    price_elem = card.select_one(".price")
    price = parse_price(price_elem.get_text(strip=True) if price_elem else None)

    detail_text = card.get_text(" ", strip=True)
    year = parse_year(detail_text)
    mileage = parse_mileage(detail_text)
    make, model = extract_make_model(title)

    return CarListing(
        source="dasparking.de",
        category="",
        title=title,
        make=make,
        model=model,
        year=year,
        mileage_km=mileage,
        price_eur=price,
        fuel_type=None,
        transmission=None,
        url=url,
    )


def parse_cards(soup: BeautifulSoup, parser) -> List[CarListing]:
    listings: List[CarListing] = []
    for card in soup.select("article, div.listing, li.search-list-item"):
        try:
            listing = parser(card)
        except Exception as exc:  # pylint: disable=broad-except
            LOGGER.debug("Failed to parse card: %s", exc, exc_info=True)
            continue
        if listing and listing.title:
            listings.append(listing)
    return listings


def scrape_with_selenium(urls: Iterable[str], parser, result_selector: str, delay: Tuple[float, float]) -> List[CarListing]:
    listings: List[CarListing] = []
    retries = 2
    for attempt in range(retries + 1):
        try:
            driver = build_chrome_driver(headless=True)
        except WebDriverException as exc:
            LOGGER.error("Unable to initialize Chrome driver: %s", exc)
            raise

        try:
            for url in urls:
                LOGGER.info("Fetching %s", url)
                try:
                    driver.get(url)
                except WebDriverException as exc:
                    LOGGER.warning("Driver error fetching %s: %s", url, exc)
                    raise
                wait_for_results(driver, result_selector, delay)
                soup = BeautifulSoup(driver.page_source, "html.parser")
                listings.extend(parse_cards(soup, parser))
                time.sleep(random.uniform(*delay))
            driver.quit()
            break
        except WebDriverException as exc:
            LOGGER.error("Encountered driver error: %s", exc)
            driver.quit()
            if attempt == retries:
                raise
            LOGGER.info("Retrying with a fresh browser instance...")
            time.sleep(random.uniform(5, 8))
    return listings


def autoscout_urls(broken: bool, pages: int, keyword: str) -> List[str]:
    urls = []
    for page in range(1, pages + 1):
        params = {
            "sort": "price",
            "desc": "0",
            "offer": "U",
            "atype": "C",
            "cy": "D",
            "page": str(page),
            "ftxt": keyword,
        }
        if broken:
            params["damaged_listing"] = "1"
        else:
            params["damaged_listing"] = "0"
            params["pricefrom"] = "10000"
        query = "&".join(f"{key}={value}" for key, value in params.items())
        urls.append(f"https://www.autoscout24.de/lst?{query}")
    return urls


def mobile_urls(broken: bool, pages: int, keyword: str) -> List[str]:
    urls = []
    for page in range(1, pages + 1):
        params = {
            "isSearchRequest": "true",
            "scopeId": "C",
            "country": "DE",
            "categories": "Car",
            "sortOption.sortBy": "PRICE",
            "sortOption.sortOrder": "ASCENDING",
            "pageNumber": str(page),
            "grossPrice": "true",
            "makeModelVariant1.makeId": "",
            "makeModelVariant1.modelId": "",
            "searchId": "",
            "ref": "quickSearch",
            "features": keyword,
        }
        if broken:
            params["damageUnrepaired"] = "YES"
        else:
            params["damageUnrepaired"] = "NO_OR_UNKNOWN"
            params["minPrice"] = "10000"
        query = "&".join(f"{key}={value}" for key, value in params.items() if value)
        urls.append(f"https://suchen.mobile.de/fahrzeuge/search.html?{query}")
    return urls


def dasparking_urls(keyword: str, pages: int) -> List[str]:
    urls = []
    for page in range(1, pages + 1):
        urls.append(
            f"https://www.dasparking.de/de/auto-suche/?query={keyword}&page={page}&radius=0&country=de&category=pkw"
        )
    return urls


def scrape_dasparking(keyword: str, pages: int, delay: Tuple[float, float]) -> List[CarListing]:
    listings: List[CarListing] = []
    headers = {"User-Agent": random_user_agent(), "Accept-Language": "de-DE,de;q=0.9,en;q=0.8"}
    for url in dasparking_urls(keyword, pages):
        LOGGER.info("Fallback fetching %s", url)
        try:
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
        except requests.RequestException as exc:
            LOGGER.warning("Failed to fetch %s: %s", url, exc)
            continue
        soup = BeautifulSoup(response.text, "html.parser")
        listings.extend(parse_cards(soup, parse_dasparking_card))
        time.sleep(random.uniform(*delay))
    return listings


def filter_listings(listings: Iterable[CarListing], broken: bool) -> List[CarListing]:
    filtered: List[CarListing] = []
    for listing in listings:
        haystack = " ".join(filter(None, [listing.title, listing.url]))
        is_broken = has_broken_keyword(haystack)
        if broken and is_broken:
            listing.category = "Motorschaden"
            filtered.append(listing)
        elif not broken and not is_broken:
            listing.category = "Fahrbereit"
            filtered.append(listing)
    return filtered


def prepare_dataframe(listings: Sequence[CarListing]) -> pd.DataFrame:
    frame = pd.DataFrame([listing.to_dict() for listing in listings])
    if frame.empty:
        return frame
    frame["price_eur"] = pd.to_numeric(frame["price_eur"], errors="coerce")
    frame["mileage_km"] = pd.to_numeric(frame["mileage_km"], errors="coerce")
    frame["year"] = pd.to_numeric(frame["year"], errors="coerce")
    frame["make_model"] = frame.apply(
        lambda row: " ".join(filter(None, [row.get("make"), row.get("model")])) if row.get("make") else row.get("title"),
        axis=1,
    )
    return frame


def compute_summary(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    agg = (
        frame.groupby(["category", "make_model"])
        .agg(
            listings=("title", "count"),
            avg_price=("price_eur", "mean"),
            avg_mileage=("mileage_km", "mean"),
            min_year=("year", "min"),
            max_year=("year", "max"),
        )
        .reset_index()
    )
    agg["year_range"] = agg.apply(
        lambda row: f"{int(row.min_year)}-{int(row.max_year)}" if not math.isnan(row.min_year) and not math.isnan(row.max_year) else "",  # type: ignore[arg-type]
        axis=1,
    )
    broken_stats = agg[agg["category"] == "Motorschaden"].drop(columns=["category"]).add_suffix("_broken")
    ready_stats = agg[agg["category"] == "Fahrbereit"].drop(columns=["category"]).add_suffix("_ready")
    summary = pd.merge(
        broken_stats,
        ready_stats,
        left_on="make_model_broken",
        right_on="make_model_ready",
        how="outer",
    )
    summary["make_model"] = summary["make_model_broken"].fillna(summary["make_model_ready"])
    summary = summary.drop(columns=[col for col in summary.columns if col.startswith("make_model_")])
    columns_order = [
        "make_model",
        "listings_broken",
        "avg_price_broken",
        "avg_mileage_broken",
        "year_range_broken",
        "listings_ready",
        "avg_price_ready",
        "avg_mileage_ready",
        "year_range_ready",
    ]
    for column in columns_order:
        if column not in summary.columns:
            summary[column] = pd.NA
    summary = summary[columns_order]
    return summary.sort_values("make_model")


def describe_overall(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    records = []
    for category, group in frame.groupby("category"):
        records.append(
            {
                "category": category,
                "count": len(group),
                "avg_price": group["price_eur"].mean(),
                "median_price": group["price_eur"].median(),
                "avg_mileage": group["mileage_km"].mean(),
                "median_mileage": group["mileage_km"].median(),
                "year_min": group["year"].min(),
                "year_max": group["year"].max(),
            }
        )
    return pd.DataFrame.from_records(records)


def save_outputs(frame: pd.DataFrame, summary: pd.DataFrame, output_dir: str) -> None:
    os.makedirs(output_dir, exist_ok=True)
    data_path = os.path.join(output_dir, "car_listings.csv")
    summary_path = os.path.join(output_dir, "summary_by_model.csv")
    overall_path = os.path.join(output_dir, "overall_summary.csv")

    frame.to_csv(data_path, index=False, quoting=csv.QUOTE_NONNUMERIC)
    summary.to_csv(summary_path, index=False, quoting=csv.QUOTE_NONNUMERIC)
    describe_overall(frame).to_csv(overall_path, index=False, quoting=csv.QUOTE_NONNUMERIC)
    LOGGER.info("Saved detailed listings to %s", data_path)
    LOGGER.info("Saved summary table to %s", summary_path)


def build_visualizations(frame: pd.DataFrame, output_dir: str) -> Optional[str]:
    if frame.empty:
        return None
    import matplotlib.pyplot as plt  # Imported lazily to avoid unnecessary dependency when not used

    os.makedirs(output_dir, exist_ok=True)
    fig, ax = plt.subplots(figsize=(10, 6))
    for category, group in frame.groupby("category"):
        group["price_eur"].plot(kind="hist", bins=20, alpha=0.5, label=category, ax=ax)
    ax.set_title("Preisverteilung nach Kategorie")
    ax.set_xlabel("Preis in EUR")
    ax.set_ylabel("Anzahl der Angebote")
    ax.legend()
    output_path = os.path.join(output_dir, "price_distribution.png")
    fig.tight_layout()
    fig.savefig(output_path)
    plt.close(fig)
    LOGGER.info("Saved visualization to %s", output_path)
    return output_path


def collect_listings(max_pages: int, delay: Tuple[float, float]) -> Tuple[List[CarListing], List[CarListing]]:
    keyword = "motorschaden"
    broken_urls = autoscout_urls(True, max_pages, keyword)
    ready_urls = autoscout_urls(False, max_pages, keyword)
    mobile_broken_urls = mobile_urls(True, max_pages, keyword)
    mobile_ready_urls = mobile_urls(False, max_pages, keyword)

    broken_listings: List[CarListing] = []
    ready_listings: List[CarListing] = []

    try:
        broken_listings.extend(scrape_with_selenium(broken_urls, parse_autoscout_card, "article", delay))
    except WebDriverException:
        LOGGER.exception("Failed to scrape AutoScout24 broken listings, trying fallback")
        broken_listings.extend(scrape_dasparking(keyword, max_pages, delay))

    try:
        ready_listings.extend(scrape_with_selenium(ready_urls, parse_autoscout_card, "article", delay))
    except WebDriverException:
        LOGGER.exception("Failed to scrape AutoScout24 ready listings")

    try:
        broken_listings.extend(scrape_with_selenium(mobile_broken_urls, parse_mobile_card, "div.cBox-body--resultitem", delay))
    except WebDriverException:
        LOGGER.exception("Failed to scrape Mobile.de broken listings")

    try:
        ready_listings.extend(scrape_with_selenium(mobile_ready_urls, parse_mobile_card, "div.cBox-body--resultitem", delay))
    except WebDriverException:
        LOGGER.exception("Failed to scrape Mobile.de ready listings")

    broken_filtered = filter_listings(broken_listings, broken=True)
    ready_filtered = [listing for listing in filter_listings(ready_listings, broken=False) if (listing.price_eur or 0) >= 10000]
    return broken_filtered, ready_filtered


def run(max_pages: int, delay: Tuple[float, float], output_dir: str, build_plot: bool) -> None:
    broken_listings, ready_listings = collect_listings(max_pages, delay)
    combined = broken_listings + ready_listings
    frame = prepare_dataframe(combined)
    summary = compute_summary(frame)
    save_outputs(frame, summary, output_dir)
    if build_plot:
        build_visualizations(frame, output_dir)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape broken motor listings and compare to ready-to-drive cars.")
    parser.add_argument("--pages", type=int, default=2, help="Number of pages per site to scrape (default: 2)")
    parser.add_argument(
        "--delay",
        type=float,
        nargs=2,
        default=(2.0, 4.0),
        metavar=("MIN", "MAX"),
        help="Random delay range in seconds between requests",
    )
    parser.add_argument("--output", default="output", help="Directory to store the CSV and visualization")
    parser.add_argument("--plot", action="store_true", help="Generate histogram visualization")
    parser.add_argument("-v", "--verbose", action="count", default=0, help="Increase log verbosity")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = parse_args(argv)
    configure_logging(args.verbose)
    delay = (min(args.delay), max(args.delay))
    LOGGER.info("Starting scraper with %s pages and delay range %s", args.pages, delay)
    run(args.pages, delay, args.output, args.plot)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        LOGGER.info("Interrupted by user")
        sys.exit(1)
