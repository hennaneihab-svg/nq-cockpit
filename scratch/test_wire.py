import urllib.request
import xml.etree.ElementTree as ET


def fetch_market_wire():
    news_items = []
    # Source 1: Google News US Markets (Fed, Nasdaq, Macro)
    url_gnews = (
        'https://news.google.com/rss/search?'
        'q=(Nasdaq+OR+FOMC+OR+"Federal+Reserve"+OR+CPI+OR+inflation)+when:2d'
        '&hl=en-US&gl=US&ceid=US:en'
    )
    try:
        req = urllib.request.Request(url_gnews, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as resp:
            root = ET.fromstring(resp.read())
            for item in list(root.iter('item'))[:12]:
                title = item.findtext('title') or ''
                pub = item.findtext('pubDate') or ''
                link = item.findtext('link') or ''
                source_elem = item.find('source')
                source_name = source_elem.text if source_elem is not None else 'Presse financière'
                news_items.append({
                    'title': title,
                    'time': pub,
                    'source': source_name,
                    'link': link,
                    'category': 'MACRO',
                })
    except Exception as e:
        print('Error gnews:', e)

    # Source 2: Federal Reserve Official Press Releases
    url_fed = 'https://www.federalreserve.gov/feeds/press_all.xml'
    try:
        req = urllib.request.Request(url_fed, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as resp:
            root = ET.fromstring(resp.read())
            for item in list(root.iter('item'))[:5]:
                title = item.findtext('title') or ''
                pub = item.findtext('pubDate') or ''
                link = item.findtext('link') or ''
                news_items.append({
                    'title': title,
                    'time': pub,
                    'source': 'Federal Reserve (Officiel)',
                    'link': link,
                    'category': 'FED',
                })
    except Exception as e:
        print('Error fed:', e)
    return news_items

if __name__ == '__main__':
    items = fetch_market_wire()
    print(f"Total retrieved: {len(items)}")
    for it in items[:5]:
        print(f"[{it['category']}] [{it['source']}] {it['title']}")
