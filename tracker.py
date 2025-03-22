import json
import time
import os
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from bs4 import BeautifulSoup
from dotenv import load_dotenv
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# Define base directory and data file (one shared JSON for all combos)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, "data.json")
DISCOUNT_THRESHOLD = 25  # percent

# Brand-Gender-Size combos
COMBOS = [
    ("Arcteryx", "Men", "S"),
    ("Patagonia", "Unisex", None),
    ("Patagonia", "Women", "M"),
]

# --- Setup headless Chrome ---
def get_driver():
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    return webdriver.Chrome(options=options)

# --- Extract product data including images ---
def scrape_products(brand, gender, size):
    url = f"https://www.wildearth.com.au/brand/{brand}#/filter:is_sale:1/filter:gender:{gender}"
    if size:
        url += f"/filter:child_sizes:{size}"

    driver = get_driver()
    driver.get(url)
    time.sleep(5)
    soup = BeautifulSoup(driver.page_source, "html.parser")
    driver.quit()

    results = []
    containers = soup.select("article.ss__result")
    for container in containers:
        try:
            details = container.select_one("div.ss__result__details")
            name_tag = details.select_one("h3.ss__result__name a")
            name = name_tag.text.strip()
            link = name_tag["href"]

            original_price_tag = details.select_one("span.ss__result__msrp")
            sale_price_tag = details.select_one("span.ss__result__price--on-sale")
            if not original_price_tag or not sale_price_tag:
                continue

            original = float(original_price_tag.text.replace("$", "").replace(",", ""))
            sale = float(sale_price_tag.text.replace("$", "").replace(",", ""))
            discount = round((original - sale) / original * 100)

            image_tag = container.select_one("figure.ss__result__image img")
            image_url = image_tag["src"] if image_tag and image_tag.has_attr("src") else ""

            if discount >= DISCOUNT_THRESHOLD:
                results.append({
                    "name": name,
                    "link": link,
                    "original": original,
                    "sale": sale,
                    "discount": discount,
                    "image": image_url,
                    "brand": brand,
                    "gender": gender,
                    "size": size
                })
        except Exception as e:
            print("Error parsing product:", e)
    return results

# --- Load stored data ---
def load_previous_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return []

# --- Save current data ---
def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

# --- Generate HTML ---
def generate_html_email(grouped):
    html = "<h1>🏕️ DealTracker Update</h1>"
    for combo_key, data in grouped.items():
        brand, gender, size = combo_key.split("|")
        title = f"{brand} - {gender}" + (f" - Size {size}" if size != "None" else "")
        new_items = data["new"]
        existing_items = data["existing"]

        html += f"<h2>{title}</h2>"

        for section_title, items in [("🆕 New Items", new_items), ("📦 Existing Items", existing_items)]:
            if not items:
                continue
            html += f"<h3>{section_title}</h3><table><tr>"
            for i, item in enumerate(items):
                html += f"""
                <td style='padding:10px; text-align:center;'>
                    <img src='{item['image']}' width='100'><br>
                    <b>{item['name']}</b><br>
                    <small>${item['original']:.2f} → <b>${item['sale']:.2f}</b> ({item['discount']}% off)</small><br>
                    <a href='{item['link']}'>View</a>
                </td>
                """
                if (i + 1) % 3 == 0:
                    html += "</tr><tr>"
            html += "</tr></table>"
    return html

# --- Send email ---
def send_email(subject, html_body):
    load_dotenv()
    sender = os.getenv("EMAIL_SENDER")
    password = os.getenv("EMAIL_PASSWORD")
    receiver = os.getenv("EMAIL_RECEIVER")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = receiver

    part = MIMEText(html_body, "html")
    msg.attach(part)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, password)
        server.send_message(msg)
        print("📬 Email sent!")

# --- Main ---
def main():
    print("Scraping current discounted products...")
    all_current_data = []
    grouped = {}
    previous_data = load_previous_data()
    prev_links = {item["link"] for item in previous_data}

    for brand, gender, size in COMBOS:
        combo_key = f"{brand}|{gender}|{size}"
        current = scrape_products(brand, gender, size)
        all_current_data.extend(current)

        new = [item for item in current if item["link"] not in prev_links]
        existing = [item for item in current if item["link"] in prev_links]

        grouped[combo_key] = {"new": new, "existing": existing}

        # Print to console
        if new:
            print(f"\n🆕 {combo_key} New Items:")
            for item in new:
                print(f"- {item['name']} (${item['original']} → ${item['sale']})")
        if existing:
            print(f"\n📦 {combo_key} Existing Items:")
            for item in existing:
                print(f"- {item['name']} (${item['original']} → ${item['sale']})")

    any_new = any(len(data["new"]) > 0 for data in grouped.values())
    if any_new:
        html = generate_html_email(grouped)
        send_email("🏞️ New Deals Across Brands", html)
    else:
        print("\nNo new discounted items across all combos.")

    save_data(all_current_data)

if __name__ == "__main__":
    main()