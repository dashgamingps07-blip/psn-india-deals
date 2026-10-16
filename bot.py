"""PSN India discount alerts → Discord. Uses public PSPrices HTML (unofficial)."""
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

BASE = 'https://psprices.com'
SOURCE = BASE + '/region-in/discounts/'
STATE = Path('seen.json')
WEBHOOK = os.getenv('DISCORD_WEBHOOK_URL', '').strip()
MIN_DISCOUNT = int(os.getenv('MIN_DISCOUNT', '50'))
MAX_POSTS = int(os.getenv('MAX_POSTS', '12'))
PAGES = max(1, min(5, int(os.getenv('PAGES', '2'))))
TEST_POST = os.getenv('TEST_POST', 'false').lower() == 'true'

SESSION = requests.Session()
SESSION.headers.update({
    'User-Agent': 'Mozilla/5.0 (compatible; PSNIndiaDeals/1.1; personal deal alerts)',
    'Accept-Language': 'en-IN,en;q=0.9',
})
IMAGE_CACHE = {}


def absolute_image(value, page_url=BASE):
    if not value:
        return None
    value = value.strip()
    if value.startswith('data:'):
        return None
    url = urljoin(page_url, value)
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https') or not parsed.netloc:
        return None
    # Discord needs a publicly fetchable image URL.
    return url


def image_from_row(row, page_url):
    # Image is often lazy loaded. Prefer srcset/data-src over placeholder src.
    for img in row.select('img'):
        candidates = [
            img.get('data-src'), img.get('data-original'),
            img.get('data-lazy-src'), img.get('data-srcset'),
            img.get('srcset'), img.get('src'),
        ]
        for candidate in candidates:
            if not candidate:
                continue
            # srcset consists of "url 1x, url 2x" entries.
            if ',' in candidate or re.search(r'\s\d+(?:\.\d+)?[wx](?:,|$)', candidate):
                candidate = candidate.split(',')[0].strip().split()[0]
            image = absolute_image(candidate, page_url)
            if image and not any(word in image.lower() for word in ('placeholder', 'spacer.gif', 'blank.gif')):
                return image
    return None


def image_from_game_page(url):
    if url in IMAGE_CACHE:
        return IMAGE_CACHE[url]
    image = None
    try:
        response = SESSION.get(url, timeout=20)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        for selector, attribute in (
            ('meta[property="og:image"]', 'content'),
            ('meta[name="twitter:image"]', 'content'),
            ('meta[property="twitter:image"]', 'content'),
        ):
            tag = soup.select_one(selector)
            if tag:
                image = absolute_image(tag.get(attribute), response.url)
                if image:
                    break
    except requests.RequestException as error:
        print(f'Image preview unavailable for {url}: {error}')
    IMAGE_CACHE[url] = image
    return image


def fetch(page):
    response = SESSION.get(SOURCE, params={
        'display': 'table', 'ordering': 'desc', 'platform': 'PS5,PS4',
        'sort': 'date', 'page': page,
    }, timeout=25)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, 'html.parser')
    deals = []
    for row in soup.select('tr'):
        cells = row.find_all('td')
        if len(cells) < 3:
            continue
        anchor = next((a for a in cells[2].find_all('a', href=True)
                       if '/game/' in a['href'] or '/games/' in a['href']), None)
        if not anchor:
            continue
        name = anchor.get_text(' ', strip=True)
        if not name:
            continue
        link = urljoin(BASE, anchor['href'])
        disc_match = re.search(r'[−\-]\s*(\d{1,3})\s*%', cells[0].get_text(' ', strip=True))
        price_matches = re.findall(r'₹\s*([\d,]+(?:\.\d+)?)', cells[1].get_text(' ', strip=True))
        if not disc_match or not price_matches:
            continue
        discount = int(disc_match.group(1))
        if discount < MIN_DISCOUNT or discount > 100:
            continue
        current = float(price_matches[0].replace(',', ''))
        original = float(price_matches[1].replace(',', '')) if len(price_matches) > 1 else None
        if original is not None and (original <= current or original <= 0):
            original = None
        deals.append({
            'name': name[:160], 'url': link, 'discount': discount,
            'price': current, 'original': original,
            'image': image_from_row(row, response.url),
        })
    return deals


def money(value):
    return '₹{:,.2f}'.format(value).removesuffix('.00')


def post(deal):
    # Use the listing thumbnail first; fall back to game-page OpenGraph cover.
    cover = deal.get('image') or image_from_game_page(deal['url'])
    discount = deal['discount']
    current = money(deal['price'])
    old = money(deal['original']) if deal['original'] is not None else None
    description = (
        f'### 🔥 {discount}% OFF\n'
        f'## {current}\n'
        + (f'~~{old}~~  **Save {money(deal["original"] - deal["price"])}**\n' if old else '')
        + f'\n🛒 **[VIEW GAME DEAL]({deal["url"]})**'
    )
    embed = {
        'author': {'name': '🎮 PLAYSTATION STORE • INDIA'},
        'title': deal['name'],
        'url': deal['url'],
        'description': description,
        'color': 0x0868D7,
        'fields': [
            {'name': '🏷️ Discount', 'value': f'**{discount}% OFF**', 'inline': True},
            {'name': '🇮🇳 Region', 'value': 'India • INR', 'inline': True},
        ],
        'footer': {'text': 'PSN India Deals • PSPrices • Verify final price before purchase'},
    }
    if cover:
        embed['thumbnail'] = {'url': cover}
    else:
        print(f'No cover URL found for: {deal["name"]}')
    payload = {'username': 'PSN India Deals', 'embeds': [embed],
               'allowed_mentions': {'parse': []}}
    for attempt in range(3):
        response = SESSION.post(WEBHOOK, json=payload, timeout=25)
        if response.status_code != 429:
            response.raise_for_status()
            print(f'Posted: {deal["name"]} | image={bool(cover)}')
            return
        try:
            delay = float(response.json().get('retry_after', 2))
        except (ValueError, TypeError):
            delay = 2
        time.sleep(max(1, min(30, delay)))
    response.raise_for_status()


def main():
    if not WEBHOOK.startswith(('https://discord.com/api/webhooks/', 'https://discordapp.com/api/webhooks/')):
        raise RuntimeError('Set DISCORD_WEBHOOK_URL in GitHub Actions secrets.')
    found = {}
    for page in range(1, PAGES + 1):
        page_deals = fetch(page)
        print(f'Page {page}: parsed {len(page_deals)} qualifying offers')
        for deal in page_deals:
            found[deal['url']] = deal
        time.sleep(1)
    if not found:
        raise RuntimeError('No deals parsed: PSPrices HTML, access or filters may have changed.')
    observed = {url: f'{deal["price"]}|{deal["discount"]}' for url, deal in found.items()}
    if TEST_POST:
        # Does not modify history. Posts exactly one currently parsed listing.
        post(next(iter(found.values())))
        print('TEST_POST successful; history unchanged.')
        return
    previous = json.loads(STATE.read_text(encoding='utf-8')) if STATE.exists() else {}
    if not previous:
        STATE.write_text(json.dumps(observed, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(f'Initialized baseline of {len(observed)} deals; no alerts on first run.')
        return
    updates = [deal for url, deal in found.items() if previous.get(url) != observed[url]]
    selected = updates[:MAX_POSTS]
    for deal in selected:
        post(deal)
        previous[deal['url']] = observed[deal['url']]
        time.sleep(1)
    # Safe state handling: do not mark unsent updates as delivered.
    unsent_urls = {deal['url'] for deal in updates[MAX_POSTS:]}
    for url, value in observed.items():
        if url not in previous and url not in unsent_urls:
            previous[url] = value
    STATE.write_text(json.dumps(dict(list(previous.items())[-12000:]), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'Found {len(found)} qualifying deals; sent {len(selected)} new/changed alerts.')


if __name__ == '__main__':
    main()
