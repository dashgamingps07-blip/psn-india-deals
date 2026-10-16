import json, os, re, time
from pathlib import Path
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

BASE = 'https://psprices.com'
SOURCE = BASE + '/region-in/discounts/'
STATE = Path('seen.json')
WEBHOOK = os.environ.get('DISCORD_WEBHOOK_URL', '').strip()
MIN_DISCOUNT = int(os.getenv('MIN_DISCOUNT', '50'))
MAX_POSTS = int(os.getenv('MAX_POSTS', '12'))
PAGES = max(1, min(5, int(os.getenv('PAGES', '2'))))
TEST_POST = os.getenv('TEST_POST', 'false').lower() == 'true'
SESSION = requests.Session()
SESSION.headers.update({'User-Agent': 'Mozilla/5.0 (compatible; PSNIndiaDeals/1.0; price-tracking personal use)', 'Accept-Language': 'en-IN,en;q=0.9'})

def fetch(page):
    r = SESSION.get(SOURCE, params={
        'display': 'table', 'ordering': 'desc', 'platform': 'PS5,PS4',
        'sort': 'date', 'page': page,
    }, timeout=25)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, 'html.parser')
    deals = []
    for row in soup.select('tr'):
        cells = row.find_all('td')
        if len(cells) < 3:
            continue
        anchor = next((a for a in cells[2].find_all('a', href=True)
                       if '/game/' in a['href'] or '/games/' in a['href']), None)
        if not anchor:
            # If layout changes, only use valid per-game links; never guess titles.
            continue
        name = anchor.get_text(' ', strip=True)
        link = urljoin(BASE, anchor['href'])
        disc_match = re.search(r'[−\-]\s*(\d{1,3})\s*%', cells[0].get_text(' ', strip=True))
        price_matches = re.findall(r'₹\s*([\d,]+(?:\.\d+)?)', cells[1].get_text(' ', strip=True))
        if not disc_match or not price_matches:
            continue
        pct = int(disc_match.group(1))
        if pct < MIN_DISCOUNT or pct > 100:
            continue
        current = float(price_matches[0].replace(',', ''))
        original = float(price_matches[1].replace(',', '')) if len(price_matches) > 1 else None
        if original is not None and (original < current or original <= 0):
            original = None
        deals.append({'name': name[:160], 'url': link, 'discount': pct,
                      'price': current, 'original': original})
    return deals

def money(value):
    return '₹{:,.2f}'.format(value).removesuffix('.00')

def post(deal):
    embed = {
        'title': deal['name'], 'url': deal['url'],
        'description': f"**{deal['discount']}% OFF**  •  **{money(deal['price'])}**" +
                       (f"  ~~{money(deal['original'])}~~" if deal['original'] else ''),
        'color': 0x1275ed,
        'fields': [{'name': 'Region', 'value': 'India (INR)', 'inline': True},
                   {'name': 'Platform', 'value': 'PS5 / PS4 listing', 'inline': True}],
        'footer': {'text': 'Source: PSPrices • Confirm final price on PlayStation Store'},
    }
    response = SESSION.post(WEBHOOK, json={'username': 'PSN India Deals', 'embeds': [embed]}, timeout=25)
    if response.status_code == 429:
        time.sleep(min(10, response.json().get('retry_after', 2)))
        response = SESSION.post(WEBHOOK, json={'username': 'PSN India Deals', 'embeds': [embed]}, timeout=25)
    response.raise_for_status()

def main():
    if not WEBHOOK.startswith('https://discord.com/api/webhooks/'):
        raise RuntimeError('Set DISCORD_WEBHOOK_URL in GitHub repository Actions secrets.')
    found = {}
    for page in range(1, PAGES + 1):
        for deal in fetch(page):
            found[deal['url']] = deal
        time.sleep(1)
    if not found:
        raise RuntimeError('No deals parsed. PSPrices layout/access may have changed; check the source and selectors.')
    previous = json.loads(STATE.read_text()) if STATE.exists() else {}
    # Compare URL+price+discount, so newly discounted/changed offers generate alerts.
    observed = {k: f"{v['price']}|{v['discount']}" for k, v in found.items()}
    if TEST_POST:
        post(next(iter(found.values())))
        print('TEST_POST delivered; real seen state unchanged.')
        return
    if not previous:
        STATE.write_text(json.dumps(observed, ensure_ascii=False, indent=2) + '\n')
        print(f'Baseline initialized with {len(observed)} deals; no flood sent.')
        return
    updates = [v for k, v in found.items() if previous.get(k) != observed[k]]
    # Old data may be outside the first pages. Preserve it while limiting state growth.
    sent = 0
    for deal in updates[:MAX_POSTS]:
        post(deal)
        previous[deal['url']] = observed[deal['url']]
        sent += 1
        time.sleep(1)
    # Mark unchanged offers as seen, but never mark unsent alerts as delivered.
    for k, value in observed.items():
        if k not in previous:
            if all(d['url'] != k for d in updates[MAX_POSTS:]):
                previous[k] = value
    STATE.write_text(json.dumps(dict(list(previous.items())[-12000:]), ensure_ascii=False, indent=2) + '\n')
    print(f'Found {len(found)} deals; sent {sent} new/changed alerts.')

if __name__ == '__main__':
    main()
