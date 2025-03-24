import json
import time
import os
import re
import imaplib
import email
from email.header import decode_header
from datetime import datetime, timedelta
from selenium import webdriver
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from bs4 import BeautifulSoup
from dotenv import load_dotenv
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from collections import defaultdict

# Load environment variables from .env file
load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, "data.json")

# --- Filter Combos ---

# Combos for wildearth website (currently empty, as per your snippet)
FILTER_COMBOS_WILDEARTH = [
    {"brand": ["Arc'teryx"], "gender": ["Men"], "size": ["S", "28", "US8.5", "US9"], "threshold": 29},
    {"brand": ["Arc'teryx"], "gender": ["Unisex"], "size": [], "threshold": 29},
    {"brand": ["Patagonia"], "gender": ["Men"], "size": ["S", "28"], "threshold": 39},
    {"brand": ["Patagonia"], "gender": ["Unisex"], "size": [], "threshold": 39},
    {"brand": ["Mammut"], "gender": ["Men"], "size": ["S", "28"], "threshold": 39},
    {"brand": ["Icebreaker"], "gender": ["Men"], "size": ["S"], "threshold": 39},
    {"brand": ["Icebreaker"], "gender": ["Unisex"], "size": [], "threshold": 39},
    {"brand": ["Salomon"], "gender": ["Men"], "size": ["US8.5", "US9"], "threshold": 32},
    {"brand": ["The$2520North$2520Face"], "gender": ["Men"], "size": ["S", "28"], "threshold": 39},
    {"brand": ["The$2520North$2520Face"], "gender": ["Unisex"], "size": [], "threshold": 39}
]

# Combos for findyourfeet website
FILTER_COMBOS_FINDYOURFEET = [
    {"brand": ["Arcteryx"], "gender": ["Men", "Unisex"], "size": ["S", "28", "9.0+US-M+%2F+8.5+UK+%2F+42.5+EUR", "8.5+US-M+%2F+8.0+UK+%2F+42.0+EUR"], "threshold": 29},
    {"brand": ["Patagonia"], "gender": ["Men", "Unisex"], "size": ["S", "28"], "threshold": 39},
    {"brand": ["Mammut"], "gender": ["Men", "Unisex"], "size": ["S", "28", "9.0+US-M+%2F+8.5+UK+%2F+42.5+EUR", "8.5+US-M+%2F+8.0+UK+%2F+42.0+EUR"], "threshold": 39},
    {"brand": ["Icebreaker"], "gender": ["Men", "Unisex"], "size": ["S"], "threshold": 39},
    {"brand": ["Salomon"], "gender": ["Men", "Unisex"], "size": ["S", "9.0+US-M+%2F+8.5+UK+%2F+42.5+EUR", "8.5+US-M+%2F+8.0+UK+%2F+42.0+EUR"], "threshold": 32},
    {"brand": ["The+North+Face"], "gender": ["Men", "Unisex"], "size": ["S", "9.0+US-M+%2F+8.5+UK+%2F+42.5+EUR", "8.5+US-M+%2F+8.0+UK+%2F+42.0+EUR"], "threshold": 39},
    {"brand": ["On+Running"], "gender": ["Men", "Unisex"], "size": ["S", "9.0+US-M+%2F+8.5+UK+%2F+42.5+EUR", "8.5+US-M+%2F+8.0+UK+%2F+42.0+EUR"], "threshold": 39}
]

# --- Brand Mapping for Normalization ---
BRAND_MAP = {
    "Arc'teryx": ["Arcteryx", "Arc'teryx"],
    "The North Face": ["The+North+Face", "The$2520North$2520Face"],
    "On Running": ["On+Running"]
}

def normalize_brand(brand):
    for canonical, aliases in BRAND_MAP.items():
        if brand in aliases:
            return canonical
    return brand

# --- Selenium Driver using Firefox (lightweight for GitHub Actions) ---
def get_driver():
    options = FirefoxOptions()
    options.add_argument("--headless")
    return webdriver.Firefox(options=options)

# --- Wildearth Functions ---
def build_url_wildearth(filters):
    url = "https://www.wildearth.com.au/view/sale#/filter:is_sale:1"
    for f_type, values in filters.items():
        if f_type == "threshold":
            continue
        filter_name = "child_sizes" if f_type == "size" else f_type
        for val in values:
            url += f"/filter:{filter_name}:{val}"
    return url

def scrape_products_wildearth(combo):
    url = build_url_wildearth(combo)
    print(f"   🌐 URL: {url}")
    threshold = combo.get("threshold", 25)
    driver = get_driver()
    driver.get(url)
    time.sleep(5)
    while True:
        try:
            load_more = driver.find_element("css selector", "button.ss__pagination__button")
            if load_more.is_displayed():
                driver.execute_script("arguments[0].click();", load_more)
                time.sleep(3)
            else:
                break
        except Exception:
            break
    soup = BeautifulSoup(driver.page_source, "html.parser")
    driver.quit()
    if "No results found" in soup.text:
        return []
    results = []
    for container in soup.select("article.ss__result"):
        try:
            details = container.select_one("div.ss__result__details")
            name = details.select_one("h3.ss__result__name a").text.strip()
            link = details.select_one("h3.ss__result__name a")["href"]
            original_tag = details.select_one("span.ss__result__msrp")
            sale_tag = details.select_one("span.ss__result__price--on-sale")
            if not original_tag or not sale_tag:
                continue
            original = float(original_tag.text.replace("$", "").replace(",", ""))
            sale = float(sale_tag.text.replace("$", "").replace(",", ""))
            discount = round((original - sale) / original * 100)
            image_tag = container.select_one("figure.ss__result__image img")
            image_url = image_tag["src"] if image_tag else ""
            if discount >= threshold:
                results.append({
                    "name": name,
                    "link": link,
                    "original": original,
                    "sale": sale,
                    "discount": discount,
                    "image": image_url,
                    "brand": normalize_brand(combo["brand"][0]),
                    "gender": combo["gender"][0]
                })
        except Exception:
            continue
    return results

# --- FindYourFeet Functions ---
def build_url_findyourfeet(filters):
    base_url = "https://findyourfeet.com.au/collections/sale"
    params = ["filter.v.availability=1"]  # Always include availability filter
    for f_type, values in filters.items():
        if f_type in ["threshold", "gender"]:
            continue
        if f_type == "brand":
            for val in values:
                params.append(f"filter.p.vendor={val}")
        elif f_type == "size":
            for val in values:
                params.append(f"filter.v.option.size={val}")
    query_string = "?" + "&".join(params) if params else ""
    return base_url + query_string

def scrape_products_findyourfeet(combo):
    url = build_url_findyourfeet(combo)
    print(f"   🌐 URL: {url}")
    threshold = combo.get("threshold", 25)
    driver = get_driver()
    driver.get(url)
    time.sleep(5)
    results = []
    while True:
        soup = BeautifulSoup(driver.page_source, "html.parser")
        if "No products match those filters" in soup.text:
            break
        product_cards = soup.find_all("product-card")
        for card in product_cards:
            try:
                title_tag = card.select_one("span.product-card__title a")
                if not title_tag:
                    continue
                title = title_tag.get_text(strip=True)
                # Determine product gender from title.
                title_lower = title.lower()
                if any(g in title_lower for g in ["(women)", "(women's)", "(womens)"]):
                    detected_gender = "Women"
                elif any(g in title_lower for g in ["(men)", "(men's)", "(mens)"]):
                    detected_gender = "Men"
                else:
                    detected_gender = "Unisex"
                # Apply gender filter from combo.
                if detected_gender not in combo.get("gender", []):
                    continue
                image_tag = card.select_one("div.product-card__figure img")
                image = ""
                if image_tag:
                    if image_tag.has_attr("src"):
                        image = image_tag["src"]
                    elif image_tag.has_attr("data-src"):
                        image = image_tag["data-src"]
                    elif image_tag.has_attr("data-original"):
                        image = image_tag["data-original"]
                    if image.startswith("//"):
                        image = "https:" + image
                sale_price_tag = card.select_one("sale-price.text-on-sale")
                if sale_price_tag:
                    sale_text = sale_price_tag.get_text(strip=True)
                    sale_match = re.search(r"(\d+\.\d+)", sale_text)
                    if sale_match:
                        sale = float(sale_match.group(1))
                    else:
                        continue
                else:
                    continue
                original_price_tag = card.select_one("compare-at-price.text-subdued.line-through")
                if original_price_tag:
                    original_text = original_price_tag.get_text(strip=True)
                    original_match = re.search(r"(\d+\.\d+)", original_text)
                    if original_match:
                        original = float(original_match.group(1))
                    else:
                        continue
                else:
                    continue
                link_tag = card.select_one("div.product-card__figure a")
                link = link_tag["href"] if link_tag and link_tag.has_attr("href") else ""
                if link.startswith("/"):
                    link = "https://findyourfeet.com.au" + link
                discount = round((original - sale) / original * 100)
                if discount >= threshold:
                    results.append({
                        "name": title,
                        "link": link,
                        "original": original,
                        "sale": sale,
                        "discount": discount,
                        "image": image,
                        "brand": normalize_brand(combo["brand"][0]),
                        "gender": detected_gender
                    })
            except Exception:
                continue
        pagination = soup.select_one("nav.collection__pagination")
        if pagination:
            next_link_tag = pagination.select_one("a[rel='next']")
            if next_link_tag and next_link_tag.get("href"):
                next_url = "https://findyourfeet.com.au" + next_link_tag.get("href")
                driver.get(next_url)
                time.sleep(5)
                continue
        break
    driver.quit()
    return results

# --- Data Handling ---
def load_previous_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE) as f:
            data = json.load(f)
            return data.get("items", []), data.get("last_run")
    return [], None

def save_data(items, timestamp):
    with open(DATA_FILE, "w") as f:
        json.dump({"last_run": timestamp, "items": items}, f, indent=2)

# --- Email Generation ---
def generate_email(grouped):
    html = "<h1>🎯 DealTracker Update</h1>"
    for brand, items in grouped.items():
        items_sorted = sorted(items, key=lambda x: x["discount"], reverse=True)
        html += f"<h2>{brand}</h2><table><tr>"
        for i, item in enumerate(items_sorted):
            html += f"""
            <td style='padding:10px;text-align:center;'>
            <img src='{item['image']}' width='100'><br>
            <b>{item['name']}</b><br>
            ${item['original']:.2f}→<b>${item['sale']:.2f}</b> ({item['discount']}% off)<br>
            <a href='{item['link']}'>View</a></td>"""
            if (i+1) % 3 == 0:
                html += "</tr><tr>"
        html += "</tr></table>"
    return html

def send_email(subject, html_body):
    sender = os.getenv("EMAIL_SENDER")
    receiver = os.getenv("EMAIL_RECEIVER")
    password = os.getenv("EMAIL_PASSWORD")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"🏷️DealTracker<{sender}>"
    msg["To"] = receiver
    msg.attach(MIMEText(html_body, "html"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, password)
        server.send_message(msg)

# --- Email Inbox Monitoring and Clean Command ---
def check_clean_command(last_run_time):
    imap_host = "imap.gmail.com"
    username = os.getenv("EMAIL_SENDER")
    password = os.getenv("EMAIL_PASSWORD")
    try:
        mail = imaplib.IMAP4_SSL(imap_host)
        mail.login(username, password)
        mail.select("inbox")
        result, data = mail.search(None, '(SUBJECT "Clean")')
        email_ids = data[0].split()
        for eid in email_ids:
            res, msg_data = mail.fetch(eid, "(RFC822)")
            if res != "OK":
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            date_tuple = email.utils.parsedate_tz(msg.get("Date"))
            if date_tuple:
                email_time = datetime.fromtimestamp(email.utils.mktime_tz(date_tuple))
                if not last_run_time or email_time > last_run_time:
                    # Reply to sender
                    reply_subject = "Re: " + (msg.get("Subject") or "Clean")
                    reply_body = "Data has been cleared as per your request."
                    send_email(reply_subject, reply_body)
                    mail.logout()
                    return True
        mail.logout()
    except Exception as e:
        print("Error checking inbox:", e)
    return False

# --- Main Function ---
def main():
    current_time = datetime.now()
    previous_data, last_run_time = load_previous_data()
    print(f"✅ Loaded {len(previous_data)} previous items.")
    print(f"⏰ Last run time: {last_run_time}")

    # If a clean command email was received after last run, clear data
    if check_clean_command(datetime.fromisoformat(last_run_time) if last_run_time else None):
        print("🧹 Clean command detected. Clearing data.json.")
        previous_data = []

    prev_links = {item["link"] for item in previous_data}
    prev_names = {item["name"] for item in previous_data}

    all_current_data = []
    new_deals_grouped = defaultdict(list)

    # Process wildearth combos
    print(f"🚀 Starting scraping for {len(FILTER_COMBOS_WILDEARTH)} wildearth filter combos...")
    for idx, combo in enumerate(FILTER_COMBOS_WILDEARTH, 1):
        print(f"\n[{idx}/{len(FILTER_COMBOS_WILDEARTH)}] 🛒 Processing wildearth combo: {combo}")
        current_items = scrape_products_wildearth(combo)
        print(f"   📦 Found {len(current_items)} items for this combo.")
        for item in current_items:
            all_current_data.append(item)
            if item["link"] not in prev_links:
                new_deals_grouped[item["brand"]].append(item)
                print(f"   ➕ New deal found: {item['name']} - ${item['original']}→${item['sale']} ({item['discount']}% off)")

    # Process findyourfeet combos
    print(f"\n🚀 Starting scraping for {len(FILTER_COMBOS_FINDYOURFEET)} findyourfeet filter combos...")
    for idx, combo in enumerate(FILTER_COMBOS_FINDYOURFEET, 1):
        print(f"\n[{idx}/{len(FILTER_COMBOS_FINDYOURFEET)}] 🛒 Processing findyourfeet combo: {combo}")
        current_items = scrape_products_findyourfeet(combo)
        print(f"   📦 Found {len(current_items)} items for this combo.")
        for item in current_items:
            all_current_data.append(item)
            if item["name"] not in prev_names:
                new_deals_grouped[item["brand"]].append(item)
                print(f"   ➕ New deal found: {item['name']} - ${item['original']}→${item['sale']} ({item['discount']}% off)")

    if new_deals_grouped:
        print("\n📧 Preparing email with new deals...")
        html_body = generate_email(new_deals_grouped)
        subject = "💥 New Deals: " + ", ".join(
            f"{brand} ({max(item['discount'] for item in items)}% off)"
            for brand, items in new_deals_grouped.items()
        )
        print(f"📨 Sending email: '{subject}'")
        send_email(subject, html_body)
        print("✅ Email sent successfully!")
    else:
        print("\nℹ️ No new deals found this time.")

    # Append new deals to previous data and save combined list.
    combined_data = previous_data + [item for item in all_current_data if item["link"] not in prev_links]
    print("💾 Saving data.json with a total of", len(combined_data), "items.")
    save_data(combined_data, current_time.isoformat())
    print("✅ Data saved successfully.")

if __name__ == "__main__":
    main()