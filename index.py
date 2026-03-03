"""
Dayynime API — Real scraper + halaman dokumentasi
/ → Halaman dokumentasi cantik
/anime/* → Endpoint scraper beneran
"""
from flask import Flask, jsonify, request, render_template_string
from bs4 import BeautifulSoup
from markupsafe import Markup
from collections import defaultdict
import cloudscraper, base64, re, json as _json, time

app = Flask(__name__)

BASE_URL  = "https://v1.animasu.app"
BASE_SHK  = "https://v1.samehadaku.how"   # Samehadaku source
BASE_OTK  = "https://otakudesu.best"       # Otakudesu source
CACHE     = {}
CACHE_TTL = {
    "home": 300, "ongoing": 180, "completed": 600,
    "movies": 600, "popular": 600, "search": 120,
    "detail": 600, "episode": 180, "genres": 3600,
    "schedule": 1800,
}

# ── Rate Limiter ──────────────────────────────────────────────
RATE_LIMIT    = 70    # max request normal
RATE_WINDOW   = 60    # per 60 detik (1 menit)
WARN_COUNT    = 3     # jumlah peringatan sebelum ban
BAN_DURATION  = 300   # ban 5 menit (detik)

_rate_store   = defaultdict(list)   # { ip: [timestamp, ...] }
_warn_store   = defaultdict(int)    # { ip: jumlah_peringatan }
_ban_store    = {}                  # { ip: ban_until_timestamp }

def _get_ip():
    return (
        request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        or request.headers.get("x-real-ip", "")
        or request.remote_addr
        or "unknown"
    )

@app.before_request
def check_rate_limit():
    if not request.path.startswith("/anime/"):
        return

    ip  = _get_ip()
    now = time.time()

    # ── Cek apakah sedang kena ban ──
    if ip in _ban_store:
        ban_until = _ban_store[ip]
        if now < ban_until:
            sisa = int(ban_until - now)
            resp = jsonify({
                "status":      "banned",
                "message":     f"🚫 IP kamu di-ban sementara karena melebihi batas request. Coba lagi dalam {sisa} detik.",
                "retry_after": sisa,
                "ban_duration": BAN_DURATION,
            })
            resp.status_code = 429
            resp.headers["Retry-After"] = str(sisa)
            return resp
        else:
            # Ban sudah habis, reset
            del _ban_store[ip]
            _warn_store[ip] = 0

    # ── Hitung request dalam window ──
    _rate_store[ip] = [t for t in _rate_store[ip] if now - t < RATE_WINDOW]
    req_count = len(_rate_store[ip])

    if req_count < RATE_LIMIT:
        # Masih aman, catat request
        _rate_store[ip].append(now)
        return

    # ── Sudah melebihi limit, beri peringatan dulu ──
    _warn_store[ip] += 1
    warn_ke = _warn_store[ip]

    if warn_ke <= WARN_COUNT:
        # Masih dalam tahap peringatan
        oldest = min(_rate_store[ip])
        retry  = int(RATE_WINDOW - (now - oldest)) + 1
        sisa_warn = WARN_COUNT - warn_ke
        resp = jsonify({
            "status":       "warning",
            "message":      f"⚠️ Peringatan {warn_ke}/{WARN_COUNT}: Kamu melebihi batas {RATE_LIMIT} request per menit! {'Sisa ' + str(sisa_warn) + ' peringatan sebelum di-ban.' if sisa_warn > 0 else 'Ini peringatan terakhir! Request berikutnya akan di-ban.'}",
            "warning_ke":   warn_ke,
            "sisa_peringatan": sisa_warn,
            "retry_after":  retry,
            "limit":        RATE_LIMIT,
        })
        resp.status_code = 429
        resp.headers["Retry-After"]       = str(retry)
        resp.headers["X-RateLimit-Limit"] = str(RATE_LIMIT)
        resp.headers["X-Warning-Count"]   = str(warn_ke)
        return resp
    else:
        # Peringatan habis → BAN
        _ban_store[ip] = now + BAN_DURATION
        _warn_store[ip] = 0
        _rate_store[ip] = []
        resp = jsonify({
            "status":       "banned",
            "message":      f"🚫 IP kamu di-ban selama {BAN_DURATION // 60} menit karena terus melebihi batas request setelah {WARN_COUNT}x peringatan.",
            "retry_after":  BAN_DURATION,
            "ban_duration": BAN_DURATION,
        })
        resp.status_code = 429
        resp.headers["Retry-After"] = str(BAN_DURATION)
        return resp

# ══════════════════════════════════════════════════════
# SCRAPER CORE
# ══════════════════════════════════════════════════════

def _scraper():
    s = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "mobile": False}
    )
    s.headers.update({
        "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8",
        "Referer":         BASE_URL + "/",
    })
    return s

def _cached(key, ttl_type, fn):
    now = time.time()
    if key in CACHE:
        data, ts = CACHE[key]
        if now - ts < CACHE_TTL.get(ttl_type, 300):
            return data
    data = fn()
    if data:
        CACHE[key] = (data, now)
    return data

def _get(path_or_url):
    url = path_or_url if path_or_url.startswith("http") else BASE_URL + path_or_url
    try:
        r = _scraper().get(url, timeout=15)
        if r.status_code == 200:
            return BeautifulSoup(r.text, "html.parser")
        return None
    except Exception as e:
        print(f"Fetch error [{url}]: {e}")
        return None

def _get_shk(path_or_url, retries=4):
    """CF bypass multi-strategy khusus samehadaku."""
    url = path_or_url if path_or_url.startswith("http") else BASE_SHK + path_or_url
    strategies = [
        {"browser": {"browser": "chrome",  "platform": "windows", "mobile": False}},
        {"browser": {"browser": "chrome",  "platform": "linux",   "mobile": False}},
        {"browser": {"browser": "firefox", "platform": "windows", "mobile": False}},
        {"browser": {"browser": "chrome",  "platform": "android", "mobile": True}},
    ]
    headers_base = {
        "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8",
        "Referer":         BASE_SHK + "/",
    }
    for i in range(retries):
        try:
            if i > 0: time.sleep(i * 1.5)
            s = cloudscraper.create_scraper(**strategies[i % len(strategies)])
            ua = ("Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 Chrome/124.0.0.0 Mobile Safari/537.36"
                  if i == 3 else
                  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36")
            s.headers.update({**headers_base, "User-Agent": ua})
            r = s.get(url, timeout=20)
            if r.status_code == 200:
                return BeautifulSoup(r.text, "html.parser")
        except Exception as e:
            print(f"[shk] attempt {i+1} error: {e}")
    return None

def _get_otk(path_or_url, retries=6):
    """CF bypass agresif untuk otakudesu.best (Animestream + Cloudflare)."""
    import requests as _req
    url = path_or_url if path_or_url.startswith("http") else BASE_OTK + path_or_url

    # Berbagai kombinasi browser + UA yang sering lolos CF
    strategies = [
        # cloudscraper strategies
        ("cs", {"browser": {"browser": "chrome",  "platform": "windows", "mobile": False},
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"}),
        ("cs", {"browser": {"browser": "chrome",  "platform": "linux",   "mobile": False},
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"}),
        ("cs", {"browser": {"browser": "firefox", "platform": "windows", "mobile": False},
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0"}),
        ("cs", {"browser": {"browser": "chrome",  "platform": "android", "mobile": True},
                "User-Agent": "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 Chrome/124.0.0.0 Mobile Safari/537.36"}),
        # requests biasa fallback
        ("req", {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"}),
        ("req", {"User-Agent": "Googlebot/2.1 (+http://www.google.com/bot.html)"}),
    ]

    headers_base = {
        "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection":      "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest":  "document",
        "Sec-Fetch-Mode":  "navigate",
        "Sec-Fetch-Site":  "none",
        "Referer":         BASE_OTK + "/",
    }

    for i in range(min(retries, len(strategies))):
        mode, cfg = strategies[i]
        try:
            if i > 0: time.sleep(i * 1.0)
            headers = {**headers_base, "User-Agent": cfg["User-Agent"]}

            if mode == "cs":
                browser_cfg = {k: v for k, v in cfg.items() if k != "User-Agent"}
                s = cloudscraper.create_scraper(**browser_cfg)
                s.headers.update(headers)
                r = s.get(url, timeout=15, allow_redirects=True)
            else:
                sess = _req.Session()
                sess.headers.update(headers)
                r = sess.get(url, timeout=15, allow_redirects=True)

            print(f"[otk] attempt {i+1} ({mode}) → {r.status_code} | {len(r.content)} bytes")

            if r.status_code == 200:
                if "challenge" in r.text[:500].lower() or "just a moment" in r.text[:500].lower():
                    print(f"[otk] attempt {i+1} → CF challenge, retry...")
                    continue
                return BeautifulSoup(r.text, "html.parser")
            elif r.status_code in (403, 503, 429):
                print(f"[otk] attempt {i+1} → blocked ({r.status_code}), retry...")
                time.sleep(2)
        except Exception as e:
            print(f"[otk] attempt {i+1} error: {e}")
    return None

# ══════════════════════════════════════════════════════
# OTAKUDESU SCRAPER FUNCTIONS
# Theme   : Animestream (WordPress 5.6.16)
# Domain  : otakudesu.best
# Cards   : .detpost
# Paginate: /page/{n}/
# Episodes: .episodelist li
# Servers : SELECT + base64 decode
# Search  : /?s={query}
# Schedule: /jadwal-rilis/ (.venz structure)
# Genres  : /genre-list/ → /genres/{slug}/
# ══════════════════════════════════════════════════════

def _otk_get_cards(soup):
    return soup.select(".detpost")

def _otk_parse_card(card):
    d = {}
    for sel in ["h2", "h3", ".title", "a[title]"]:
        el = card.select_one(sel)
        if el:
            text = el.get_text(strip=True) or el.get("title", "")
            if text and len(text) > 1:
                d["title"] = text; break
    a = card.select_one("a[href]")
    if a:
        d["url"]     = a["href"]
        d["animeId"] = a["href"].rstrip("/").split("/")[-1]
    img = card.select_one("img")
    if img:
        for attr in ["src", "data-src", "data-lazy-src", "data-original"]:
            v = img.get(attr, "")
            if v and v.startswith("http"):
                d["poster"] = v; break
    for sel in [".epz", ".epx", ".ep", ".eggepisode", ".l2"]:
        el = card.select_one(sel)
        if el: d["episode"] = el.get_text(strip=True); break
    for sel in [".typez", ".type", ".etiket"]:
        el = card.select_one(sel)
        if el: d["type"] = el.get_text(strip=True); break
    return d

def _otk_pagination(soup, page=1):
    p = {"hasNextPage": False, "hasPrevPage": False, "currentPage": page}
    if soup.select_one(".next.page-numbers, a.next, [rel='next']"):
        p["hasNextPage"] = True
    p["hasPrevPage"] = page > 1
    cur = soup.select_one(".page-numbers.current")
    if cur:
        try: p["currentPage"] = int(re.sub(r"\D", "", cur.get_text()))
        except: pass
    return p

def _otk_server_type(url):
    u = url.lower()
    for k, v in {
        "desustream": "desustream", "blogger.com": "blogger",
        "mega.nz": "mega", "vidhide": "vidhide",
        "doodstream": "doodstream", "streamtape": "streamtape",
        "ok.ru": "okru", "streamwish": "streamwish",
        "filelions": "filelions", ".mp4": "mp4", ".m3u8": "m3u8",
    }.items():
        if k in u: return v
    return "embed"

def _otk_decode_server(val):
    try:
        padded  = val + "=" * (4 - len(val) % 4)
        decoded = base64.b64decode(padded).decode("utf-8", errors="ignore")
        m = re.search(r'src=["\'](https?://[^"\']+)["\']', decoded)
        if m: return m.group(1)
        if decoded.strip().startswith("http"): return decoded.strip()
    except:
        pass
    return None

def _otk_do_home():
    soup = _get_otk("/")
    if not soup: return None
    return {"animeList": [_otk_parse_card(c) for c in _otk_get_cards(soup)]}

def _otk_do_list(path, page=1):
    url = path.rstrip("/") + f"/page/{page}/" if page > 1 else path
    soup = _get_otk(url)
    if not soup: return None
    return {
        "animeList":  [_otk_parse_card(c) for c in _otk_get_cards(soup)],
        "pagination": _otk_pagination(soup, page),
    }

def _otk_do_search(query, page=1):
    url = f"/page/{page}/?s={query}" if page > 1 else f"/?s={query}"
    soup = _get_otk(url)
    if not soup: return None
    return {
        "query":      query,
        "animeList":  [_otk_parse_card(c) for c in _otk_get_cards(soup)],
        "pagination": _otk_pagination(soup, page),
    }

def _otk_do_detail(slug):
    soup = _get_otk(f"/anime/{slug}/")
    if not soup: return None
    d = {
        "animeId": slug, "title": "", "poster": "",
        "synopsis": "", "genres": [], "info": {}, "episodeList": [],
    }
    h1 = soup.select_one("h1")
    if h1: d["title"] = h1.get_text(strip=True)

    img = soup.select_one(".wp-post-image")
    if img: d["poster"] = img.get("src") or img.get("data-src", "")

    for sel in [".sinopc p", ".sinopc", ".entry-content p", ".desc p"]:
        el = soup.select_one(sel)
        if el and len(el.get_text(strip=True)) > 30:
            d["synopsis"] = el.get_text(strip=True); break

    for row in soup.select(".infox .spe span, .spe span"):
        t = row.get_text(" ", strip=True)
        if ":" in t:
            k, _, v = t.partition(":")
            if k.strip() and v.strip():
                d["info"][k.strip().lower()] = v.strip()

    score_el = soup.select_one(".rating strong, .score, .rtg")
    if score_el: d["info"]["score"] = score_el.get_text(strip=True)

    seen_g = set()
    for a in soup.select("a[href*='genre'], a[href*='genres']"):
        name     = a.get_text(strip=True)
        href     = a.get("href", "")
        genre_id = href.rstrip("/").split("/")[-1]
        if name and genre_id and genre_id not in seen_g \
                and genre_id not in ("genre-list", "genres", "genre"):
            seen_g.add(genre_id)
            d["genres"].append({"name": name, "genreId": genre_id})

    for li in soup.select(".episodelist li"):
        a = li.find("a", href=True)
        if not a: continue
        ep_slug = a["href"].rstrip("/").split("/")[-1]
        if "episode" not in ep_slug.lower(): continue
        m = re.search(r"episode[- _](\d+(?:\.\d+)?)", ep_slug, re.I)
        date_el = li.select_one("span.zeebr, span.date, .released")
        d["episodeList"].append({
            "episodeId": ep_slug,
            "num":       m.group(1) if m else "",
            "title":     a.get_text(strip=True),
            "date":      date_el.get_text(strip=True) if date_el else "",
        })
    return d

def _otk_do_episode(slug):
    soup = _get_otk(f"/episode/{slug}/")
    if not soup: soup = _get_otk(f"/{slug}/")
    if not soup: return None
    d = {
        "episodeId": slug, "title": "", "animeId": "",
        "episodeNum": "", "prevEpisode": None, "nextEpisode": None,
        "defaultEmbed": "", "servers": [],
    }
    h1 = soup.select_one("h1.entry-title, h1")
    if h1: d["title"] = h1.get_text(strip=True)

    for a in soup.select("a[href*='/anime/']"):
        href = a.get("href", "")
        a_slug = href.rstrip("/").split("/")[-1]
        if a_slug and a_slug != slug:
            d["animeId"] = a_slug; break

    m = re.search(r"episode[- _](\d+(?:\.\d+)?)", slug, re.I)
    if m: d["episodeNum"] = m.group(1)

    for a in soup.select(".nvs a, .naveps a, .nflx a, .nextprev a, .episodegate a"):
        href  = a.get("href", "")
        text  = a.get_text(strip=True).lower()
        ep2   = href.rstrip("/").split("/")[-1]
        if "episode" not in ep2: continue
        if any(w in text for w in ["sebelum", "prev", "◄", "←", "«"]):
            d["prevEpisode"] = ep2
        elif any(w in text for w in ["selanjut", "next", "►", "→", "»"]):
            d["nextEpisode"] = ep2

    iframe = soup.select_one("#pembed iframe, .pembed iframe, iframe[src]")
    if iframe: d["defaultEmbed"] = iframe.get("src", "")

    servers = []
    for sel_el in soup.select("select"):
        opts = sel_el.select("option")
        if any(opt.get("value","").startswith("http") and "/episode/" in opt.get("value","")
               for opt in opts):
            continue  # skip select navigasi episode
        for opt in opts:
            val = opt.get("value", "").strip()
            lbl = opt.get_text(strip=True)
            if not val or lbl.lower() in ("pilih server", "select server", ""): continue
            decoded = _otk_decode_server(val)
            if not decoded and val.startswith("http") and BASE_OTK not in val:
                decoded = val
            if decoded:
                if not d["defaultEmbed"]: d["defaultEmbed"] = decoded
                servers.append({"name": lbl, "embedUrl": decoded, "type": _otk_server_type(decoded)})

    if not servers and d["defaultEmbed"]:
        servers.append({"name": "Server 1", "embedUrl": d["defaultEmbed"],
                        "type": _otk_server_type(d["defaultEmbed"])})
    d["servers"] = servers
    return d

def _otk_do_genres():
    soup = _get_otk("/genre-list/")
    if not soup: return None
    genres, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"]; name = a.get_text(strip=True)
        slug = href.rstrip("/").split("/")[-1]
        if not name or not slug or slug in seen or len(name) > 40: continue
        if "/genres/" not in href and "/genre/" not in href: continue
        seen.add(slug)
        genres.append({"name": name, "genreId": slug, "url": href})
    return {"genreList": genres}

def _otk_do_schedule():
    soup = _get_otk("/jadwal-rilis/")
    if not soup: return None
    DAYS_ID = {
        "monday":"Senin","tuesday":"Selasa","wednesday":"Rabu",
        "thursday":"Kamis","friday":"Jumat","saturday":"Sabtu","sunday":"Minggu",
        "senin":"Senin","selasa":"Selasa","rabu":"Rabu",
        "kamis":"Kamis","jumat":"Jumat","sabtu":"Sabtu","minggu":"Minggu",
    }
    DAY_ORDER = ["Senin","Selasa","Rabu","Kamis","Jumat","Sabtu","Minggu"]
    sch = {}
    for block in soup.select(".venz"):
        ne = block.select_one("h2, h3, h4, strong, b, .hari")
        if not ne: continue
        day_name = DAYS_ID.get(ne.get_text(strip=True).lower().strip())
        if not day_name: continue
        items = []
        for li in block.select("ul li"):
            a = li.find("a", href=True)
            if not a: continue
            title = a.get_text(strip=True); href = a["href"]
            if not title or not href: continue
            poster = ""
            img = li.find("img")
            if img:
                for attr in ["src","data-src","data-lazy-src","data-original"]:
                    v = img.get(attr, "")
                    if v and v.startswith("http"): poster = v; break
            items.append({"title": title, "animeId": href.rstrip("/").split("/")[-1],
                          "url": href, "poster": poster})
        if items: sch[day_name] = items
    return {"days": [{"day": d, "animeList": sch[d]} for d in DAY_ORDER if d in sch]}


def ok(data):
    return jsonify({"status": "success", "data": data})

def err(msg, code=500):
    return jsonify({"status": "error", "message": msg}), code

def _parse_card(card):
    data = {}
    el = card.select_one("h2, h3, .tt, .ntitle, a[title]")
    if el:
        data["title"] = el.get_text(strip=True) or el.get("title", "")
    a = card.select_one("a[href]")
    if a:
        href = a.get("href", "")
        data["url"]     = href
        data["animeId"] = href.rstrip("/").split("/")[-1]
    img = card.select_one("img[src], img[data-src], img[data-lazy-src]")
    if img:
        data["poster"] = img.get("src") or img.get("data-src") or img.get("data-lazy-src") or ""
    el = card.select_one(".epx, .eggepisode, .ep, .l2")
    if el: data["episodes"] = el.get_text(strip=True)
    el = card.select_one(".typez, .type, .etiket")
    if el: data["type"] = el.get_text(strip=True)
    el = card.select_one(".score, .numscore, .rating")
    if el: data["score"] = el.get_text(strip=True)
    return data

def _parse_pagination(soup):
    pag = {"hasNextPage": False, "hasPrevPage": False, "currentPage": 1}
    if soup.select_one(".next.page-numbers, a.next, [rel='next']"): pag["hasNextPage"] = True
    if soup.select_one(".prev.page-numbers, a.prev, [rel='prev']"): pag["hasPrevPage"] = True
    cur = soup.select_one(".page-numbers.current")
    if cur:
        try: pag["currentPage"] = int(cur.get_text(strip=True))
        except: pass
    return pag

def _decode_server(b64_value):
    if not b64_value: return ""
    try:
        padded  = b64_value + "=" * (4 - len(b64_value) % 4)
        decoded = base64.b64decode(padded).decode("utf-8", errors="ignore")
        m = re.search(r'src=["\']([^"\']+)["\']', decoded)
        if m: return m.group(1)
        if decoded.startswith("http"): return decoded.strip()
        return ""
    except: return ""

def _detect_server_type(url):
    u = url.lower()
    if "blogger.com" in u:  return "blogger"
    if "mega.nz"     in u:  return "mega"
    if "vidhide"     in u:  return "vidhide"
    if "doodstream"  in u:  return "doodstream"
    if "streamtape"  in u:  return "streamtape"
    return "embed"

def _do_schedule_raw(soup):
    schedule = {}
    days_map = {
        "sunday":"Minggu","monday":"Senin","tuesday":"Selasa",
        "wednesday":"Rabu","thursday":"Kamis","friday":"Jumat","saturday":"Sabtu",
        "minggu":"Minggu","senin":"Senin","selasa":"Selasa",
        "rabu":"Rabu","kamis":"Kamis","jumat":"Jumat","sabtu":"Sabtu",
    }
    for day_el in soup.select(".schedulelist, .schedule .day, .jadwal-hari, .scheduleday"):
        day_name_el = day_el.select_one("h2, h3, .day-name, strong, .title")
        if not day_name_el: continue
        raw      = day_name_el.get_text(strip=True).lower()
        day_name = days_map.get(raw, raw.title())
        items    = []
        for a in day_el.select("li a, .animepost a, .bs a"):
            items.append({"title": a.get_text(strip=True), "animeId": a["href"].rstrip("/").split("/")[-1], "url": a["href"]})
        if items: schedule[day_name] = items
    return schedule

def _do_home():
    soup = _get("/")
    if not soup: return None
    ongoing = [p for c in soup.select(".bs") if (p := _parse_card(c)) and p.get("title")]
    popular = []
    for c in soup.select(".popular .bs, .trending .bs, .owl-item .bs"):
        p = _parse_card(c)
        if p.get("title"): popular.append(p)
    return {"ongoing": ongoing, "popular": popular, "schedule": _do_schedule_raw(soup)}

def _do_list(status, page):
    url_map = {"movie": f"/anime/?type=movie&page={page}", "popular": f"/anime/?order=popular&page={page}"}
    soup = _get(url_map.get(status, f"/anime/?status={status}&page={page}"))
    if not soup: return None
    return {"animeList": [_parse_card(c) for c in soup.select(".bs")], "pagination": _parse_pagination(soup)}

def _do_search(query, page):
    soup = _get(f"/page/{page}/?s={query}" if page > 1 else f"/?s={query}")
    if not soup: return None
    return {"animeList": [_parse_card(c) for c in soup.select(".bs")], "pagination": _parse_pagination(soup), "query": query}

def _do_detail(slug):
    soup = _get(f"/anime/{slug}/")
    if not soup: return None
    data = {"animeId": slug, "title": "", "poster": "", "synopsis": "", "status": "", "type": "", "score": "", "studio": "", "released": "", "genres": [], "info": {}, "episodeList": []}
    el = soup.select_one(".entry-title, h1.title, h1")
    if el: data["title"] = el.get_text(strip=True)
    el = soup.select_one(".thumb img, .poster img, .wp-post-image")
    if el: data["poster"] = el.get("src") or el.get("data-src", "")
    el = soup.select_one(".entry-content p, .sinopsis p, .desc p")
    if el: data["synopsis"] = el.get_text(strip=True)
    for row in soup.select(".spe span, .infox .spe span"):
        text = row.get_text(" ", strip=True)
        if ":" in text:
            k, _, v = text.partition(":")
            key, val = k.strip().lower(), v.strip()
            data["info"][key] = val
            if "status" in key: data["status"] = val
            if "tipe" in key or "type" in key: data["type"] = val
            if "skor" in key or "score" in key: data["score"] = val
            if "studio" in key: data["studio"] = val
            if "tayang" in key or "rilis" in key: data["released"] = val
    for a in soup.select(".genre-info a, .genxed a, .spe a[href*='genre']"):
        name = a.get_text(strip=True)
        slug_g = a["href"].rstrip("/").split("/")[-1]
        if name and slug_g: data["genres"].append({"name": name, "genreId": slug_g})
    ep_links = soup.select("#daftarepisode li a") or soup.select("ul li a[href*='episode']")
    for a in ep_links:
        ep_slug = a.get("href", "").rstrip("/").split("/")[-1]
        m = re.search(r"episode[- ](\d+(?:\.\d+)?)", ep_slug, re.I)
        li = a.find_parent("li")
        ep_date = li.select_one(".date, .epl-date") if li else None
        data["episodeList"].append({"episodeId": ep_slug, "title": a.get_text(strip=True), "num": m.group(1) if m else "", "date": ep_date.get_text(strip=True) if ep_date else ""})
    return data

def _do_episode(episode_slug):
    soup = _get(f"/{episode_slug}/")
    if not soup: return None
    data = {"episodeId": episode_slug, "title": "", "animeId": "", "episodeNum": "", "prevEpisode": None, "nextEpisode": None, "defaultEmbed": "", "servers": []}
    el = soup.select_one(".entry-title, h1")
    if el: data["title"] = el.get_text(strip=True)
    m = re.match(r"nonton-(.+?)-episode-\d", episode_slug)
    if m: data["animeId"] = m.group(1)
    m = re.search(r"episode[- ](\d+(?:\.\d+)?)", episode_slug, re.I)
    if m: data["episodeNum"] = m.group(1)
    for a in soup.select(".nvs a, .naveps a, .nflx a, .episodenav a"):
        href = a.get("href", "")
        text = a.get_text(strip=True).lower()
        slug_nav = href.rstrip("/").split("/")[-1]
        if any(w in text for w in ["sebelum", "prev", "◄", "←", "«"]): data["prevEpisode"] = slug_nav
        elif any(w in text for w in ["selanjut", "next", "►", "→", "»"]): data["nextEpisode"] = slug_nav
    iframe = soup.select_one("#pembed iframe, #embed_holder iframe")
    if iframe: data["defaultEmbed"] = iframe.get("src", "")
    servers = []
    for opt in soup.select("select option"):
        val = opt.get("value", "").strip()
        label = opt.get_text(strip=True)
        if not val or not label or label == "Pilih Server/Kualitas": continue
        embed_url = _decode_server(val)
        if embed_url: servers.append({"name": label, "embedUrl": embed_url, "type": _detect_server_type(embed_url)})
    if not servers:
        for btn in soup.select(".server a, .mirrorlist a, .btn-eps a"):
            embed_url = btn.get("href") or btn.get("data-src") or btn.get("data-video", "")
            if embed_url: servers.append({"name": btn.get_text(strip=True), "embedUrl": embed_url, "type": _detect_server_type(embed_url)})
    data["servers"] = servers
    return data

# ══════════════════════════════════════════════════════
# DOCS UI
# ══════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════
# SAMEHADAKU SCRAPER FUNCTIONS
# ══════════════════════════════════════════════════════

def _shk_get_cards(soup):
    for sel in [".animposx", ".thumb", ".bsx", ".bs", ".animcon"]:
        cards = soup.select(sel)
        if len(cards) >= 3: return cards
    return []

def _shk_parse_card(card):
    data = {}
    el = card.select_one("h2, h3, .tt, .ntitle, a[title]")
    if el:
        data["title"] = el.get_text(strip=True) or el.get("title", "")
    a = card.select_one("a[href]")
    if a:
        href = a.get("href", "")
        data["url"]     = href
        data["animeId"] = href.rstrip("/").split("/")[-1]
    img = card.select_one("img[src], img[data-src], img[data-lazy-src]")
    if img:
        data["poster"] = img.get("src") or img.get("data-src") or img.get("data-lazy-src") or ""
    el = card.select_one(".epx, .eggepisode, .ep, .l2")
    if el: data["episodes"] = el.get_text(strip=True)
    el = card.select_one(".typez, .type, .etiket")
    if el: data["type"] = el.get_text(strip=True)
    el = card.select_one(".score, .numscore, .rating")
    if el: data["score"] = el.get_text(strip=True)
    return data

def _shk_pagination(soup):
    pag = {"hasNextPage": False, "hasPrevPage": False, "currentPage": 1}
    if soup.select_one(".next.page-numbers, a.next, [rel='next']"): pag["hasNextPage"] = True
    if soup.select_one(".prev.page-numbers, a.prev, [rel='prev']"): pag["hasPrevPage"] = True
    cur = soup.select_one(".page-numbers.current")
    if cur:
        try: pag["currentPage"] = int(cur.get_text(strip=True))
        except: pass
    return pag

def _shk_do_schedule_raw(soup):
    schedule = {}
    days_map = {
        "sunday":"Minggu","monday":"Senin","tuesday":"Selasa",
        "wednesday":"Rabu","thursday":"Kamis","friday":"Jumat","saturday":"Sabtu",
        "minggu":"Minggu","senin":"Senin","selasa":"Selasa",
        "rabu":"Rabu","kamis":"Kamis","jumat":"Jumat","sabtu":"Sabtu",
    }
    for day_el in soup.select(".schedulelist, .schedule .day, .jadwal-hari, .scheduleday"):
        day_name_el = day_el.select_one("h2, h3, .day-name, strong, .title")
        if not day_name_el: continue
        raw      = day_name_el.get_text(strip=True).lower()
        day_name = days_map.get(raw, raw.title())
        items    = []
        for a in day_el.select("li a, .animepost a, .bs a"):
            items.append({"title": a.get_text(strip=True), "animeId": a["href"].rstrip("/").split("/")[-1], "url": a["href"]})
        if items: schedule[day_name] = items
    return schedule

def _shk_do_home():
    soup = _get_shk("/")
    if not soup: return None
    cards = _shk_get_cards(soup)
    return {"animeList": [r for r in [_shk_parse_card(c) for c in cards] if r.get("title")]}

def _shk_do_list(status, page):
    url_map = {
        "movie":   f"/anime/?type=movie&page={page}",
        "popular": f"/anime/?order=popular&page={page}",
    }
    url = url_map.get(status, f"/anime/?status={status}&page={page}")
    soup = _get_shk(url)
    if not soup: return None
    cards = _shk_get_cards(soup)
    result = [r for r in [_shk_parse_card(c) for c in cards] if r.get("title")]
    return {"animeList": result, "pagination": _shk_pagination(soup)}

def _shk_do_search(query, page):
    soup = _get_shk(f"/page/{page}/?s={query}" if page > 1 else f"/?s={query}")
    if not soup: return None
    return {"animeList": [_shk_parse_card(c) for c in _shk_get_cards(soup)], "pagination": _shk_pagination(soup), "query": query}

def _shk_do_detail(slug):
    soup = _get_shk(f"/anime/{slug}/")
    if not soup: return None
    data = {"animeId": slug, "title": "", "poster": "", "synopsis": "", "status": "", "type": "", "score": "", "studio": "", "released": "", "genres": [], "info": {}, "episodeList": []}
    el = soup.select_one(".entry-title, h1.title, h1")
    if el: data["title"] = el.get_text(strip=True)
    el = soup.select_one(".thumb img, .poster img, .wp-post-image")
    if el: data["poster"] = el.get("src") or el.get("data-src", "")
    el = soup.select_one(".entry-content p, .sinopsis p, .desc p")
    if el: data["synopsis"] = el.get_text(strip=True)
    for row in soup.select(".spe span, .infox .spe span"):
        text = row.get_text(" ", strip=True)
        if ":" in text:
            k, _, v = text.partition(":")
            key, val = k.strip().lower(), v.strip()
            data["info"][key] = val
            if "status" in key: data["status"] = val
            if "tipe" in key or "type" in key: data["type"] = val
            if "skor" in key or "score" in key: data["score"] = val
            if "studio" in key: data["studio"] = val
            if "tayang" in key or "rilis" in key: data["released"] = val
    for a in soup.select(".genre-info a, .genxed a, .spe a[href*='genre']"):
        name = a.get_text(strip=True)
        slug_g = a["href"].rstrip("/").split("/")[-1]
        if name and slug_g: data["genres"].append({"name": name, "genreId": slug_g})
    ep_links = soup.select("#daftarepisode li a") or soup.select("ul li a[href*='episode']")
    for a in ep_links:
        ep_slug = a.get("href", "").rstrip("/").split("/")[-1]
        m = re.search(r"episode[- ](\d+(?:\.\d+)?)", ep_slug, re.I)
        li = a.find_parent("li")
        ep_date = li.select_one(".date, .epl-date") if li else None
        data["episodeList"].append({"episodeId": ep_slug, "title": a.get_text(strip=True), "num": m.group(1) if m else "", "date": ep_date.get_text(strip=True) if ep_date else ""})
    return data

def _shk_do_episode(episode_slug):
    soup = _get_shk(f"/{episode_slug}/")
    if not soup: return None
    data = {"episodeId": episode_slug, "title": "", "animeId": "", "episodeNum": "", "prevEpisode": None, "nextEpisode": None, "defaultEmbed": "", "servers": []}
    el = soup.select_one(".entry-title, h1")
    if el: data["title"] = el.get_text(strip=True)
    m = re.match(r"nonton-(.+?)-episode-\d", episode_slug)
    if m: data["animeId"] = m.group(1)
    m = re.search(r"episode[- ](\d+(?:\.\d+)?)", episode_slug, re.I)
    if m: data["episodeNum"] = m.group(1)
    for a in soup.select(".nvs a, .naveps a, .nflx a, .episodenav a"):
        href = a.get("href", "")
        text = a.get_text(strip=True).lower()
        slug_nav = href.rstrip("/").split("/")[-1]
        if any(w in text for w in ["sebelum", "prev", "◄", "←", "«"]): data["prevEpisode"] = slug_nav
        elif any(w in text for w in ["selanjut", "next", "►", "→", "»"]): data["nextEpisode"] = slug_nav
    iframe = soup.select_one("#pembed iframe, #embed_holder iframe")
    if iframe: data["defaultEmbed"] = iframe.get("src", "")
    servers = []
    for opt in soup.select("select option"):
        val = opt.get("value", "").strip()
        label = opt.get_text(strip=True)
        if not val or not label or label == "Pilih Server/Kualitas": continue
        embed_url = _decode_server(val)
        if embed_url: servers.append({"name": label, "embedUrl": embed_url, "type": _detect_server_type(embed_url)})
    if not servers:
        for btn in soup.select(".server a, .mirrorlist a, .btn-eps a"):
            embed_url = btn.get("href") or btn.get("data-src") or btn.get("data-video", "")
            if embed_url: servers.append({"name": btn.get_text(strip=True), "embedUrl": embed_url, "type": _detect_server_type(embed_url)})
    data["servers"] = servers
    # ── AJAX player_ajax (samehadaku/eastplay) ──
    if not data["servers"]:
        options = soup.select(".east_player_option[data-post]")
        if options:
            post_id = options[0].get("data-post", "")
            s_ajax = cloudscraper.create_scraper(browser={"browser": "firefox", "platform": "windows", "mobile": False})
            s_ajax.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
                "Referer": f"{BASE_SHK}/{episode_slug}/",
                "X-Requested-With": "XMLHttpRequest",
            })
            for opt in options:
                nume = opt.get("data-nume", "")
                lbl = opt.select_one("span")
                name = lbl.get_text(strip=True) if lbl else f"Server {nume}"
                try:
                    resp = s_ajax.post(f"{BASE_SHK}/wp-admin/admin-ajax.php",
                        data={"action": "player_ajax", "post": post_id, "nume": nume, "type": "schtml"}, timeout=10)
                    if resp.status_code == 200 and resp.text.strip():
                        iframe_soup = BeautifulSoup(resp.text, "html.parser")
                        iframe = iframe_soup.find("iframe")
                        embed_url = iframe.get("src", "") if iframe else ""
                        if not embed_url:
                            m2 = re.search(r'src=["\'](.*?)["\']', resp.text)
                            embed_url = m2.group(1) if m2 else ""
                        if embed_url:
                            if not data["defaultEmbed"]: data["defaultEmbed"] = embed_url
                            data["servers"].append({"name": name, "embedUrl": embed_url, "type": _detect_server_type(embed_url)})
                except Exception as e:
                    print(f"[shk ep ajax] {name}: {e}")

    return data

# ══════════════════════════════════════════════════════
# DOCS UI
# ══════════════════════════════════════════════════════

def _shk_do_genres():
    VALID = {"action","adventure","comedy","drama","fantasy","horror","mystery","romance",
             "sci-fi","slice-of-life","supernatural","thriller","sports","music","school",
             "shounen","shoujo","seinen","josei","mecha","military","historical","psychological",
             "ecchi","harem","magic","martial-arts","game","demons","parody","police","samurai",
             "space","super-power","vampire","gore","urban-fantasy","teamsports","isekai","team"}
    soup = _get_shk("/")
    if not soup: return None
    genres, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = a.get("href",""); name = a.get_text(strip=True)
        slug = href.rstrip("/").split("/")[-1]
        if name and slug and slug not in seen and "/genre/" in href and slug.lower() in VALID:
            seen.add(slug); genres.append({"name": name, "genreId": slug, "url": href})
    return {"genreList": genres}

def _shk_do_schedule():
    DAYS_MAP = {"monday":"Senin","tuesday":"Selasa","wednesday":"Rabu",
                "thursday":"Kamis","friday":"Jumat","saturday":"Sabtu","sunday":"Minggu"}
    result = []
    s = cloudscraper.create_scraper(browser={"browser":"firefox","platform":"windows","mobile":False})
    s.headers.update({"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
                      "Accept":"application/json","Referer":f"{BASE_SHK}/jadwal-rilis/"})
    for day_en, day_id in DAYS_MAP.items():
        try:
            r = s.get(f"{BASE_SHK}/wp-json/custom/v1/all-schedule?perpage=20&day={day_en}", timeout=15)
            if r.status_code != 200: result.append({"day": day_id, "animeList": []}); continue
            items_raw = r.json()
            if not isinstance(items_raw, list): result.append({"day": day_id, "animeList": []}); continue
            result.append({"day": day_id, "animeList": [{
                "title":   i.get("title",""),   "animeId": i.get("slug",""),
                "url":     i.get("url",""),      "poster":  i.get("featured_img_src",""),
                "score":   i.get("east_score",""), "type":  i.get("east_type",""),
                "time":    i.get("east_time",""), "genre":  i.get("genre",""),
            } for i in items_raw]})
        except Exception as e:
            print(f"[shk schedule] {day_en}: {e}")
            result.append({"day": day_id, "animeList": []})
    return {"days": result}


ENDPOINTS_DOCS = [
    {"title": "Halaman Home", "path": "/anime/home", "description": "Mengambil data homepage — daftar anime ongoing terbaru dan anime populer.", "response": {"status": "success", "data": {"ongoing": [{"animeId": "one-piece", "title": "One Piece", "poster": "https://...", "episodes": "Episode 1122", "type": "TV", "score": "9.1"}], "popular": [], "schedule": {}}}},
    {"title": "Anime Ongoing", "path": "/anime/ongoing?page=1", "description": "Daftar anime yang sedang tayang.", "response": {"status": "success", "data": {"animeList": [{"animeId": "slug", "title": "Judul Anime", "poster": "https://...", "episodes": "Episode 7", "type": "TV", "score": "7.5"}], "pagination": {"hasNextPage": True, "hasPrevPage": False, "currentPage": 1}}}},
    {"title": "Anime Completed", "path": "/anime/completed?page=1", "description": "Daftar anime yang sudah selesai tayang.", "response": {"status": "success", "data": {"animeList": [], "pagination": {"hasNextPage": True, "hasPrevPage": False, "currentPage": 1}}}},
    {"title": "Anime Movie", "path": "/anime/movies?page=1", "description": "Daftar anime dengan tipe Movie.", "response": {"status": "success", "data": {"animeList": [], "pagination": {"hasNextPage": True, "hasPrevPage": False, "currentPage": 1}}}},
    {"title": "Anime Populer", "path": "/anime/popular?page=1", "description": "Daftar anime terpopuler.", "response": {"status": "success", "data": {"animeList": [], "pagination": {"hasNextPage": True, "hasPrevPage": False, "currentPage": 1}}}},
    {"title": "Cari Anime", "path": "/anime/search?q={query}", "description": "Cari anime berdasarkan judul.", "example": "Contoh: /anime/search?q=naruto", "response": {"status": "success", "data": {"query": "naruto", "animeList": [], "pagination": {}}}},
    {"title": "Detail Lengkap Anime", "path": "/anime/detail/{slug}", "description": "Detail lengkap sebuah anime beserta daftar episode.", "example": "Contoh: /anime/detail/naruto", "response": {"status": "success", "data": {"animeId": "naruto", "title": "Naruto", "poster": "https://...", "synopsis": "...", "status": "Completed", "type": "TV", "score": "8.3", "genres": [], "episodeList": []}}},
    {"title": "Detail Episode + Server", "path": "/anime/episode/{slug}", "description": "Detail episode beserta daftar server streaming.", "example": "Contoh: /anime/episode/nonton-naruto-episode-1", "response": {"status": "success", "data": {"episodeId": "nonton-naruto-episode-1", "title": "Nonton Naruto Episode 1", "animeId": "naruto", "episodeNum": "1", "prevEpisode": None, "nextEpisode": "nonton-naruto-episode-2", "defaultEmbed": "https://...", "servers": [{"name": "720p", "embedUrl": "https://...", "type": "vidhide"}]}}},
    {"title": "Daftar Genre", "path": "/anime/genres", "description": "Semua genre anime yang tersedia.", "response": {"status": "success", "data": {"genreList": [{"name": "Action", "genreId": "action"}, {"name": "Comedy", "genreId": "comedy"}]}}},
    {"title": "Jadwal Rilis", "path": "/anime/schedule", "description": "Jadwal rilis anime per hari.", "response": {"status": "success", "data": {"days": [{"day": "Senin", "animeList": []}, {"day": "Selasa", "animeList": []}]}}},
    # ── Samehadaku endpoints ──
    {
        "title": "[SHK] Halaman Home",
        "path": "/shk/anime/home",
        "description": "Mengambil data homepage — daftar anime terbaru beserta jadwal tayang per hari.",
        "response": {
            "status": "success",
            "data": {
                "animeList": [
                    {
                        "animeId": "jigokuraku-season-2",
                        "title": "Jigokuraku Season 2",
                        "poster": "https://v1.samehadaku.how/wp-content/uploads/2026/03/Jigokuraku-21.jpg",
                        "url": "https://v1.samehadaku.how/anime/jigokuraku-season-2/"
                    },
                    {
                        "animeId": "ikoku-nikki",
                        "title": "Ikoku Nikki",
                        "poster": "https://v1.samehadaku.how/wp-content/uploads/2026/03/AkVMvscYWWr.png",
                        "url": "https://v1.samehadaku.how/anime/ikoku-nikki/"
                    }
                ],
                "schedule": []
            }
        }
    },
    {
        "title": "[SHK] Anime Ongoing",
        "path": "/shk/anime/ongoing?page=1",
        "description": "Daftar anime yang sedang tayang. Gunakan parameter `page` untuk navigasi halaman.",
        "response": {
            "status": "success",
            "data": {
                "animeList": [
                    {
                        "animeId": "jujutsu-kaisen-season-3",
                        "title": "Jujutsu Kaisen Season 3",
                        "poster": "https://v1.samehadaku.how/wp-content/uploads/...",
                        "type": "TV",
                        "score": "8.7",
                        "url": "https://v1.samehadaku.how/anime/jujutsu-kaisen-season-3/"
                    }
                ],
                "pagination": {
                    "hasNextPage": True,
                    "hasPrevPage": False,
                    "currentPage": 1
                }
            }
        }
    },
    {
        "title": "[SHK] Anime Completed",
        "path": "/shk/anime/completed?page=1",
        "description": "Daftar anime yang sudah selesai tayang.",
        "response": {
            "status": "success",
            "data": {
                "animeList": [
                    {
                        "animeId": "naruto-kecil",
                        "title": "Naruto Kecil",
                        "poster": "https://v1.samehadaku.how/wp-content/uploads/2024/08/142503.jpg",
                        "type": "TV",
                        "score": "8.84"
                    }
                ],
                "pagination": {
                    "hasNextPage": True,
                    "hasPrevPage": False,
                    "currentPage": 1
                }
            }
        }
    },
    {
        "title": "[SHK] Anime Movie",
        "path": "/shk/anime/movies?page=1",
        "description": "Daftar anime dengan tipe Movie.",
        "response": {
            "status": "success",
            "data": {
                "animeList": [
                    {
                        "animeId": "blue-lock-episode-nagi",
                        "title": "Blue Lock: Episode Nagi",
                        "poster": "https://v1.samehadaku.how/wp-content/uploads/...",
                        "type": "Movie",
                        "score": "7.9"
                    }
                ],
                "pagination": {
                    "hasNextPage": True,
                    "hasPrevPage": False,
                    "currentPage": 1
                }
            }
        }
    },
    {
        "title": "[SHK] Anime Populer",
        "path": "/shk/anime/popular?page=1",
        "description": "Daftar anime terpopuler berdasarkan jumlah penonton.",
        "response": {
            "status": "success",
            "data": {
                "animeList": [
                    {
                        "animeId": "naruto-shippuden",
                        "title": "Naruto: Shippuuden",
                        "poster": "https://v1.samehadaku.how/wp-content/uploads/2020/05/17407.jpg",
                        "type": "TV",
                        "score": "8.15"
                    }
                ],
                "pagination": {
                    "hasNextPage": True,
                    "hasPrevPage": False,
                    "currentPage": 1
                }
            }
        }
    },
    {
        "title": "[SHK] Cari Anime",
        "path": "/shk/anime/search?q={query}",
        "description": "Cari anime berdasarkan judul. Gunakan parameter `q` untuk kata kunci pencarian.",
        "example": "Contoh: /anime/search?q=naruto",
        "response": {
            "status": "success",
            "data": {
                "animeList": [
                    {
                        "animeId": "naruto-kecil",
                        "title": "Naruto Kecil",
                        "poster": "https://v1.samehadaku.how/wp-content/uploads/2024/08/142503.jpg",
                        "score": "8.84",
                        "type": "TV",
                        "url": "https://v1.samehadaku.how/anime/naruto-kecil/"
                    },
                    {
                        "animeId": "naruto-shippuden",
                        "title": "Naruto: Shippuuden",
                        "poster": "https://v1.samehadaku.how/wp-content/uploads/2020/05/17407.jpg",
                        "score": "8.15",
                        "type": "TV",
                        "url": "https://v1.samehadaku.how/anime/naruto-shippuden/"
                    }
                ],
                "pagination": {
                    "hasNextPage": False,
                    "hasPrevPage": False,
                    "currentPage": 1
                }
            }
        }
    },
    {
        "title": "[SHK] Detail Lengkap Anime",
        "path": "/shk/anime/detail/{slug}",
        "description": "Detail lengkap sebuah anime beserta daftar episode. Slug diambil dari field `animeId`.",
        "example": "Contoh: /anime/detail/ikoku-nikki",
        "response": {
            "status": "success",
            "data": {
                "animeId": "ikoku-nikki",
                "title": "Ikoku Nikki Sub Indo",
                "poster": "https://v1.samehadaku.how/wp-content/uploads/2026/01/154233-1.jpg",
                "synopsis": "Novelis berusia 35 tahun, Makio Koudai, tidak pernah memiliki hubungan yang baik dengan kakak perempuannya...",
                "status": "",
                "type": "",
                "score": "",
                "studio": "",
                "info": {
                    "released": "Jan 4, 2026 to ?"
                },
                "genres": [
                    {
                        "name": "Drama",
                        "genreId": "drama"
                    }
                ],
                "episodeList": [
                    {
                        "episodeId": "ikoku-nikki-episode-9",
                        "num": "9",
                        "title": "Ikoku Nikki Episode 9",
                        "date": "2 March 2026"
                    },
                    {
                        "episodeId": "ikoku-nikki-episode-8",
                        "num": "8",
                        "title": "Ikoku Nikki Episode 8",
                        "date": "23 February 2026"
                    }
                ]
            }
        }
    },
    {
        "title": "[SHK] Detail Episode + Server",
        "path": "/shk/anime/episode/{slug}",
        "description": "Detail episode beserta semua server streaming. Server di-fetch via AJAX dari sumber langsung.",
        "example": "Contoh: /anime/episode/ikoku-nikki-episode-9",
        "response": {
            "status": "success",
            "data": {
                "episodeId": "ikoku-nikki-episode-9",
                "title": "Ikoku Nikki Episode 9 Sub Indo",
                "animeId": "ikoku-nikki",
                "episodeNum": "9",
                "prevEpisode": "ikoku-nikki-episode-8",
                "nextEpisode": None,
                "defaultEmbed": "https://www.blogger.com/video.g?token=AD6v5dx...",
                "servers": [
                    {
                        "name": "Blogspot 360p",
                        "embedUrl": "https://www.blogger.com/video.g?token=...",
                        "type": "blogger"
                    },
                    {
                        "name": "Wibufile 480p",
                        "embedUrl": "https://api.wibufile.com/embed/f4154c9e-...",
                        "type": "embed"
                    },
                    {
                        "name": "Wibufile 720p",
                        "embedUrl": "https://s0.wibufile.com/video01/IkoNiki-9-MP4HD.mp4",
                        "type": "mp4"
                    },
                    {
                        "name": "Wibufile 1080p",
                        "embedUrl": "https://s0.wibufile.com/video01/IkoNiki-9-FULLHD.mp4",
                        "type": "mp4"
                    },
                    {
                        "name": "Mega 480p",
                        "embedUrl": "https://mega.nz/embed/u9xARRpA#LCBe...",
                        "type": "mega"
                    },
                    {
                        "name": "Mega 720p",
                        "embedUrl": "https://mega.nz/embed/qqAzxSZK#Cucz...",
                        "type": "mega"
                    },
                    {
                        "name": "Mega 1080p",
                        "embedUrl": "https://mega.nz/embed/294WVJjD#nFq9...",
                        "type": "mega"
                    },
                    {
                        "name": "Pucuk 1080p",
                        "embedUrl": "https://filedon.co/embed/4X6TdLGidf",
                        "type": "embed"
                    }
                ]
            }
        }
    },
    {
        "title": "[SHK] Daftar Genre",
        "path": "/shk/anime/genres",
        "description": "Semua genre anime yang tersedia di sumber.",
        "response": {
            "status": "success",
            "data": {
                "genreList": [
                    {
                        "name": "Action",
                        "genreId": "action",
                        "url": "https://v1.samehadaku.how/genre/action/"
                    },
                    {
                        "name": "Comedy",
                        "genreId": "comedy",
                        "url": "https://v1.samehadaku.how/genre/comedy/"
                    },
                    {
                        "name": "Drama",
                        "genreId": "drama",
                        "url": "https://v1.samehadaku.how/genre/drama/"
                    },
                    {
                        "name": "Fantasy",
                        "genreId": "fantasy",
                        "url": "https://v1.samehadaku.how/genre/fantasy/"
                    },
                    {
                        "name": "Romance",
                        "genreId": "romance",
                        "url": "https://v1.samehadaku.how/genre/romance/"
                    }
                ]
            }
        }
    },
    {
        "title": "[SHK] Jadwal Rilis",
        "path": "/shk/anime/schedule",
        "description": "Jadwal rilis anime per hari dalam seminggu. Data diambil dari REST API sumber langsung.",
        "response": {
            "status": "success",
            "data": {
                "days": [
                    {
                        "day": "Senin",
                        "animeList": [
                            {
                                "title": "Kizoku Tensei",
                                "animeId": "kizoku-tensei-megumareta-umare-kara-saikyou-no-chikara-wo-eru",
                                "url": "https://v1.samehadaku.how/anime/kizoku-tensei-...",
                                "poster": "https://v1.samehadaku.how/wp-content/uploads/2026/01/Kizoku-Tensei.jpg",
                                "score": "6.21",
                                "type": "TV",
                                "time": "01:00",
                                "genre": "Action, Adventure"
                            }
                        ]
                    },
                    {
                        "day": "Selasa",
                        "animeList": [
                            {
                                "title": "Golden Kamuy Final Season",
                                "animeId": "golden-kamuy-final-season",
                                "url": "https://v1.samehadaku.how/anime/golden-kamuy-final-season/",
                                "poster": "https://v1.samehadaku.how/wp-content/uploads/...",
                                "score": "8.1",
                                "type": "TV",
                                "time": "23:00",
                                "genre": "Action, Adventure"
                            }
                        ]
                    },
                    {
                        "day": "Jumat",
                        "animeList": [
                            {
                                "title": "Jujutsu Kaisen Season 3",
                                "animeId": "jujutsu-kaisen-season-3",
                                "url": "https://v1.samehadaku.how/anime/jujutsu-kaisen-season-3/",
                                "poster": "https://v1.samehadaku.how/wp-content/uploads/...",
                                "score": "8.7",
                                "type": "TV",
                                "time": "23:30",
                                "genre": "Action, Fantasy"
                            }
                        ]
                    }
                ]
            }
        }
    },
    # ── Otakudesu endpoints ──
    {
        "title": "[OTK] Halaman Home",
        "path": "/otk/anime/home",
        "description": "Mengambil daftar anime terbaru dari homepage otakudesu.best.",
        "response": {
            "status": "success",
            "data": {
                "animeList": [
                    {
                        "animeId": "goumon-s2-sub-indo",
                        "title": "Himesama \"Goumon\" no Jikan desu Season 2",
                        "poster": "https://otakudesu.best/wp-content/uploads/2026/01/153326.jpg",
                        "url": "https://otakudesu.best/anime/goumon-s2-sub-indo/",
                        "episode": "Episode 8",
                        "type": "TV"
                    }
                ]
            }
        }
    },
    {
        "title": "[OTK] Anime Ongoing",
        "path": "/otk/anime/ongoing?page=1",
        "description": "Daftar anime yang sedang tayang di otakudesu.best.",
        "response": {
            "status": "success",
            "data": {
                "animeList": [
                    {
                        "animeId": "goumon-s2-sub-indo",
                        "title": "Himesama \"Goumon\" no Jikan desu Season 2",
                        "poster": "https://otakudesu.best/wp-content/uploads/2026/01/153326.jpg",
                        "episode": "Episode 8",
                        "type": "TV"
                    }
                ],
                "pagination": {"hasNextPage": True, "hasPrevPage": False, "currentPage": 1}
            }
        }
    },
    {
        "title": "[OTK] Anime Completed",
        "path": "/otk/anime/completed?page=1",
        "description": "Daftar anime yang sudah selesai tayang di otakudesu.best.",
        "response": {
            "status": "success",
            "data": {
                "animeList": [
                    {
                        "animeId": "shingeki-no-kyojin-sub-indo",
                        "title": "Shingeki no Kyojin",
                        "poster": "https://otakudesu.best/wp-content/uploads/...",
                        "type": "TV"
                    }
                ],
                "pagination": {"hasNextPage": True, "hasPrevPage": False, "currentPage": 1}
            }
        }
    },
    {
        "title": "[OTK] Anime Movie",
        "path": "/otk/anime/movies?page=1",
        "description": "Daftar anime Movie di otakudesu.best.",
        "response": {
            "status": "success",
            "data": {
                "animeList": [
                    {
                        "animeId": "kimi-no-na-wa-sub-indo",
                        "title": "Kimi no Na wa.",
                        "poster": "https://otakudesu.best/wp-content/uploads/...",
                        "type": "Movie"
                    }
                ],
                "pagination": {"hasNextPage": True, "hasPrevPage": False, "currentPage": 1}
            }
        }
    },
    {
        "title": "[OTK] Anime Populer",
        "path": "/otk/anime/popular?page=1",
        "description": "Daftar anime terpopuler di otakudesu.best.",
        "response": {
            "status": "success",
            "data": {
                "animeList": [
                    {
                        "animeId": "naruto-sub-indo",
                        "title": "Naruto",
                        "poster": "https://otakudesu.best/wp-content/uploads/...",
                        "type": "TV"
                    }
                ],
                "pagination": {"hasNextPage": True, "hasPrevPage": False, "currentPage": 1}
            }
        }
    },
    {
        "title": "[OTK] Cari Anime",
        "path": "/otk/anime/search?q={query}",
        "description": "Cari anime berdasarkan judul di otakudesu.best.",
        "example": "Contoh: /otk/anime/search?q=naruto",
        "response": {
            "status": "success",
            "data": {
                "query": "naruto",
                "animeList": [
                    {
                        "animeId": "naruto-sub-indo",
                        "title": "Naruto",
                        "poster": "https://otakudesu.best/wp-content/uploads/...",
                        "type": "TV"
                    }
                ],
                "pagination": {"hasNextPage": False, "hasPrevPage": False, "currentPage": 1}
            }
        }
    },
    {
        "title": "[OTK] Detail Lengkap Anime",
        "path": "/otk/anime/detail/{slug}",
        "description": "Detail lengkap anime beserta daftar episode. Slug dari field `animeId`.",
        "example": "Contoh: /otk/anime/detail/goumon-s2-sub-indo",
        "response": {
            "status": "success",
            "data": {
                "animeId": "goumon-s2-sub-indo",
                "title": "Himesama \"Goumon\" no Jikan desu Season 2 Subtitle Indonesia",
                "poster": "https://otakudesu.best/wp-content/uploads/2026/01/153326.jpg",
                "synopsis": "Kelanjutan dari season pertama...",
                "info": {"status": "Ongoing", "studio": "Asahi Production"},
                "genres": [
                    {"name": "Comedy", "genreId": "comedy"},
                    {"name": "Fantasy", "genreId": "fantasy"}
                ],
                "episodeList": [
                    {"episodeId": "hgnjd-s2-episode-8-sub-indo", "num": "8",
                     "title": "Himesama Goumon Season 2 Episode 8", "date": ""},
                    {"episodeId": "hgnjd-s2-episode-7-sub-indo", "num": "7",
                     "title": "Himesama Goumon Season 2 Episode 7", "date": ""}
                ]
            }
        }
    },
    {
        "title": "[OTK] Detail Episode + Server",
        "path": "/otk/anime/episode/{slug}",
        "description": "Detail episode beserta server streaming. Server di-decode dari SELECT base64 (metode Otakudesu).",
        "example": "Contoh: /otk/anime/episode/hgnjd-s2-episode-8-sub-indo",
        "response": {
            "status": "success",
            "data": {
                "episodeId": "hgnjd-s2-episode-8-sub-indo",
                "title": "Himesama Goumon Season 2 Episode 8 Sub Indo",
                "animeId": "goumon-s2-sub-indo",
                "episodeNum": "8",
                "prevEpisode": "hgnjd-s2-episode-7-sub-indo",
                "nextEpisode": None,
                "defaultEmbed": "https://desustream.info/dstream/updesu/v5/index.php?id=...",
                "servers": [
                    {"name": "Desustream 360p",
                     "embedUrl": "https://desustream.info/dstream/updesu/v5/index.php?id=...",
                     "type": "desustream"},
                    {"name": "Desustream 720p",
                     "embedUrl": "https://desustream.info/dstream/updesu/v5/index.php?id=...",
                     "type": "desustream"}
                ]
            }
        }
    },
    {
        "title": "[OTK] Daftar Genre",
        "path": "/otk/anime/genres",
        "description": "Semua genre anime di otakudesu.best (36 genre).",
        "response": {
            "status": "success",
            "data": {
                "genreList": [
                    {"name": "Action",    "genreId": "action",    "url": "https://otakudesu.best/genres/action/"},
                    {"name": "Adventure", "genreId": "adventure", "url": "https://otakudesu.best/genres/adventure/"},
                    {"name": "Comedy",    "genreId": "comedy",    "url": "https://otakudesu.best/genres/comedy/"},
                    {"name": "Drama",     "genreId": "drama",     "url": "https://otakudesu.best/genres/drama/"},
                    {"name": "Fantasy",   "genreId": "fantasy",   "url": "https://otakudesu.best/genres/fantasy/"}
                ]
            }
        }
    },
    {
        "title": "[OTK] Jadwal Rilis",
        "path": "/otk/anime/schedule",
        "description": "Jadwal rilis anime per hari dari /jadwal-rilis/ otakudesu.best.",
        "response": {
            "status": "success",
            "data": {
                "days": [
                    {
                        "day": "Senin",
                        "animeList": [
                            {"title": "Goumon Baito-kun no Nichijou",
                             "animeId": "goumon-baito-sub-indo",
                             "url": "https://otakudesu.best/anime/goumon-baito-sub-indo/",
                             "poster": "https://otakudesu.best/wp-content/uploads/2026/01/153380.jpg"}
                        ]
                    },
                    {
                        "day": "Minggu",
                        "animeList": [
                            {"title": "Ao no Orchestra Season 2",
                             "animeId": "orchestra-s2-sub-indo",
                             "url": "https://otakudesu.best/anime/orchestra-s2-sub-indo/",
                             "poster": "https://otakudesu.best/wp-content/uploads/2025/10/151796.jpg"}
                        ]
                    }
                ]
            }
        }
    },
]
def highlight_json(value):
    text = _json.dumps(value, indent=2, ensure_ascii=False)
    def rep(m):
        t = m.group(0)
        safe = t.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')
        if re.match(r'^"[^"]*"(?=\s*:)', t): return f'<span class="jk">{safe}</span>'
        if re.match(r'^"', t):               return f'<span class="js">{safe}</span>'
        if re.match(r'^-?\d', t):            return f'<span class="jn">{safe}</span>'
        if t in ('true','false'):            return f'<span class="jb">{safe}</span>'
        if t == 'null':                      return f'<span class="jl">{safe}</span>'
        return safe
    return re.sub(r'"(?:[^"\\]|\\.)*"(?=\s*:)|"(?:[^"\\]|\\.)*"|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|true|false|null', rep, text)

HTML = '''<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dayynime API</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=Fira+Code:wght@400;500&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#0f1923;--bg2:#152030;--bg3:#1a2840;--card:#162035;--card2:#1e2d45;
  --border:rgba(255,255,255,0.07);--border2:rgba(255,255,255,0.13);
  --accent:#e8501a;--accent2:#ff6b35;--blue:#38bdf8;--green:#4ade80;
  --text:#e2eaf4;--text2:#8ba0b8;--text3:#4d6278;
  --sans:'Plus Jakarta Sans',sans-serif;--mono:'Fira Code',monospace;
}
html{scroll-behavior:smooth}
body{background:var(--bg);color:var(--text);font-family:var(--sans);min-height:100vh;line-height:1.6}
.header{background:linear-gradient(180deg,var(--bg2) 0%,var(--bg) 100%);border-bottom:1px solid var(--border);padding:48px 24px 40px;text-align:center;position:relative;overflow:hidden}
.header::before{content:'';position:absolute;top:-60px;left:50%;transform:translateX(-50%);width:600px;height:300px;background:radial-gradient(ellipse,rgba(232,80,26,0.12) 0%,transparent 70%);pointer-events:none}
.header-badge{display:inline-flex;align-items:center;gap:6px;background:rgba(232,80,26,0.12);border:1px solid rgba(232,80,26,0.25);border-radius:99px;padding:4px 14px;font-family:var(--mono);font-size:11px;color:var(--accent2);margin-bottom:20px;letter-spacing:0.5px}
.badge-dot{width:6px;height:6px;border-radius:50%;background:var(--accent2);animation:blink 1.5s ease-in-out infinite}
@keyframes blink{0%,100%{opacity:1}50%{opacity:0.3}}
.header-logo{font-size:clamp(28px,6vw,44px);font-weight:800;letter-spacing:-1px;margin-bottom:10px}
.header-logo .d{color:var(--accent)}
.header-logo .api{font-family:var(--mono);font-size:0.55em;font-weight:500;color:var(--text2);vertical-align:middle;margin-left:4px;background:var(--bg3);border:1px solid var(--border2);padding:2px 10px;border-radius:6px;letter-spacing:2px}
.header-desc{color:var(--text2);font-size:15px;max-width:480px;margin:0 auto 28px}
.base-url{display:inline-flex;align-items:center;gap:12px;background:var(--bg3);border:1px solid var(--border2);border-radius:10px;padding:10px 20px;font-family:var(--mono);font-size:13px}
.base-url-label{color:var(--text3);font-size:10px;letter-spacing:2px;text-transform:uppercase}
.base-url-val{color:var(--blue)}
.header-stats{display:flex;justify-content:center;gap:32px;margin-top:24px;flex-wrap:wrap}
.stat{font-size:13px;color:var(--text3)}
.stat strong{color:var(--text);font-weight:700;margin-right:4px}
.main{max-width:780px;margin:0 auto;padding:32px 20px 80px}
.section-header{display:flex;align-items:center;gap:12px;margin-bottom:20px}
.section-icon{font-size:22px}
.section-title{font-size:20px;font-weight:800;color:var(--text)}
.section-line{flex:1;height:2px;background:linear-gradient(to right,var(--accent),transparent)}
.section-header.shk .section-line{background:linear-gradient(to right,var(--blue),transparent)}
.section-header.shk .section-title{color:var(--blue)}
.ep-card.shk{border-left-color:var(--blue)}
.ep-card.shk:hover{border-color:rgba(56,189,248,0.4)}
.ep-card.shk .method-pill{background:rgba(56,189,248,0.1);color:var(--blue);border-color:rgba(56,189,248,0.2)}
.section-header.otk .section-line{background:linear-gradient(to right,#f59e0b,transparent)}
.section-header.otk .section-title{color:#f59e0b}
.ep-card.otk{border-left-color:#f59e0b}
.ep-card.otk:hover{border-color:rgba(245,158,11,0.4)}
.ep-card.otk .method-pill{background:rgba(245,158,11,0.1);color:#f59e0b;border-color:rgba(245,158,11,0.2)}
.section-gap{margin-top:36px}
.ep-card{background:var(--card);border:1px solid var(--border);border-left:3px solid var(--accent);border-radius:12px;margin-bottom:14px;overflow:hidden;transition:border-color 0.2s,box-shadow 0.2s}
.ep-card:hover{border-color:rgba(232,80,26,0.4);box-shadow:0 4px 24px rgba(0,0,0,0.3)}
.ep-header{display:flex;align-items:center;gap:12px;padding:16px 20px;cursor:pointer;user-select:none}
.ep-header:hover{background:rgba(255,255,255,0.02)}
.method-pill{font-family:var(--mono);font-size:10px;font-weight:600;padding:3px 10px;border-radius:6px;flex-shrink:0;letter-spacing:1px;background:rgba(74,222,128,0.1);color:var(--green);border:1px solid rgba(74,222,128,0.2)}
.ep-title{font-size:15px;font-weight:700;color:var(--text);flex:1}
.chevron{width:18px;height:18px;color:var(--text3);transition:transform 0.25s cubic-bezier(.34,1.56,.64,1);flex-shrink:0}
.ep-card.open .chevron{transform:rotate(180deg)}
.path-box{margin:0 20px;background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:11px 16px;font-family:var(--mono);font-size:13px;color:var(--text2);display:flex;align-items:center;gap:10px}
.path-method{color:var(--green);font-weight:600;margin-right:2px}
.path-static{color:var(--text2)}
.path-param{color:var(--accent2)}
.ep-body{display:none;padding:14px 20px 20px}
.ep-card.open .ep-body{display:block}
.ep-desc{font-size:13px;color:var(--text2);margin-bottom:6px;line-height:1.65}
.ep-example{font-size:12px;color:var(--text3);font-family:var(--mono);margin-bottom:16px}
.ep-example span{color:var(--accent2)}
.json-label-row{display:flex;align-items:center;justify-content:space-between;margin-bottom:8px}
.json-label-text{font-family:var(--mono);font-size:10px;letter-spacing:2px;text-transform:uppercase;color:var(--text3)}
.copy-btn{font-family:var(--mono);font-size:10px;background:var(--bg3);border:1px solid var(--border2);color:var(--text2);border-radius:6px;padding:4px 12px;cursor:pointer;transition:all 0.15s}
.copy-btn:hover{background:var(--card2);color:var(--text)}
.copy-btn.ok{color:var(--green);border-color:rgba(74,222,128,0.3)}
.json-wrap{background:var(--bg);border:1px solid var(--border);border-radius:10px;overflow:hidden}
.json-bar{background:var(--bg3);border-bottom:1px solid var(--border);padding:8px 14px;display:flex;align-items:center;gap:6px}
.dot{width:10px;height:10px;border-radius:50%}
.dot-r{background:#ff5f57}.dot-y{background:#febc2e}.dot-g{background:#28c840}
pre{font-family:var(--mono);font-size:12px;line-height:1.75;padding:16px;overflow-x:auto;color:var(--text)}
pre::-webkit-scrollbar{height:3px}
pre::-webkit-scrollbar-thumb{background:var(--border2);border-radius:99px}
.jk{color:#7dd3fc}.js{color:#86efac}.jn{color:#fbbf24}.jb{color:#f472b6}.jl{color:#94a3b8}
.rl-box{background:rgba(220,38,38,0.07);border:1px solid rgba(220,38,38,0.35);border-left:4px solid #ef4444;border-radius:12px;padding:22px 24px;margin-bottom:28px}
.rl-box-title{font-size:17px;font-weight:900;color:#f87171;margin-bottom:16px;letter-spacing:0.5px}
.rl-row{display:flex;gap:10px;margin-bottom:10px;font-size:14px;line-height:1.6}
.rl-key{color:var(--text3);font-family:var(--mono);font-size:12px;white-space:nowrap;padding-top:2px;min-width:110px}
.rl-val{color:var(--text)}
.rl-val strong{color:#f87171}
.rl-divider{height:1px;background:rgba(220,38,38,0.2);margin:14px 0}
.rl-note{font-size:13px;color:var(--text2);margin-bottom:8px;line-height:1.6}
.rl-roast{margin-top:14px;padding:10px 16px;background:rgba(220,38,38,0.1);border-radius:8px;font-size:13px;font-weight:700;color:#fca5a5;text-align:center;letter-spacing:0.3px}
@media(max-width:480px){.rl-row{flex-direction:column;gap:2px}.rl-key{min-width:unset}}
.footer{text-align:center;padding:32px 20px;border-top:1px solid var(--border);font-family:var(--mono);font-size:11px;color:var(--text3)}
.footer a{color:var(--accent2);text-decoration:none}
@media(max-width:480px){.header{padding:36px 16px 32px}.main{padding:24px 14px 60px}.ep-header{padding:14px 16px}.path-box{margin:0 16px;font-size:12px}.ep-body{padding:12px 16px 18px}}
</style>
</head>
<body>
<div class="header">
  <div class="header-badge"><span class="badge-dot"></span>API ONLINE</div>
  <div class="header-logo"><span class="d">D</span>AYYNIME<span class="api">API</span></div>
  <p class="header-desc">REST API scraper untuk streaming anime sub Indo. Data diambil langsung dari sumber dengan sistem cache.</p>
  <div class="base-url">
    <span class="base-url-label">Base URL</span>
    <span class="base-url-val">https://dayynime-api.vercel.app</span>
  </div>
  <div class="header-stats">
    <div class="stat"><strong>{{ endpoints|length }}</strong>Endpoints</div>
    <div class="stat"><strong>v1.animasu.app</strong>Animasu</div>
    <div class="stat"><strong>v1.samehadaku.how</strong>Samehadaku</div>
    <div class="stat"><strong>otakudesu.best</strong>Otakudesu</div>
    <div class="stat"><strong>Flask</strong>Framework</div>
    <div class="stat"><strong>JSON</strong>Format</div>
  </div>
</div>
<div class="main">
  <!-- Rate Limit Warning Box -->
  <div class="rl-box">
    <div class="rl-box-title">🚨 PERINGATAN RATE LIMIT</div>
    <div class="rl-row"><span class="rl-key">Rate Limit:</span><span class="rl-val">70 permintaan per menit</span></div>
    <div class="rl-row"><span class="rl-key">Pelanggaran:</span><span class="rl-val">Jika Anda melewati batas, Anda akan mendapatkan 3 kali peringatan sebelum <strong>BAN PERMANEN</strong></span></div>
    <div class="rl-divider"></div>
    <div class="rl-note">⚡ Gunakan API dengan bijak dan jangan spamming!</div>
    <div class="rl-note">🛡️ Tujuan Rate Limit: Melindungi server dari serangan Hama DDoS dan aktivitas spammer yang dapat mengganggu layanan untuk pengguna lain.</div>
    <div class="rl-roast">MINIMAL TAU DIRI.. DI KASI AKSES GRATIS MALAH NGELUNJAK</div>
  </div>

  <!-- Animasu Endpoints -->
  <div class="section-header">
    <span class="section-icon">📡</span>
    <span class="section-title">Dayynime API Endpoints</span>
    <div class="section-line"></div>
  </div>
  {% for ep in endpoints_animasu %}
  <div class="ep-card" id="ep{{loop.index}}">
    <div class="ep-header" onclick="toggle(this)">
      <span class="method-pill">GET</span>
      <span class="ep-title">{{ ep.title }}</span>
      <svg class="chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M6 9l6 6 6-6"/></svg>
    </div>
    <div class="path-box">
      <span class="path-method">GET</span>
      {% set parts = ep.path.split('{') %}
      {% if parts|length > 1 %}
        <span class="path-static">{{ parts[0] }}</span><span class="path-param">{{'{{'}}{{ parts[1] }}</span>
      {% else %}
        <span class="path-static">{{ ep.path }}</span>
      {% endif %}
    </div>
    <div class="ep-body">
      <p class="ep-desc">{{ ep.description }}</p>
      {% if ep.example is defined %}<p class="ep-example">📌 <span>{{ ep.example }}</span></p>{% endif %}
      <div class="json-label-row">
        <span class="json-label-text">Response JSON</span>
        <button class="copy-btn" onclick="copyJson(event,this,'pre{{loop.index}}')">Copy</button>
      </div>
      <div class="json-wrap">
        <div class="json-bar"><div class="dot dot-r"></div><div class="dot dot-y"></div><div class="dot dot-g"></div></div>
        <pre id="pre{{loop.index}}">{{ ep.json_html }}</pre>
      </div>
    </div>
  </div>
  {% endfor %}

  <!-- Samehadaku Endpoints -->
  <div class="section-header shk section-gap">
    <span class="section-icon">🌊</span>
    <span class="section-title">Samehadaku API Endpoints</span>
    <div class="section-line"></div>
  </div>
  {% for ep in endpoints_shk %}
  <div class="ep-card shk" id="shk{{loop.index}}">
    <div class="ep-header" onclick="toggle(this)">
      <span class="method-pill">GET</span>
      <span class="ep-title">{{ ep.title }}</span>
      <svg class="chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M6 9l6 6 6-6"/></svg>
    </div>
    <div class="path-box">
      <span class="path-method">GET</span>
      {% set parts = ep.path.split('{') %}
      {% if parts|length > 1 %}
        <span class="path-static">{{ parts[0] }}</span><span class="path-param">{{'{{'}}{{ parts[1] }}</span>
      {% else %}
        <span class="path-static">{{ ep.path }}</span>
      {% endif %}
    </div>
    <div class="ep-body">
      <p class="ep-desc">{{ ep.description }}</p>
      {% if ep.example is defined %}<p class="ep-example">📌 <span>{{ ep.example }}</span></p>{% endif %}
      <div class="json-label-row">
        <span class="json-label-text">Response JSON</span>
        <button class="copy-btn" onclick="copyJson(event,this,'shk_pre{{loop.index}}')">Copy</button>
      </div>
      <div class="json-wrap">
        <div class="json-bar"><div class="dot dot-r"></div><div class="dot dot-y"></div><div class="dot dot-g"></div></div>
        <pre id="shk_pre{{loop.index}}">{{ ep.json_html }}</pre>
      </div>
    </div>
  </div>
  {% endfor %}

  <!-- Otakudesu Endpoints -->
  <div class="section-header otk section-gap">
    <span class="section-icon">🍊</span>
    <span class="section-title">Otakudesu API Endpoints</span>
    <div class="section-line"></div>
  </div>
  {% for ep in endpoints_otk %}
  <div class="ep-card otk" id="otk{{loop.index}}">
    <div class="ep-header" onclick="toggle(this)">
      <span class="method-pill">GET</span>
      <span class="ep-title">{{ ep.title }}</span>
      <svg class="chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M6 9l6 6 6-6"/></svg>
    </div>
    <div class="path-box">
      <span class="path-method">GET</span>
      {% set parts = ep.path.split('{') %}
      {% if parts|length > 1 %}
        <span class="path-static">{{ parts[0] }}</span><span class="path-param">{{'{{'}}{{ parts[1] }}</span>
      {% else %}
        <span class="path-static">{{ ep.path }}</span>
      {% endif %}
    </div>
    <div class="ep-body">
      <p class="ep-desc">{{ ep.description }}</p>
      {% if ep.example is defined %}<p class="ep-example">📌 <span>{{ ep.example }}</span></p>{% endif %}
      <div class="json-label-row">
        <span class="json-label-text">Response JSON</span>
        <button class="copy-btn" onclick="copyJson(event,this,'otk_pre{{loop.index}}')">Copy</button>
      </div>
      <div class="json-wrap">
        <div class="json-bar"><div class="dot dot-r"></div><div class="dot dot-y"></div><div class="dot dot-g"></div></div>
        <pre id="otk_pre{{loop.index}}">{{ ep.json_html }}</pre>
      </div>
    </div>
  </div>
  {% endfor %}
</div>
<div class="footer">Dayynime API v1.0.0 &nbsp;·&nbsp; Source: <a href="https://v1.animasu.app" target="_blank">v1.animasu.app</a> &nbsp;·&nbsp; <a href="https://v1.samehadaku.how" target="_blank">v1.samehadaku.how</a> &nbsp;·&nbsp; <a href="https://otakudesu.best" target="_blank">otakudesu.best</a> &nbsp;·&nbsp; Built with Flask + cloudscraper</div>
<script>
function toggle(header){if(event.target.closest('.copy-btn'))return;header.closest('.ep-card').classList.toggle('open')}
function copyJson(e,btn,id){e.stopPropagation();const text=document.getElementById(id).innerText;navigator.clipboard.writeText(text).then(()=>{btn.textContent='✓ Copied';btn.classList.add('ok');setTimeout(()=>{btn.textContent='Copy';btn.classList.remove('ok')},2000)})}
</script>
</body>
</html>'''

# ══════════════════════════════════════════════════════
# ROUTES
# ══════════════════════════════════════════════════════

@app.route("/")
def index():
    animasu_rendered, shk_rendered, otk_rendered = [], [], []
    for ep in ENDPOINTS_DOCS:
        ep2 = dict(ep)
        ep2["json_html"] = Markup(highlight_json(ep["response"]))
        if ep["title"].startswith("[SHK]"):
            ep2["title"] = ep["title"][6:]
            shk_rendered.append(ep2)
        elif ep["title"].startswith("[OTK]"):
            ep2["title"] = ep["title"][6:]
            otk_rendered.append(ep2)
        else:
            animasu_rendered.append(ep2)
    return render_template_string(HTML,
        endpoints_animasu=animasu_rendered,
        endpoints_shk=shk_rendered,
        endpoints_otk=otk_rendered,
        endpoints=animasu_rendered + shk_rendered + otk_rendered,
    )

@app.route("/anime/home")
def route_home():
    data = _cached("home", "home", _do_home)
    return ok(data) if data else err("Gagal mengambil data home")

@app.route("/anime/ongoing")
def route_ongoing():
    page = request.args.get("page", 1, type=int)
    data = _cached(f"ongoing_{page}", "ongoing", lambda: _do_list("ongoing", page))
    return ok(data) if data else err("Gagal mengambil ongoing")

@app.route("/anime/completed")
def route_completed():
    page = request.args.get("page", 1, type=int)
    data = _cached(f"completed_{page}", "completed", lambda: _do_list("completed", page))
    return ok(data) if data else err("Gagal mengambil completed")

@app.route("/anime/movies")
def route_movies():
    page = request.args.get("page", 1, type=int)
    data = _cached(f"movies_{page}", "movies", lambda: _do_list("movie", page))
    return ok(data) if data else err("Gagal mengambil movies")

@app.route("/anime/popular")
def route_popular():
    page = request.args.get("page", 1, type=int)
    data = _cached(f"popular_{page}", "popular", lambda: _do_list("popular", page))
    return ok(data) if data else err("Gagal mengambil popular")

@app.route("/anime/search")
def route_search():
    query = request.args.get("q", "").strip()
    page  = request.args.get("page", 1, type=int)
    if not query: return err("Parameter 'q' diperlukan", 400)
    data = _do_search(query, page)
    return ok(data) if data else err("Gagal melakukan pencarian")

@app.route("/anime/detail/<slug>")
def route_detail(slug):
    data = _cached(f"detail_{slug}", "detail", lambda: _do_detail(slug))
    return ok(data) if data else err(f"Anime '{slug}' tidak ditemukan", 404)

@app.route("/anime/episode/<path:slug>")
def route_episode(slug):
    data = _cached(f"ep_{slug}", "episode", lambda: _do_episode(slug))
    return ok(data) if data else err(f"Episode '{slug}' tidak ditemukan", 404)

@app.route("/anime/genres")
def route_genres():
    def _do_genres():
        soup = _get("/")
        if not soup: return None
        genres, seen = [], set()
        for sel in [".genre a", ".genres a", "a[href*='/genre/']"]:
            for a in soup.select(sel):
                name = a.get_text(strip=True)
                href = a.get("href", "")
                slug = href.rstrip("/").split("/")[-1]
                if name and slug and slug not in seen:
                    seen.add(slug)
                    genres.append({"name": name, "genreId": slug, "url": href})
            if genres: break
        return {"genreList": genres}
    data = _cached("genres", "genres", _do_genres)
    return ok(data) if data else err("Gagal mengambil genre")

@app.route("/anime/schedule")
def route_schedule():
    def _fetch():
        soup = _get("/")
        if not soup: return None
        sched = _do_schedule_raw(soup)
        return {"days": [{"day": d, "animeList": items} for d, items in sched.items()]}
    data = _cached("schedule", "schedule", _fetch)
    return ok(data) if data else err("Gagal mengambil jadwal")

# ══════════════════════════════════════════════════════
# SAMEHADAKU ROUTES  (/shk/anime/*)
# ══════════════════════════════════════════════════════

@app.route("/shk/anime/home")
def shk_home():
    data = _cached("shk_home", "home", _shk_do_home)
    return ok(data) if data else err("Gagal mengambil home samehadaku")

@app.route("/shk/anime/ongoing")
def shk_ongoing():
    page = request.args.get("page", 1, type=int)
    data = _cached(f"shk_ongoing_{page}", "ongoing", lambda: _shk_do_list("ongoing", page))
    return ok(data) if data else err("Gagal mengambil ongoing samehadaku")

@app.route("/shk/anime/completed")
def shk_completed():
    page = request.args.get("page", 1, type=int)
    data = _cached(f"shk_completed_{page}", "completed", lambda: _shk_do_list("completed", page))
    return ok(data) if data else err("Gagal mengambil completed samehadaku")

@app.route("/shk/anime/movies")
def shk_movies():
    page = request.args.get("page", 1, type=int)
    data = _cached(f"shk_movies_{page}", "movies", lambda: _shk_do_list("movie", page))
    return ok(data) if data else err("Gagal mengambil movies samehadaku")

@app.route("/shk/anime/popular")
def shk_popular():
    page = request.args.get("page", 1, type=int)
    data = _cached(f"shk_popular_{page}", "popular", lambda: _shk_do_list("popular", page))
    return ok(data) if data else err("Gagal mengambil popular samehadaku")

@app.route("/shk/anime/search")
def shk_search():
    q    = request.args.get("q", "").strip()
    page = request.args.get("page", 1, type=int)
    if not q: return err("Parameter 'q' diperlukan", 400)
    data = _shk_do_search(q, page)
    return ok(data) if data else err("Gagal search samehadaku")

@app.route("/shk/anime/detail/<slug>")
def shk_detail(slug):
    data = _cached(f"shk_detail_{slug}", "detail", lambda: _shk_do_detail(slug))
    return ok(data) if data else err(f"Anime '{slug}' tidak ditemukan", 404)

@app.route("/shk/anime/episode/<path:slug>")
def shk_episode(slug):
    data = _cached(f"shk_ep_{slug}", "episode", lambda: _shk_do_episode(slug))
    return ok(data) if data else err(f"Episode '{slug}' tidak ditemukan", 404)

@app.route("/shk/anime/genres")
def shk_genres():
    data = _cached("shk_genres", "genres", _shk_do_genres)
    return ok(data) if data else err("Gagal mengambil genre samehadaku")

@app.route("/shk/anime/schedule")
def shk_schedule():
    data = _cached("shk_schedule", "schedule", _shk_do_schedule)
    return ok(data) if data else err("Gagal mengambil jadwal samehadaku")

@app.route("/health")
def health():
    return jsonify({"status": "ok", "source": BASE_URL})

# ══════════════════════════════════════════════════════
# OTAKUDESU ROUTES  (/otk/anime/*)
# ══════════════════════════════════════════════════════

@app.route("/otk/anime/home")
def otk_home():
    data = _cached("otk_home", "home", _otk_do_home)
    return ok(data) if data else err("Gagal mengambil home otakudesu")

@app.route("/otk/anime/ongoing")
def otk_ongoing():
    page = request.args.get("page", 1, type=int)
    data = _cached(f"otk_ongoing_{page}", "ongoing", lambda: _otk_do_list("/ongoing-anime/", page))
    return ok(data) if data else err("Gagal mengambil ongoing otakudesu")

@app.route("/otk/anime/completed")
def otk_completed():
    page = request.args.get("page", 1, type=int)
    data = _cached(f"otk_completed_{page}", "completed", lambda: _otk_do_list("/complete-anime/", page))
    return ok(data) if data else err("Gagal mengambil completed otakudesu")

@app.route("/otk/anime/movies")
def otk_movies():
    page = request.args.get("page", 1, type=int)
    data = _cached(f"otk_movies_{page}", "movies", lambda: _otk_do_list("/anime-movie/", page))
    return ok(data) if data else err("Gagal mengambil movies otakudesu")

@app.route("/otk/anime/popular")
def otk_popular():
    page = request.args.get("page", 1, type=int)
    data = _cached(f"otk_popular_{page}", "popular", lambda: _otk_do_list("/popular-anime/", page))
    return ok(data) if data else err("Gagal mengambil popular otakudesu")

@app.route("/otk/anime/search")
def otk_search():
    q    = request.args.get("q", "").strip()
    page = request.args.get("page", 1, type=int)
    if not q: return err("Parameter 'q' diperlukan", 400)
    data = _otk_do_search(q, page)
    return ok(data) if data else err("Gagal search otakudesu")

@app.route("/otk/anime/detail/<slug>")
def otk_detail(slug):
    data = _cached(f"otk_detail_{slug}", "detail", lambda: _otk_do_detail(slug))
    return ok(data) if data else err(f"Anime '{slug}' tidak ditemukan", 404)

@app.route("/otk/anime/episode/<path:slug>")
def otk_episode(slug):
    data = _cached(f"otk_ep_{slug}", "episode", lambda: _otk_do_episode(slug))
    return ok(data) if data else err(f"Episode '{slug}' tidak ditemukan", 404)

@app.route("/otk/anime/genres")
def otk_genres():
    data = _cached("otk_genres", "genres", _otk_do_genres)
    return ok(data) if data else err("Gagal mengambil genre otakudesu")

@app.route("/otk/anime/schedule")
def otk_schedule():
    data = _cached("otk_schedule", "schedule", _otk_do_schedule)
    return ok(data) if data else err("Gagal mengambil jadwal otakudesu")

if __name__ == "__main__":
    app.run(debug=True, port=5001)
