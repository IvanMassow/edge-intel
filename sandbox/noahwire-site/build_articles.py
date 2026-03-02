#!/usr/bin/env python3
"""
Noah Wire — RSS Article Builder
Fetches articles from RSS feeds, generates individual HTML pages with proper SEO,
builds a news index page, and generates sitemap.xml.

Run: python3 build_articles.py
Cron: */60 * * * * cd ~/noahwire-site && python3 build_articles.py
"""

import os
import re
import json
import hashlib
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html import escape, unescape
from pathlib import Path

# --- Config ---
FEEDS = [
    'https://noah.makes.news/section/663bf0becee334cd1f1a4bcf/rss.xml',
    'https://noah.makes.news/section/663bee09cee334cd1f1a4bca/rss.xml',
]
SITE_URL = 'https://www.noahwire.com'
OUTPUT_DIR = Path(__file__).parent / 'news' / 'articles'
NEWS_INDEX = Path(__file__).parent / 'news' / 'index.html'
SITEMAP_PATH = Path(__file__).parent / 'sitemap.xml'
ARTICLES_JSON = Path(__file__).parent / 'news' / 'articles.json'

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def slugify(text):
    """Convert text to URL-friendly slug."""
    text = unescape(text)
    text = re.sub(r'[^\w\s-]', '', text.lower())
    text = re.sub(r'[-\s]+', '-', text).strip('-')
    return text[:80]


def strip_html(html_text):
    """Remove HTML tags, return plain text."""
    clean = re.sub(r'<[^>]+>', '', html_text)
    clean = unescape(clean)
    return re.sub(r'\s+', ' ', clean).strip()


def fetch_feed(url):
    """Fetch and parse an RSS feed."""
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'NoahWire-Builder/1.0'})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return ET.fromstring(resp.read())
    except Exception as e:
        print(f"  Error fetching {url}: {e}")
        return None


def parse_items(root):
    """Extract articles from RSS XML."""
    items = []
    for item in root.findall('.//item'):
        title = item.findtext('title', '').strip()
        link = item.findtext('link', '').strip()
        desc = item.findtext('description', '').strip()
        pub_date = item.findtext('pubDate', '').strip()
        guid = item.findtext('guid', link).strip()

        # Image from enclosure
        enc = item.find('enclosure')
        image = enc.get('url', '') if enc is not None else ''

        if not title:
            continue

        # Parse date
        try:
            dt = datetime.strptime(pub_date, '%a, %d %b %Y %H:%M:%S %z')
        except (ValueError, TypeError):
            dt = datetime.now(timezone.utc)

        # Generate slug from title
        slug = slugify(title)
        # Add short hash for uniqueness
        uid = hashlib.md5(guid.encode()).hexdigest()[:6]
        slug = f"{slug}-{uid}"

        # Plain text excerpt
        plain = strip_html(desc)
        excerpt = plain[:200] + '...' if len(plain) > 200 else plain

        items.append({
            'title': title,
            'slug': slug,
            'link': link,
            'description': desc,
            'excerpt': excerpt,
            'plain_text': plain,
            'date': dt.isoformat(),
            'date_display': dt.strftime('%d %B %Y'),
            'date_short': dt.strftime('%d %b %Y'),
            'image': image,
            'guid': guid,
        })

    return items


def build_article_page(article):
    """Generate a single article HTML page."""
    title_escaped = escape(article['title'])
    excerpt_escaped = escape(article['excerpt'])
    url = f"{SITE_URL}/news/articles/{article['slug']}.html"

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title_escaped} — Noah Wire</title>
  <meta name="description" content="{excerpt_escaped}">
  <meta name="robots" content="index, follow">
  <link rel="canonical" href="{url}">
  <meta property="og:title" content="{title_escaped}">
  <meta property="og:description" content="{excerpt_escaped}">
  <meta property="og:type" content="article">
  <meta property="og:url" content="{url}">
  <meta property="article:published_time" content="{article['date']}">
  <meta property="article:publisher" content="Noah Wire Services">'''

    if article['image']:
        html += f'\n  <meta property="og:image" content="{escape(article["image"])}">'

    html += f'''
  <script type="application/ld+json">
  {{
    "@context": "https://schema.org",
    "@type": "NewsArticle",
    "headline": "{title_escaped}",
    "description": "{excerpt_escaped}",
    "datePublished": "{article['date']}",
    "publisher": {{
      "@type": "Organization",
      "name": "Noah Wire Services",
      "url": "{SITE_URL}"
    }},
    "mainEntityOfPage": "{url}"'''

    if article['image']:
        html += f',\n    "image": "{escape(article["image"])}"'

    html += '''
  }
  </script>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Montserrat:wght@600;700;800&family=Playfair+Display:ital,wght@0,400;0,500;0,600;0,700;1,400;1,500&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="../../assets/css/style.css">
  <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>N</text></svg>">
  <style>
    .article-body { max-width: 720px; margin: 0 auto; }
    .article-body p { margin-bottom: 1.25em; font-size: var(--text-lg); line-height: 1.8; color: var(--text-secondary); }
    .article-body strong { color: var(--text-primary); }
    .article-hero-img { width: 100%; max-height: 480px; object-fit: cover; border-radius: 12px; margin-bottom: 2.5rem; }
    .article-meta { font-size: var(--text-sm); color: var(--text-tertiary); margin-bottom: 2rem; }
    .article-back { font-size: var(--text-sm); color: var(--text-tertiary); margin-bottom: 2rem; display: inline-flex; align-items: center; gap: 0.5rem; }
    .article-back:hover { color: var(--accent-light); }
  </style>
</head>
<body>

  <nav class="nav scrolled">
    <div class="nav__inner">
      <a href="../../index.html" class="nav__logo">Noah Wire</a>
      <ul class="nav__links">
        <li><a href="../../wire.html" class="nav__link">Wire</a></li>
        <li><a href="../../intelligence.html" class="nav__link">Intelligence</a></li>
        <li><a href="../../agent.html" class="nav__link">Agent Noah</a></li>
        <li><a href="../" class="nav__link active">News</a></li>
        <li><a href="../../about.html" class="nav__link">About</a></li>
        <li><a href="../../contact.html" class="nav__cta">Book a Demo</a></li>
      </ul>
      <button class="nav__toggle" aria-label="Toggle menu"><span></span><span></span><span></span></button>
    </div>
    <div class="nav__mobile">
      <a href="../../wire.html">Wire</a><a href="../../intelligence.html">Intelligence</a><a href="../../agent.html">Agent Noah</a>
      <a href="../">News</a><a href="../../about.html">About</a><a href="../../contact.html">Book a Demo</a>
    </div>
  </nav>

  <section class="section section--dark" style="padding-top: calc(var(--nav-height) + 3rem);">
    <div class="container container--narrow">'''

    html += f'''
      <a href="../" class="article-back">
        <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m15 18-6-6 6-6"/></svg>
        Back to News
      </a>
      <article>
        <h1 style="font-size: clamp(1.75rem, 3.5vw, var(--text-4xl)); margin-bottom: 1rem;">{title_escaped}</h1>
        <div class="article-meta">
          <time datetime="{article['date']}">{article['date_display']}</time>
          &nbsp;&middot;&nbsp; Noah Wire
        </div>'''

    if article['image']:
        html += f'''
        <img class="article-hero-img" src="{escape(article['image'])}" alt="{title_escaped}" loading="lazy">'''

    html += f'''
        <div class="article-body">
          {article['description']}
        </div>
        <hr class="divider" style="margin: 3rem 0;">
        <p style="font-size: var(--text-sm); color: var(--text-tertiary);">
          This article was produced by Noah Wire Services. Original source:
          <a href="{escape(article['link'])}" target="_blank" rel="noopener">{escape(article['link'])}</a>
        </p>
      </article>
    </div>
  </section>

  <footer class="footer">
    <div class="container">
      <div class="footer__bottom">
        <span>&copy; 2026 Noah Wire Services Ltd.</span>
        <span>London, United Kingdom</span>
      </div>
    </div>
  </footer>

  <script src="../../assets/js/main.js"></script>
</body>
</html>'''

    return html


def build_news_index(articles):
    """Generate the news index page."""
    cards = ''
    for a in articles[:30]:  # Show latest 30
        img_html = ''
        if a['image']:
            img_html = f'<div class="news-card__image"><img src="articles/{a["slug"]}.html" data-src="{escape(a["image"])}" alt="" loading="lazy" onerror="this.parentElement.style.display=\'none\'" style="width:100%;height:100%;object-fit:cover;"></div>'
            # Fix: use actual image URL
            img_html = f'<div style="aspect-ratio:16/9;overflow:hidden;border-radius:12px 12px 0 0;"><img src="{escape(a["image"])}" alt="" loading="lazy" style="width:100%;height:100%;object-fit:cover;"></div>'

        cards += f'''
      <article class="card reveal" style="padding: 0; overflow: hidden;">
        {img_html}
        <div style="padding: 1.5rem;">
          <time style="font-size: var(--text-xs); color: var(--text-tertiary); text-transform: uppercase; letter-spacing: 0.08em;">{a['date_short']}</time>
          <h3 style="font-family: var(--font-display); font-size: var(--text-lg); line-height: 1.3; margin: 0.5rem 0 0.75rem;">
            <a href="articles/{a['slug']}.html" style="color: var(--text-primary); text-decoration: none;">{escape(a['title'])}</a>
          </h3>
          <p style="font-size: var(--text-sm); color: var(--text-tertiary); line-height: 1.5; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden;">
            {escape(a['excerpt'])}
          </p>
        </div>
      </article>'''

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Latest News — Noah Wire</title>
  <meta name="description" content="Latest news and intelligence from Noah Wire. Updated every hour with fresh, authoritative, copyright-clean content.">
  <meta name="robots" content="index, follow">
  <link rel="canonical" href="{SITE_URL}/news/">
  <meta property="og:title" content="Latest News — Noah Wire">
  <meta property="og:description" content="Fresh intelligence, every hour. Latest news from Noah Wire Services.">
  <meta property="og:type" content="website">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Montserrat:wght@600;700;800&family=Playfair+Display:ital,wght@0,400;0,500;0,600;0,700;1,400;1,500&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="../assets/css/style.css">
  <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>N</text></svg>">
</head>
<body>

  <nav class="nav">
    <div class="nav__inner">
      <a href="../index.html" class="nav__logo">Noah Wire</a>
      <ul class="nav__links">
        <li><a href="../wire.html" class="nav__link">Wire</a></li>
        <li><a href="../intelligence.html" class="nav__link">Intelligence</a></li>
        <li><a href="../agent.html" class="nav__link">Agent Noah</a></li>
        <li><a href="./" class="nav__link active">News</a></li>
        <li><a href="../about.html" class="nav__link">About</a></li>
        <li><a href="../contact.html" class="nav__cta">Book a Demo</a></li>
      </ul>
      <button class="nav__toggle" aria-label="Toggle menu"><span></span><span></span><span></span></button>
    </div>
    <div class="nav__mobile">
      <a href="../wire.html">Wire</a><a href="../intelligence.html">Intelligence</a><a href="../agent.html">Agent Noah</a>
      <a href="./">News</a><a href="../about.html">About</a><a href="../contact.html">Book a Demo</a>
    </div>
  </nav>

  <section class="section section--dark" style="padding-top: calc(var(--nav-height) + 4rem);">
    <div class="container">
      <div class="reveal" style="margin-bottom: 3rem;">
        <span class="eyebrow">Latest from the Wire</span>
        <h1 style="font-size: clamp(2rem, 4vw, var(--text-5xl));">Fresh intelligence, every hour</h1>
        <p style="margin-top: 1rem; max-width: 600px;">
          Our wire delivers original, fact-checked news around the clock.
          Every story indexed, every source cited.
        </p>
      </div>
      <div class="grid grid--3">
        {cards}
      </div>
    </div>
  </section>

  <footer class="footer">
    <div class="container">
      <div class="footer__bottom">
        <span>&copy; 2026 Noah Wire Services Ltd.</span>
        <span>London, United Kingdom</span>
      </div>
    </div>
  </footer>

  <script src="../assets/js/main.js"></script>
</body>
</html>'''


def build_sitemap(articles, pages):
    """Generate sitemap.xml."""
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    urls = ''

    for page in pages:
        urls += f'''
  <url>
    <loc>{SITE_URL}/{page}</loc>
    <lastmod>{now}</lastmod>
    <changefreq>weekly</changefreq>
    <priority>0.8</priority>
  </url>'''

    for a in articles:
        urls += f'''
  <url>
    <loc>{SITE_URL}/news/articles/{a['slug']}.html</loc>
    <lastmod>{a['date'][:10]}</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.6</priority>
  </url>'''

    return f'''<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}
</urlset>'''


def main():
    print("Noah Wire Article Builder")
    print("=" * 40)

    # Fetch all feeds
    all_articles = []
    for feed_url in FEEDS:
        print(f"Fetching: {feed_url}")
        root = fetch_feed(feed_url)
        if root is not None:
            items = parse_items(root)
            print(f"  Found {len(items)} articles")
            all_articles.extend(items)

    if not all_articles:
        print("No articles found. Exiting.")
        return

    # Deduplicate by guid
    seen = set()
    unique = []
    for a in all_articles:
        if a['guid'] not in seen:
            seen.add(a['guid'])
            unique.append(a)
    all_articles = unique

    # Sort by date (newest first)
    all_articles.sort(key=lambda x: x['date'], reverse=True)
    print(f"\nTotal unique articles: {len(all_articles)}")

    # Build individual article pages
    print("\nGenerating article pages...")
    for a in all_articles:
        filepath = OUTPUT_DIR / f"{a['slug']}.html"
        html = build_article_page(a)
        filepath.write_text(html, encoding='utf-8')
        print(f"  -> {a['slug']}.html")

    # Build news index
    print("\nGenerating news index...")
    index_html = build_news_index(all_articles)
    NEWS_INDEX.write_text(index_html, encoding='utf-8')
    print(f"  -> news/index.html")

    # Save articles JSON (for any tooling)
    articles_data = [{k: v for k, v in a.items() if k != 'description'} for a in all_articles]
    ARTICLES_JSON.write_text(json.dumps(articles_data, indent=2), encoding='utf-8')
    print(f"  -> news/articles.json")

    # Build sitemap
    print("\nGenerating sitemap.xml...")
    pages = ['', 'wire.html', 'intelligence.html', 'agent.html', 'about.html', 'contact.html', 'news/']
    sitemap_xml = build_sitemap(all_articles, pages)
    SITEMAP_PATH.write_text(sitemap_xml, encoding='utf-8')
    print(f"  -> sitemap.xml")

    print(f"\nDone! {len(all_articles)} articles generated.")


if __name__ == '__main__':
    main()
