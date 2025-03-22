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
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, "data.json")

FILTER_COMBOS = [
    {"brand": ["Arc'teryx"], "gender": ["Men"], "size": ["S", "28", "US8.5", "US9"], "threshold": 29},
    {"brand": ["Arc'teryx"], "gender": ["Unisex"], "size": [], "threshold": 29},
    {"brand": ["Patagonia"], "gender": ["Men"], "size": ["S", "28"], "threshold": 33},
    {"brand": ["Patagonia"], "gender": ["Unisex"], "size": [], "threshold": 33},
    {"brand": ["Mammut"], "gender": ["Men"], "size": ["S", "28"], "threshold": 39},
    {"brand": ["Icebreaker"], "gender": ["Men"], "size": ["S"], "threshold": 39},
    {"brand": ["Icebreaker"], "gender": ["Unisex"], "size": [], "threshold": 39},
    {"brand": ["Salomon"], "gender": ["Men"], "size": ["US8.5", "US9"], "threshold": 33},
    {"brand": ["The$2520North$2520Face"], "gender": ["Men"], "size": ["S", "28"], "threshold": 39},
    {"brand": ["The$2520North$2520Face"], "gender": ["Unisex"], "size": [], "threshold": 39}
]

def get_driver():
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    return webdriver.Chrome(options=options)

def build_url(filters):
    url = "https://www.wildearth.com.au/view/sale#/filter:is_sale:1"
    for f_type, values in filters.items():
        if f_type == "threshold":
            continue
        filter_name = "child_sizes" if f_type == "size" else f_type
        for val in values:
            url += f"/filter:{filter_name}:{val}"
    return url

def scrape_products(combo):
    url = build_url(combo)
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
                    "brand": combo["brand"][0],
                })
        except:
            continue
    return results

def load_previous_data():
    return json.load(open(DATA_FILE)) if os.path.exists(DATA_FILE) else []

def save_data(data):
    json.dump(data, open(DATA_FILE, "w"), indent=2)

def decode_brand_name(brand):
    return brand.replace('$2520', ' ')

def generate_email(grouped):
    html = "<h1>🎯 DealTracker Update</h1>"
    for brand, items in grouped.items():
        display_brand = decode_brand_name(brand)
        html += f"<h2>{display_brand}</h2><table><tr>"
        for i, item in enumerate(items):
            html += f"""
            <td style='padding:10px;text-align:center;'>
            <img src='{item['image']}' width='100'><br>
            <b>{item['name']}</b><br>
            ${item['original']:.2f}→<b>${item['sale']:.2f}</b> ({item['discount']}% off)<br>
            <a href='{item['link']}'>View</a></td>"""
            if (i+1)%3==0:
                html+="</tr><tr>"
        html+="</tr></table>"
    return html

def send_email(subject,html_body):
    load_dotenv()
    sender=os.getenv("EMAIL_SENDER")
    receiver=os.getenv("EMAIL_RECEIVER")
    password=os.getenv("EMAIL_PASSWORD")

    msg=MIMEMultipart("alternative")
    msg["Subject"]=subject
    msg["From"]=f"🏷️DealTracker<{sender}>"
    msg["To"]=receiver
    msg.attach(MIMEText(html_body,"html"))

    with smtplib.SMTP_SSL("smtp.gmail.com",465) as server:
        server.login(sender,password)
        server.send_message(msg)

def main():
    print("🔍 Loading previous deal data...")
    previous_data = load_previous_data()
    prev_links = {item["link"] for item in previous_data}
    print(f"✅ Loaded {len(prev_links)} previous items.")

    all_current_data = []
    new_deals_grouped = defaultdict(list)

    print(f"🚀 Starting scraping for {len(FILTER_COMBOS)} filter combos...")

    for idx, combo in enumerate(FILTER_COMBOS, 1):
        print(f"\n[{idx}/{len(FILTER_COMBOS)}] 🛒 Processing combo: {combo}")
        current_items = scrape_products(combo)
        print(f"   📦 Found {len(current_items)} total items for this combo.")

        for item in current_items:
            all_current_data.append(item)
            if item["link"] not in prev_links:
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

    print("💾 Saving current deal data...")
    save_data(all_current_data)
    print("✅ Data saved successfully.")

if __name__=="__main__":
    main()