
"""PSN India AAA game deals -> Discord."""

import os
import json
import random
import re
import time

from pathlib import Path
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


# CONFIGURATION

BASE = "https://psprices.com"
SOURCE = BASE + "/region-in/discounts/"
STATE = Path("seen.json")

COOLDOWN_DAYS = 7

WEBHOOK = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
MIN_DISCOUNT = int(os.getenv("MIN_DISCOUNT", "30"))
MAX_POSTS = max(0, int(os.getenv("MAX_POSTS", "1")))
PAGES = max(1, min(5, int(os.getenv("PAGES", "3"))))

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (compatible; "
        "PSNIndiaDeals/1.1; personal deal alerts)"
    ),
    "Accept-Language": "en-IN,en;q=0.9"
})


# AAA / POPULAR GAME FILTER

AAA_NAMES = (
    "god of war",
    "spider-man",
    "spiderman",
    "the last of us",
    "uncharted",
    "ghost of tsushima",
    "ghost of yotei",
    "horizon",
    "gran turismo",
    "death stranding",
    "days gone",
    "bloodborne",
    "demon's souls",
    "demons souls",
    "returnal",
    "stellar blade",
    "astro bot",
    "ratchet",
    "elden ring",
    "dark souls",
    "sekiro",
    "armored core",
    "cyberpunk",
    "the witcher",
    "red dead redemption",
    "grand theft auto",
    "resident evil",
    "silent hill",
    "final fantasy",
    "assassin's creed",
    "assassins creed",
    "far cry",
    "watch dogs",
    "tomb raider",
    "hitman",
    "metal gear",
    "devil may cry",
    "monster hunter",
    "dragon's dogma",
    "dragons dogma",
    "hogwarts legacy",
    "star wars",
    "batman",
    "mortal kombat",
    "tekken",
    "street fighter",
    "call of duty",
    "battlefield",
    "doom",
    "elder scrolls",
    "fallout",
    "kingdom come",
    "mafia",
    "dying light",
    "dead space",
    "alan wake",
    "control",
    "borderlands",
    "bioshock",
    "persona",
    "metaphor refantazio",
    "yakuza",
    "like a dragon",
    "nioh",
    "lies of p",
    "black myth",
    "wolverine",
    "indiana jones",
    "avatar: frontiers",
    "prince of persia",
    "dragon age",
    "mass effect",
    "middle-earth",
    "need for speed",
    "ea sports fc",
    "wwe 2k",
    "nba 2k",
    "f1 20",
    "it takes two",
    "a plague tale",
    "jedi survivor",
    "jedi fallen order",
    "forza horizon"
)

EXCLUDED = (
    "soundtrack",
    "season pass",
    "battle pass",
    "character pass",
    "currency pack",
    "coin pack",
    "credit pack",
    "virtual currency",
    "avatar pack",
    "costume pack",
    "skin pack",
    "upgrade pack",
    "expansion pass",
    "artbook",
    "art book",
    "dlc",
    "add-on",
    "add on",
    "digital deluxe upgrade",
    "bonus content",
    "points pack",
    "starter pack",
    "weapon pack",
    "cosmetic pack",
    "sound track",
    "virtual coin"
)


def normalized(name):
    return re.sub(
        r"[^a-z0-9]+",
        " ",
        name.casefold().replace("’", "'")
    ).strip()


def is_aaa(name):
    text = " " + normalized(name) + " "

    blocked = any(
        " " + normalized(word) + " " in text
        for word in EXCLUDED
    )

    allowed = any(
        " " + normalized(word) + " " in text
        for word in AAA_NAMES
    )

    return allowed and not blocked


def game_key(name):
    text = normalized(name)

    # Match Roman numerals and numeric versions.
    # Different sequels remain separate games.
    roman = {
        "ii": "2",
        "iii": "3",
        "iv": "4",
        "v": "5",
        "vi": "6",
        "vii": "7",
        "viii": "8",
        "ix": "9",
        "x": "10"
    }

    text = " ".join(
        roman.get(word, word)
        for word in text.split()
    )

    # Group recognized editions of the same game.
    text = re.sub(
        r"\b(standard edition|digital deluxe edition|"
        r"deluxe edition|ultimate edition|gold edition|"
        r"complete edition|champion edition|arcade edition|"
        r"definitive edition|legendary edition|"
        r"premium edition|special edition|"
        r"game of the year edition|goty edition|"
        r"digital edition|remastered|ps4|ps5)\b",
        " ",
        text
    )

    return re.sub(r"\s+", " ", text).strip()


# IMAGE FUNCTIONS

def image_url(raw, base):
    if not raw or raw.startswith("data:"):
        return None

    result = urljoin(base, raw.strip())
    parsed = urlparse(result)

    if parsed.scheme in ("https", "http") and parsed.netloc:
        return result

    return None


def row_image(row, base):
    for img in row.select("img"):
        for key in (
            "data-src",
            "data-original",
            "data-lazy-src",
            "src",
            "data-srcset",
            "srcset"
        ):
            raw = img.get(key)

            if not raw:
                continue

            raw = raw.split(",")[0].strip().split()[0]
            result = image_url(raw, base)

            if result and not any(
                word in result.lower()
                for word in (
                    "placeholder",
                    "spacer.gif",
                    "blank.gif"
                )
            ):
                return result

    return None


def detail_image(url):
    try:
        response = SESSION.get(url, timeout=20)
        response.raise_for_status()

        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )

        for selector in (
            'meta[property="og:image"]',
            'meta[name="twitter:image"]'
        ):
            element = soup.select_one(selector)

            if element:
                result = image_url(
                    element.get("content"),
                    response.url
                )

                if result:
                    return result

    except requests.RequestException as error:
        print(f"Cover unavailable: {error}")

    return None


# FETCH PSN INDIA DEALS

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

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    parsed_count = 0
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

        name = anchor.get_text(" ", strip=True)

        discount_match = re.search(
            r"[−\-]\s*(\d{1,3})\s*%",
            cells[0].get_text(" ", strip=True)
        )

        prices = re.findall(
            r"₹\s*([\d,]+(?:\.\d+)?)",
            cells[1].get_text(" ", strip=True)
        )

        if not name or not discount_match or not prices:
            continue

        parsed_count += 1

        discount = int(discount_match.group(1))

        if not MIN_DISCOUNT <= discount <= 100:
            continue

        if not is_aaa(name):
            continue

        current = float(
            prices[0].replace(",", "")
        )

        original = (
            float(prices[1].replace(",", ""))
            if len(prices) > 1
            else None
        )

        if original is not None and original <= current:
            original = None

        deals.append({
            "name": name[:160],
            "url": urljoin(BASE, anchor["href"]),
            "discount": discount,
            "price": current,
            "original": original,
            "image": row_image(row, response.url)
        })

    print(
        f"Page {page}: "
        f"{parsed_count} parsed, "
        f"{len(deals)} qualifying AAA deals"
    )

    return parsed_count, deals


# PRICE FORMAT

def money(amount):
    return "₹{:,.2f}".format(
        amount
    ).removesuffix(".00")


# DISCORD MESSAGE

def post(deal):
    cover = (
        deal.get("image")
        or detail_image(deal["url"])
    )

    current = money(deal["price"])
    old = deal.get("original")

    description = (
        f"### 🔥 {deal['discount']}% OFF\n"
        f"## {current}\n"
    )

    if old is not None:
        description += (
            f"~~{money(old)}~~  "
            f"**Save {money(old - deal['price'])}**\n"
        )

    description += (
        f"\n🛒 **[VIEW GAME DEAL]"
        f"({deal['url']})**"
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
                "value": f"**{deal['discount']}% OFF**",
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

    # Original small game thumbnail
    if cover:
        embed["thumbnail"] = {
            "url": cover
        }

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
                response.json().get("retry_after", 2)
            )
        except (TypeError, ValueError):
            delay = 2

        time.sleep(max(1, min(30, delay)))

    response.raise_for_status()


# NORMAL PRODUCTION MODE

def main():
    if not WEBHOOK.startswith((
        "https://discord.com/api/webhooks/",
        "https://discordapp.com/api/webhooks/"
    )):
        raise RuntimeError(
            "Missing Discord webhook secret"
        )

    found = {}
    parsed_total = 0

    for page in range(1, PAGES + 1):
        count, deals = fetch(page)
        parsed_total += count

        for deal in deals:
            found[deal["url"]] = deal

        time.sleep(1)

    if parsed_total == 0:
        raise RuntimeError(
            "PSPrices page loaded but no deals parsed. "
            "Parser or access may have changed."
        )

    if not found:
        print(
            "No qualifying AAA deals in scanned pages. "
            "No post."
        )
        return

    # Load persisted history
    history = (
        json.loads(
            STATE.read_text(encoding="utf-8")
        )
        if STATE.exists()
        else {}
    )

    if not isinstance(history, dict):
        raise RuntimeError(
            "Invalid seen.json structure"
        )

    # 7-DAY COOLDOWN SYSTEM

    posted_times = history.get("__posted_times__", {})

    if not isinstance(posted_times, dict):
        posted_times = {}

    now = datetime.now(timezone.utc)

    # Migrate old posted games to timed history.
    # Previous exact posting timestamps are unknown.
    if "__posted_times__" not in history:
        for old_key in history.get("__posted_games__", []):
            key = game_key(old_key)

            if key:
                posted_times[key] = now.isoformat()

        history["__posted_times__"] = posted_times

        STATE.write_text(
            json.dumps(
                history,
                ensure_ascii=False,
                indent=2
            ) + "\n",
            encoding="utf-8"
        )

    # Group editions and filter games on cooldown
    available_by_game = {}

    for deal in found.values():
        key = game_key(deal["name"])

        if not key or key in available_by_game:
            continue

        last_posted = posted_times.get(key)

        if last_posted:
            try:
                posted_at = datetime.fromisoformat(
                    last_posted
                )

                if posted_at.tzinfo is None:
                    posted_at = posted_at.replace(
                        tzinfo=timezone.utc
                    )

                if now - posted_at < timedelta(
                    days=COOLDOWN_DAYS
                ):
                    continue

            except (TypeError, ValueError):
                # Invalid timestamp should not block forever
                pass

        available_by_game[key] = deal

    available = list(available_by_game.values())

    print(
        f"Eligible AAA deals: {len(found)} | "
        f"Outside {COOLDOWN_DAYS}-day cooldown: "
        f"{len(available)}"
    )

    if not available:
        print(
            "No AAA games currently outside cooldown."
        )
        return

    # Random eligible game selection
    selected = random.sample(
        available,
        min(MAX_POSTS, len(available))
    )

    for deal in selected:
        post(deal)

        # Only save after successful Discord delivery
        posted_times[
            game_key(deal["name"])
        ] = datetime.now(timezone.utc).isoformat()

        history["__posted_times__"] = posted_times

        STATE.write_text(
            json.dumps(
                history,
                ensure_ascii=False,
                indent=2
            ) + "\n",
            encoding="utf-8"
        )

        time.sleep(1)

    print(
        f"Posted {len(selected)} AAA deal(s), "
        f"each with a {COOLDOWN_DAYS}-day cooldown"
    )


if __name__ == "__main__":
    main()
