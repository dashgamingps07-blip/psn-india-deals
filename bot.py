
"""PSN India discount alerts to Discord using PSPrices."""

import random
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


# ---------------- CONFIGURATION ----------------

BASE = "https://psprices.com"
SOURCE = BASE + "/region-in/discounts/"
STATE = Path("seen.json")

WEBHOOK = os.getenv("DISCORD_WEBHOOK_URL", "").strip()

MIN_DISCOUNT = int(os.getenv("MIN_DISCOUNT", "25"))
MAX_POSTS = int(os.getenv("MAX_POSTS", "1"))
PAGES = max(1, min(5, int(os.getenv("PAGES", "2"))))

TEST_POST = os.getenv(
    "TEST_POST", "false"
).lower() == "true"

SESSION = requests.Session()

SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (compatible; "
        "PSNIndiaDeals/1.1; personal deal alerts)"
    ),
    "Accept-Language": "en-IN,en;q=0.9",
})

IMAGE_CACHE = {}


# ---------------- IMAGE FUNCTIONS ----------------

def absolute_image(value, page_url=BASE):
    if not value:
        return None

    value = value.strip()

    if value.startswith("data:"):
        return None

    url = urljoin(page_url, value)
    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https"):
        return None

    if not parsed.netloc:
        return None

    return url


def image_from_row(row, page_url):
    for img in row.select("img"):

        candidates = [
            img.get("data-src"),
            img.get("data-original"),
            img.get("data-lazy-src"),
            img.get("data-srcset"),
            img.get("srcset"),
            img.get("src"),
        ]

        for candidate in candidates:

            if not candidate:
                continue

            if "," in candidate or re.search(
                r"\s\d+(?:\.\d+)?[wx](?:,|$)",
                candidate
            ):
                candidate = (
                    candidate.split(",")[0]
                    .strip()
                    .split()[0]
                )

            image = absolute_image(
                candidate,
                page_url
            )

            if image and not any(
                word in image.lower()
                for word in (
                    "placeholder",
                    "spacer.gif",
                    "blank.gif"
                )
            ):
                return image

    return None


def image_from_game_page(url):

    if url in IMAGE_CACHE:
        return IMAGE_CACHE[url]

    image = None

    try:
        response = SESSION.get(
            url,
            timeout=20
        )

        response.raise_for_status()

        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )

        for selector, attribute in (
            ('meta[property="og:image"]', "content"),
            ('meta[name="twitter:image"]', "content"),
            ('meta[property="twitter:image"]', "content"),
        ):

            tag = soup.select_one(selector)

            if tag:
                image = absolute_image(
                    tag.get(attribute),
                    response.url
                )

                if image:
                    break

    except requests.RequestException as error:
        print(
            f"Image preview unavailable "
            f"for {url}: {error}"
        )

    IMAGE_CACHE[url] = image

    return image


# ---------------- FETCH DEALS ----------------

def fetch(page):

    response = SESSION.get(
        SOURCE,
        params={
            "display": "table",
            "ordering": "desc",
            "platform": "PS5,PS4",
            "sort": "date",
            "page": page,
        },
        timeout=25
    )

    response.raise_for_status()

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    deals = []

    for row in soup.select("tr"):

        cells = row.find_all("td")

        if len(cells) < 3:
            continue

        anchor = next(
            (
                a for a in cells[2].find_all(
                    "a", href=True
                )
                if "/game/" in a["href"]
                or "/games/" in a["href"]
            ),
            None
        )

        if not anchor:
            continue

        name = anchor.get_text(
            " ",
            strip=True
        )

        if not name:
            continue

        link = urljoin(
            BASE,
            anchor["href"]
        )

        disc_match = re.search(
            r"[−\-]\s*(\d{1,3})\s*%",
            cells[0].get_text(" ", strip=True)
        )

        price_matches = re.findall(
            r"₹\s*([\d,]+(?:\.\d+)?)",
            cells[1].get_text(" ", strip=True)
        )

        if not disc_match or not price_matches:
            continue

        discount = int(
            disc_match.group(1)
        )

        if discount < MIN_DISCOUNT:
            continue

        if discount > 100:
            continue

        current = float(
            price_matches[0].replace(",", "")
        )

        original = (
            float(
                price_matches[1].replace(",", "")
            )
            if len(price_matches) > 1
            else None
        )

        if original is not None:
            if original <= current or original <= 0:
                original = None

        deals.append({
            "name": name[:160],
            "url": link,
            "discount": discount,
            "price": current,
            "original": original,
            "image": image_from_row(
                row,
                response.url
            ),
        })

    return deals


# ---------------- PRICE FORMAT ----------------

def money(value):
    return "₹{:,.2f}".format(
        value
    ).removesuffix(".00")


# ---------------- DISCORD POST ----------------

def post(deal):

    cover = (
        deal.get("image")
        or image_from_game_page(
            deal["url"]
        )
    )

    discount = deal["discount"]

    current = money(
        deal["price"]
    )

    old = (
        money(deal["original"])
        if deal["original"] is not None
        else None
    )

    description = (
        f"### 🔥 {discount}% OFF\n"
        f"## {current}\n"
        + (
            f"~~{old}~~  "
            f"**Save "
            f"{money(deal['original'] - deal['price'])}"
            f"**\n"
            if old else ""
        )
        + (
            f"\n🛒 **[VIEW GAME DEAL]"
            f"({deal['url']})**"
        )
    )

    embed = {
        "author": {
            "name": "🎮 PLAYSTATION STORE • INDIA"
        },
        "title": deal["name"],
        "url": deal["url"],
        "description": description,
        "color": 0x0868D7,
        "fields": [
            {
                "name": "🏷️ Discount",
                "value": f"**{discount}% OFF**",
                "inline": True
            },
            {
                "name": "🇮🇳 Region",
                "value": "India • INR",
                "inline": True
            }
        ],
        "footer": {
            "text": (
                "PlayStation Deals • PSPrices"
                " • Verify final price before purchase"
            )
        }
    }

    # Small cover thumbnail
    if cover:
        embed["thumbnail"] = {
            "url": cover
        }
    else:
        print(
            f"No cover URL found for: "
            f"{deal['name']}"
        )

    payload = {
        "username": "PlayStation Deals",
        "embeds": [embed],
        "allowed_mentions": {
            "parse": []
        }
    }

    for attempt in range(3):

        response = SESSION.post(
            WEBHOOK,
            json=payload,
            timeout=25
        )

        if response.status_code != 429:

            response.raise_for_status()

            print(
                f"Posted: {deal['name']} "
                f"| image={bool(cover)}"
            )

            return

        try:
            delay = float(
                response.json().get(
                    "retry_after", 2
                )
            )
        except (ValueError, TypeError):
            delay = 2

        time.sleep(
            max(1, min(30, delay))
        )

    response.raise_for_status()


# ---------------- MAIN FUNCTION ----------------

def main():

    if not WEBHOOK.startswith((
        "https://discord.com/api/webhooks/",
        "https://discordapp.com/api/webhooks/"
    )):
        raise RuntimeError(
            "Set DISCORD_WEBHOOK_URL "
            "in GitHub Actions secrets."
        )

    found = {}

    for page in range(1, PAGES + 1):

        page_deals = fetch(page)

        print(
            f"Page {page}: parsed "
            f"{len(page_deals)} qualifying offers"
        )

        for deal in page_deals:
            found[deal["url"]] = deal

        time.sleep(1)

    if not found:
        raise RuntimeError(
            "No deals parsed: PSPrices HTML, "
            "access or filters may have changed."
        )

    observed = {
        url: (
            f"{deal['price']}|"
            f"{deal['discount']}"
        )
        for url, deal in found.items()
    }

    # TEST MODE: one random deal
    if TEST_POST:

        deal = random.choice(
            list(found.values())
        )

        post(deal)

        print(
            f"Random test deal posted: "
            f"{deal['name']}"
        )

        print(
            "History unchanged."
        )

        return

    # NORMAL MODE
    previous = (
        json.loads(
            STATE.read_text(
                encoding="utf-8"
            )
        )
        if STATE.exists()
        else {}
    )

    # First normal run: save existing deals
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
            f"Initialized baseline of "
            f"{len(observed)} deals; "
            f"no alerts on first run."
        )

        return

    # Find new or changed deals
    updates = [
        deal
        for url, deal in found.items()
        if previous.get(url) != observed[url]
    ]

    selected = updates[:MAX_POSTS]

    for deal in selected:

        post(deal)

        previous[deal["url"]] = (
            observed[deal["url"]]
        )

        time.sleep(1)

    # Do not mark unsent deals as delivered
    unsent_urls = {
        deal["url"]
        for deal in updates[MAX_POSTS:]
    }

    for url, value in observed.items():

        if (
            url not in previous
            and url not in unsent_urls
        ):
            previous[url] = value

    STATE.write_text(
        json.dumps(
            dict(
                list(previous.items())[-12000:]
            ),
            ensure_ascii=False,
            indent=2
        ) + "\n",
        encoding="utf-8"
    )

    print(
        f"Found {len(found)} qualifying deals; "
        f"sent {len(selected)} new/changed alerts."
    )


if __name__ == "__main__":
    main()
