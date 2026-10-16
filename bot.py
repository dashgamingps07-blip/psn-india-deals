
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE = "https://psprices.com"
SOURCE = BASE + "/region-in/discounts/"
STATE = Path("seen.json")

WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
MIN_DISCOUNT = int(os.getenv("MIN_DISCOUNT", "25"))
MAX_POSTS = int(os.getenv("MAX_POSTS", "12"))
PAGES = max(1, min(5, int(os.getenv("PAGES", "2"))))
TEST_POST = os.getenv("TEST_POST", "false").lower() == "true"

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0",
    "Accept-Language": "en-IN,en;q=0.9"
})


def money(value):
    if value is None:
        return "N/A"
    return "₹{:,.2f}".format(value).removesuffix(".00")


def valid_image(url, base=BASE):
    if not url or url.startswith("data:"):
        return None

    url = urljoin(base, url)

    if url.startswith("https://"):
        return url

    return None


def extract_image(element, base=BASE):
    for img in element.select("img"):
        for attribute in (
            "data-src",
            "data-original",
            "data-lazy-src",
            "src"
        ):
            result = valid_image(img.get(attribute), base)
            if result:
                return result

        srcset = img.get("srcset") or img.get("data-srcset")

        if srcset:
            for item in reversed(srcset.split(",")):
                source = item.strip().split(" ")[0]
                result = valid_image(source, base)
                if result:
                    return result

    return None


def get_game_image(deal):
    if deal.get("image"):
        return deal["image"]

    try:
        response = SESSION.get(deal["url"], timeout=20)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        for selector in (
            'meta[property="og:image"]',
            'meta[name="twitter:image"]',
            'meta[property="twitter:image"]'
        ):
            tag = soup.select_one(selector)

            if tag:
                image = valid_image(
                    tag.get("content"),
                    deal["url"]
                )

                if image:
                    return image

        image = extract_image(soup, deal["url"])

        if image:
            return image

    except requests.RequestException as error:
        print(f"Image fetch failed: {error}")

    return None


def fetch(page):
    response = SESSION.get(
        SOURCE,
        params={
            "display": "table",
            "ordering": "desc",
            "platform": "PS5,PS4",
            "sort": "date",
            "page": page
        },
        timeout=25
    )

    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    deals = []

    for row in soup.select("tr"):
        cells = row.find_all("td")

        if len(cells) < 3:
            continue

        anchor = next(
            (
                a for a in cells[2].find_all("a", href=True)
                if "/game/" in a["href"]
                or "/games/" in a["href"]
            ),
            None
        )

        if not anchor:
            continue

        name = anchor.get_text(" ", strip=True)

        if not name:
            continue

        link = urljoin(BASE, anchor["href"])

        discount_match = re.search(
            r"[−\-]\s*(\d{1,3})\s*%",
            cells[0].get_text(" ", strip=True)
        )

        prices = re.findall(
            r"₹\s*([\d,]+(?:\.\d+)?)",
            cells[1].get_text(" ", strip=True)
        )

        if not discount_match or not prices:
            continue

        discount = int(discount_match.group(1))

        if discount < MIN_DISCOUNT or discount > 100:
            continue

        current = float(prices[0].replace(",", ""))

        original = (
            float(prices[1].replace(",", ""))
            if len(prices) > 1
            else None
        )

        if original is not None:
            if original < current or original <= 0:
                original = None

        image = extract_image(row, BASE)

        deals.append({
            "name": name[:160],
            "url": link,
            "discount": discount,
            "price": current,
            "original": original,
            "image": image
        })

    print(f"Page {page}: {len(deals)} eligible deals")
    return deals


def post(deal):
    image = get_game_image(deal)

    discount = deal["discount"]
    current_price = money(deal["price"])
    original = deal.get("original")

    description = (
        f"## 🔥 {discount}% OFF\n"
        f"## 💰 {current_price}\n"
    )

    if original is not None:
        description += f"~~{money(original)}~~\n"

        savings = max(0, original - deal["price"])

        if savings > 0:
            description += f"💸 Save {money(savings)}\n"

    description += (
        f"\n[🛒 VIEW GAME DEAL]({deal['url']})"
    )

    embed = {
        "author": {
            "name": "🎮 PLAYSTATION STORE | INDIA"
        },
        "title": deal["name"],
        "url": deal["url"],
        "description": description,
        "color": 0x0070D1,
        "fields": [
            {
                "name": "🇮🇳 Region",
                "value": "India • INR",
                "inline": True
            }
        ],
        "footer": {
            "text": (
                "PSN India Deals • Source: PSPrices"
                " • Verify price on PlayStation Store"
            )
        }
    }

    # Large image instead of small thumbnail
    if image:
        embed["image"] = {
            "url": image
        }

    payload = {
        "username": "PSN India Deals",
        "embeds": [embed],
        "allowed_mentions": {
            "parse": []
        }
    }

    response = SESSION.post(
        WEBHOOK,
        json=payload,
        timeout=25
    )

    if response.status_code == 429:
        retry = response.json().get("retry_after", 2)
        time.sleep(min(10, float(retry)))

        response = SESSION.post(
            WEBHOOK,
            json=payload,
            timeout=25
        )

    response.raise_for_status()

    print(
        f"Posted: {deal['name']} | "
        f"{discount}% OFF | "
        f"image={bool(image)}"
    )


def main():
    if not WEBHOOK.startswith(
        "https://discord.com/api/webhooks/"
    ):
        raise RuntimeError(
            "Set DISCORD_WEBHOOK_URL in GitHub Actions secrets."
        )

    found = {}

    for page in range(1, PAGES + 1):
        for deal in fetch(page):
            found[deal["url"]] = deal

        time.sleep(1)

    if not found:
        raise RuntimeError(
            "No deals parsed. Check PSPrices source/layout."
        )

    previous = (
        json.loads(STATE.read_text(encoding="utf-8"))
        if STATE.exists()
        else {}
    )

    observed = {
        url: f"{deal['price']}|{deal['discount']}"
        for url, deal in found.items()
    }

    # Manual test: post one deal without changing history
    if TEST_POST:
        deal = next(iter(found.values()))
        post(deal)

        print(
            "TEST_POST delivered; "
            "saved deal history unchanged."
        )
        return

    # First run: save baseline, no mass posting
    if not previous:
        STATE.write_text(
            json.dumps(
                observed,
                ensure_ascii=False,
                indent=2
            ) + "\n",
            encoding="utf-8"
        )

        print(
            f"Baseline initialized: {len(observed)} deals"
        )
        return

    updates = [
        deal
        for url, deal in found.items()
        if previous.get(url) != observed[url]
    ]

    sent = 0

    for deal in updates[:MAX_POSTS]:
        post(deal)

        previous[deal["url"]] = observed[deal["url"]]
        sent += 1

        time.sleep(1)

    unsent = {
        deal["url"]
        for deal in updates[MAX_POSTS:]
    }

    for url, value in observed.items():
        if url not in previous and url not in unsent:
            previous[url] = value

    STATE.write_text(
        json.dumps(
            dict(list(previous.items())[-12000:]),
            ensure_ascii=False,
            indent=2
        ) + "\n",
        encoding="utf-8"
    )

    print(
        f"Found {len(found)} deals; "
        f"posted {sent} new/changed alerts."
    )


if __name__ == "__main__":
    main()
