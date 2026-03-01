"""
api/index.py
============
Dayynime API — Flask Scraper siap deploy ke Vercel
Sebagai pengganti / alternatif sankavollerei.com

Endpoint yang tersedia:
  GET /                          → Info API
  GET /anime/home                → Homepage (ongoing + popular)
  GET /anime/ongoing?page=1      → Ongoing list
  GET /anime/completed?page=1    → Completed list
  GET /anime/movies?page=1       → Movie list
  GET /anime/popular?page=1      → Popular list
  GET /anime/search?q=naruto     → Search
  GET /anime/detail/{slug}       → Detail anime + episode list
  GET /anime/episode/{slug}      → Episode detail + server list
  GET /anime/genres              → Genre list
  GET /anime/schedule            → Jadwal rilis

Deploy ke Vercel:
  1. pip install cloudscraper beautifulsoup4 flask
  2. Buat vercel.json (sudah disertakan)
  3. vercel deploy
"""

from flask import Flask, jsonify, request
from bs4 import BeautifulSoup
import cloudscraper, base64, re, json, time, os

app = Flask(__name__)

BASE_URL  = "https://v1.animasu.app"
CACHE     = {}
CACHE_TTL = {
    "home": 300, "ongoing": 180, "completed": 600,
    "movies": 600, "popular": 600, "search": 120,
    "detail": 600, "episode": 180, "genres": 3600,
    "schedule": 1800,
}

# ── Scraper instance ──────────────────────────────────────────
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

# ── Cache helper ──────────────────────────────────────────────
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

# ── Fetch HTML ────────────────────────────────────────────────
def _get(path_or_url):
    url = path_or_url if path_or_url.startswith("http") else BASE_URL + path_or_url
    try:
        s = _scraper()
        r = s.get(url, timeout=15)
        if r.status_code == 200:
            return BeautifulSoup(r.text, "html.parser")
        return None
    except Exception as e:
        print(f"Fetch error [{url}]: {e}")
        return None

# ── Response helper ───────────────────────────────────────────
def ok(data, **kwargs):
    return jsonify({"status": "success", "data": data, **kwargs})

def err(msg, code=500):
    return jsonify({"status": "error", "message": msg}), code

# ══════════════════════════════════════════════════════════════
# SCRAPER FUNCTIONS
# ══════════════════════════════════════════════════════════════

def _parse_card(card):
    data = {}
    el = card.select_one("h2, h3, .tt, .ntitle, a[title]")
    if el:
        data["title"] = el.get_text(strip=True) or el.get("title", "")
    a = card.select_one("a[href]")
    if a:
        href = a.get("href", "")
        data["url"]  = href
        data["slug"] = href.rstrip("/").split("/")[-1]
        # Kalau /anime/{slug}/ → strip "anime" prefix
        if "/anime/" in href:
            data["animeId"] = href.rstrip("/").split("/")[-1]
        else:
            data["animeId"] = href.rstrip("/").split("/")[-1]
    img = card.select_one("img[src], img[data-src], img[data-lazy-src]")
    if img:
        data["poster"] = img.get("src") or img.get("data-src") or img.get("data-lazy-src") or ""
    el = card.select_one(".epx, .eggepisode, .ep, .l2")
    if el:
        data["episodes"] = el.get_text(strip=True)
    el = card.select_one(".typez, .type, .etiket")
    if el:
        data["type"] = el.get_text(strip=True)
    el = card.select_one(".score, .numscore, .rating")
    if el:
        data["score"] = el.get_text(strip=True)
    return data

def _parse_pagination(soup):
    pag = {"hasNextPage": False, "hasPrevPage": False, "currentPage": 1}
    if soup.select_one(".next.page-numbers, a.next, [rel='next']"):
        pag["hasNextPage"] = True
    if soup.select_one(".prev.page-numbers, a.prev, [rel='prev']"):
        pag["hasPrevPage"] = True
    cur = soup.select_one(".page-numbers.current")
    if cur:
        try: pag["currentPage"] = int(cur.get_text(strip=True))
        except: pass
    return pag

def _decode_server(b64_value):
    """Decode base64 option value → embed URL"""
    if not b64_value:
        return ""
    try:
        # Tambah padding
        padded = b64_value + "=" * (4 - len(b64_value) % 4)
        decoded = base64.b64decode(padded).decode("utf-8", errors="ignore")
        # Cari iframe src
        m = re.search(r'src=["\']([^"\']+)["\']', decoded)
        if m:
            return m.group(1)
        if decoded.startswith("http"):
            return decoded.strip()
        return ""
    except:
        return ""

def _do_home():
    soup = _get("/")
    if not soup:
        return None

    # Ongoing / recent
    ongoing = [_parse_card(c) for c in soup.select(".bs") if _parse_card(c).get("title")]

    # Popular (slider / top section)
    popular = []
    for c in soup.select(".popular .bs, .trending .bs, .owl-item .bs"):
        p = _parse_card(c)
        if p.get("title"):
            popular.append(p)

    # Schedule (ambil semua hari)
    schedule = _do_schedule_from_soup(soup)

    return {
        "ongoing": ongoing,
        "popular": popular,
        "schedule": schedule,
    }

def _do_list(status, page):
    if status == "movie":
        url = f"/anime/?type=movie&page={page}"
    elif status == "popular":
        url = f"/anime/?order=popular&page={page}"
    else:
        url = f"/anime/?status={status}&page={page}"

    soup = _get(url)
    if not soup:
        return None

    animes = [_parse_card(c) for c in soup.select(".bs")]
    return {
        "animeList":  animes,
        "pagination": _parse_pagination(soup),
    }

def _do_search(query, page):
    url = f"/page/{page}/?s={query}" if page > 1 else f"/?s={query}"
    soup = _get(url)
    if not soup:
        return None
    return {
        "animeList":  [_parse_card(c) for c in soup.select(".bs")],
        "pagination": _parse_pagination(soup),
        "query":      query,
    }

def _do_detail(slug):
    soup = _get(f"/anime/{slug}/")
    if not soup:
        return None

    data = {
        "animeId":  slug,
        "title":    "",
        "poster":   "",
        "synopsis": "",
        "status":   "",
        "type":     "",
        "score":    "",
        "studio":   "",
        "released": "",
        "genres":   [],
        "info":     {},
        "episodeList": [],
    }

    el = soup.select_one(".entry-title, h1.title, h1")
    if el: data["title"] = el.get_text(strip=True)

    el = soup.select_one(".thumb img, .poster img, .wp-post-image")
    if el: data["poster"] = el.get("src") or el.get("data-src", "")

    el = soup.select_one(".entry-content p, .sinopsis p, .desc p")
    if el: data["synopsis"] = el.get_text(strip=True)

    # Info detail
    for row in soup.select(".spe span, .infox .spe span"):
        text = row.get_text(" ", strip=True)
        if ":" in text:
            k, _, v = text.partition(":")
            key = k.strip().lower()
            val = v.strip()
            data["info"][key] = val
            if "status"  in key: data["status"]   = val
            if "tipe"    in key or "type" in key: data["type"] = val
            if "skor"    in key or "score" in key: data["score"] = val
            if "studio"  in key: data["studio"]   = val
            if "tayang"  in key or "rilis" in key: data["released"] = val

    # Genre
    for a in soup.select(".genre-info a, .genxed a, .spe a[href*='genre'], .spe a"):
        name = a.get_text(strip=True)
        slug_g = a["href"].rstrip("/").split("/")[-1]
        if name and slug_g:
            data["genres"].append({"name": name, "genreId": slug_g})

    # Episode list — selector yang sudah terbukti
    ep_links = (
        soup.select("#daftarepisode li a") or
        soup.select("ul li a[href*='episode']")
    )
    for a in ep_links:
        ep_url  = a.get("href", "")
        ep_slug = ep_url.rstrip("/").split("/")[-1]
        m = re.search(r"episode[- ](\d+(?:\.\d+)?)", ep_slug, re.I)
        ep_num = m.group(1) if m else ""
        li = a.find_parent("li")
        ep_date = li.select_one(".date, .epl-date") if li else None
        data["episodeList"].append({
            "episodeId": ep_slug,
            "title":     a.get_text(strip=True),
            "num":       ep_num,
            "date":      ep_date.get_text(strip=True) if ep_date else "",
        })

    return data

def _do_episode(episode_slug):
    soup = _get(f"/{episode_slug}/")
    if not soup:
        return None

    data = {
        "episodeId":  episode_slug,
        "title":      "",
        "animeId":    "",
        "episodeNum": "",
        "prevEpisode": None,
        "nextEpisode": None,
        "defaultEmbed": "",
        "servers": [],
    }

    el = soup.select_one(".entry-title, h1")
    if el: data["title"] = el.get_text(strip=True)

    # Anime slug dari episode slug
    m = re.match(r"nonton-(.+?)-episode-\d", episode_slug)
    if m: data["animeId"] = m.group(1)

    m = re.search(r"episode[- ](\d+(?:\.\d+)?)", episode_slug, re.I)
    if m: data["episodeNum"] = m.group(1)

    # Prev / Next
    nav_links = soup.select(".nvs a, .naveps a, .nflx a, .episodenav a")
    for a in nav_links:
        href = a.get("href", "")
        text = a.get_text(strip=True).lower()
        slug_nav = href.rstrip("/").split("/")[-1]
        if any(w in text for w in ["sebelum", "prev", "◄", "←", "«"]):
            data["prevEpisode"] = slug_nav
        elif any(w in text for w in ["selanjut", "next", "►", "→", "»"]):
            data["nextEpisode"] = slug_nav

    # Default embed
    iframe = soup.select_one("#pembed iframe, #embed_holder iframe")
    if iframe:
        data["defaultEmbed"] = iframe.get("src", "")

    # Server list dari <select> <option value="BASE64">
    servers = []
    for opt in soup.select("select option"):
        val   = opt.get("value", "").strip()
        label = opt.get_text(strip=True)
        if not val or not label or label == "Pilih Server/Kualitas":
            continue
        embed_url = _decode_server(val)
        if not embed_url:
            continue

        server = {
            "name":     label,
            "embedUrl": embed_url,
            "type":     _detect_server_type(embed_url),
        }
        servers.append(server)

    # Fallback: cari tombol server
    if not servers:
        for btn in soup.select(".server a, .mirrorlist a, .btn-eps a"):
            embed_url = btn.get("href") or btn.get("data-src") or btn.get("data-video", "")
            if embed_url:
                servers.append({
                    "name":     btn.get_text(strip=True),
                    "embedUrl": embed_url,
                    "type":     _detect_server_type(embed_url),
                })

    data["servers"] = servers
    return data

def _detect_server_type(url):
    url_lower = url.lower()
    if "blogger.com" in url_lower:   return "blogger"
    if "mega.nz"     in url_lower:   return "mega"
    if "vidhide"     in url_lower:   return "vidhide"
    if "doodstream"  in url_lower:   return "doodstream"
    if "streamlare"  in url_lower:   return "streamlare"
    if "streamtape"  in url_lower:   return "streamtape"
    if "okru"        in url_lower:   return "ok.ru"
    if "m3u8"        in url_lower:   return "m3u8"
    if "mp4"         in url_lower:   return "mp4"
    return "embed"

def _do_genres():
    soup = _get("/")
    if not soup:
        return None
    genres = []
    seen   = set()
    # Coba berbagai selector genre
    for sel in [".genre a", ".genres a", "a[href*='/genre/']", "a[href*='genres']", ".sub-menu a[href*='genre']"]:
        for a in soup.select(sel):
            name  = a.get_text(strip=True)
            href  = a.get("href", "")
            slug  = href.rstrip("/").split("/")[-1]
            if name and slug and slug not in seen:
                seen.add(slug)
                genres.append({"name": name, "genreId": slug, "url": href})
        if genres:
            break
    return {"genreList": genres}

def _do_schedule_from_soup(soup):
    days_id = {
        "sunday": "Minggu", "monday": "Senin", "tuesday": "Selasa",
        "wednesday": "Rabu", "thursday": "Kamis", "friday": "Jumat",
        "saturday": "Sabtu",
        "minggu": "Minggu", "senin": "Senin", "selasa": "Selasa",
        "rabu": "Rabu", "kamis": "Kamis", "jumat": "Jumat", "sabtu": "Sabtu",
    }
    schedule = {}
    for day_el in soup.select(".schedulelist, .schedule .day, .jadwal-hari, .scheduleday"):
        day_name_el = day_el.select_one("h2, h3, .day-name, strong, .title")
        if not day_name_el:
            continue
        raw_name = day_name_el.get_text(strip=True).lower()
        day_name = days_id.get(raw_name, raw_name.title())
        items = []
        for a in day_el.select("li a, .animepost a, .bs a"):
            items.append({
                "title":   a.get_text(strip=True),
                "animeId": a["href"].rstrip("/").split("/")[-1],
                "url":     a["href"],
            })
        if items:
            schedule[day_name] = items
    return schedule

# ══════════════════════════════════════════════════════════════
# ROUTES
# ══════════════════════════════════════════════════════════════

@app.route("/")
def index():
    return jsonify({
        "name":    "Dayynime API",
        "version": "1.0.0",
        "base":    BASE_URL,
        "endpoints": [
            "GET /anime/home",
            "GET /anime/ongoing?page=1",
            "GET /anime/completed?page=1",
            "GET /anime/movies?page=1",
            "GET /anime/popular?page=1",
            "GET /anime/search?q={query}&page=1",
            "GET /anime/detail/{slug}",
            "GET /anime/episode/{slug}",
            "GET /anime/genres",
            "GET /anime/schedule",
        ]
    })

@app.route("/anime/home")
def route_home():
    data = _cached("home", "home", _do_home)
    if not data:
        return err("Gagal mengambil data home")
    return ok(data)

@app.route("/anime/ongoing")
def route_ongoing():
    page = request.args.get("page", 1, type=int)
    data = _cached(f"ongoing_{page}", "ongoing", lambda: _do_list("ongoing", page))
    if not data:
        return err("Gagal mengambil ongoing")
    return ok(data, pagination=data.get("pagination"))

@app.route("/anime/completed")
def route_completed():
    page = request.args.get("page", 1, type=int)
    data = _cached(f"completed_{page}", "completed", lambda: _do_list("completed", page))
    if not data:
        return err("Gagal mengambil completed")
    return ok(data, pagination=data.get("pagination"))

@app.route("/anime/movies")
def route_movies():
    page = request.args.get("page", 1, type=int)
    data = _cached(f"movies_{page}", "movies", lambda: _do_list("movie", page))
    if not data:
        return err("Gagal mengambil movies")
    return ok(data, pagination=data.get("pagination"))

@app.route("/anime/popular")
def route_popular():
    page = request.args.get("page", 1, type=int)
    data = _cached(f"popular_{page}", "popular", lambda: _do_list("popular", page))
    if not data:
        return err("Gagal mengambil popular")
    return ok(data, pagination=data.get("pagination"))

@app.route("/anime/search")
def route_search():
    query = request.args.get("q", "").strip()
    page  = request.args.get("page", 1, type=int)
    if not query:
        return err("Parameter 'q' diperlukan", 400)
    data = _do_search(query, page)  # search tidak di-cache
    if not data:
        return err("Gagal melakukan pencarian")
    return ok(data)

@app.route("/anime/detail/<slug>")
def route_detail(slug):
    data = _cached(f"detail_{slug}", "detail", lambda: _do_detail(slug))
    if not data:
        return err(f"Anime '{slug}' tidak ditemukan", 404)
    return ok(data)

@app.route("/anime/episode/<path:slug>")
def route_episode(slug):
    data = _cached(f"ep_{slug}", "episode", lambda: _do_episode(slug))
    if not data:
        return err(f"Episode '{slug}' tidak ditemukan", 404)
    return ok(data)

@app.route("/anime/genres")
def route_genres():
    data = _cached("genres", "genres", _do_genres)
    if not data:
        return err("Gagal mengambil genre")
    return ok(data)

@app.route("/anime/schedule")
def route_schedule():
    def _fetch_schedule():
        soup = _get("/")
        if not soup:
            return None
        sched = _do_schedule_from_soup(soup)
        return {"days": [
            {"day": day, "animeList": items}
            for day, items in sched.items()
        ]}
    data = _cached("schedule", "schedule", _fetch_schedule)
    if not data:
        return err("Gagal mengambil jadwal")
    return ok(data)

# Health check
@app.route("/health")
def health():
    return jsonify({"status": "ok", "source": BASE_URL})

if __name__ == "__main__":
    app.run(debug=True, port=5001)
