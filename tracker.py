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

# Define base directory and data file (always saved alongside this script)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, "data.json")

URL = "https://www.wildearth.com.au/brand/Arcteryx#/filter:is_sale:1/filter:gender:Men/filter:child_sizes:S"
DISCOUNT_THRESHOLD = 25  # percent

# --- Setup headless Chrome ---
def get_driver():
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    return webdriver.Chrome(options=options)

# --- Extract product data including images ---
def scrape_products():
    driver = get_driver()
    driver.get(URL)
    time.sleep(5)  # Allow JavaScript to load products
    soup = BeautifulSoup(driver.page_source, "html.parser")
    driver.quit()

    results = []
    # Each product is wrapped in an <article> tag with classes "ss__result ss__result--item"
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

            # Grab the product image from the <figure> tag
            image_tag = container.select_one("figure.ss__result__image img")
            image_url = image_tag["src"] if image_tag and image_tag.has_attr("src") else ""

            if discount >= DISCOUNT_THRESHOLD:
                results.append({
                    "name": name,
                    "link": link,
                    "original": original,
                    "sale": sale,
                    "discount": discount,
                    "image": image_url
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

# --- Generate HTML email body for new and existing items ---
def generate_html_email(new_items, existing_items):
    html = "<h2>🆕 New Discounted Arcteryx Products</h2>"
    for item in new_items:
        html += f"""
        <div style="margin-bottom:20px; padding:10px; border-bottom:1px solid #ccc;">
            <h3>{item['name']}</h3>
            <img src="{item['image']}" alt="{item['name']}" width="200"><br>
            <strong>Original:</strong> ${item['original']:.2f}<br>
            <strong>Now:</strong> ${item['sale']:.2f} ({item['discount']}% off)<br>
            <a href="{item['link']}">View Product</a>
        </div>
        """
    if existing_items:
        html += "<h2>📦 Existing Discounted Arcteryx Products</h2>"
        for item in existing_items:
            html += f"""
            <div style="margin-bottom:20px; padding:10px; border-bottom:1px solid #ccc;">
                <h3>{item['name']}</h3>
                <img src="{item['image']}" alt="{item['name']}" width="200"><br>
                <strong>Original:</strong> ${item['original']:.2f}<br>
                <strong>Now:</strong> ${item['sale']:.2f} ({item['discount']}% off)<br>
                <a href="{item['link']}">View Product</a>
            </div>
            """
    return html

# --- Send email using Gmail ---
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
    current_data = scrape_products()
    previous_data = load_previous_data()

    current_links = {item["link"] for item in current_data}
    previous_links = {item["link"] for item in previous_data}

    new_items = [item for item in current_data if item["link"] not in previous_links]
    existing_items = [item for item in current_data if item["link"] in previous_links]

    # Display new items on console
    if new_items:
        print(f"\n🆕 New discounted items found:")
        for idx, item in enumerate(new_items, 1):
            print(f"{idx}. {item['name']}")
            print(f"   Original: ${item['original']:.2f} → Sale: ${item['sale']:.2f} ({item['discount']}% off)")
            print(f"   Link: {item['link']}\n")
    else:
        print("\nNo new discounted items found.")

    # Display existing items on console
    if existing_items:
        print(f"\n📦 Existing discounted items:")
        for idx, item in enumerate(existing_items, 1):
            print(f"{idx}. {item['name']}")
            print(f"   Original: ${item['original']:.2f} → Sale: ${item['sale']:.2f} ({item['discount']}% off)")
            print(f"   Link: {item['link']}\n")

    # Only send email if new items are found; include both new and existing in the email
    if new_items:
        html = generate_html_email(new_items, existing_items)
        send_email("🏞️ New Arcteryx Deals", html)

    # Save only current discounted products (pruning removed items)
    save_data(current_data)

if __name__ == "__main__":
    main()