"""
app.py — Dayynime API Documentation Website
Tampilan card per endpoint + struktur JSON
"""
from flask import Flask, render_template_string
from markupsafe import Markup
import json as _json, re

app = Flask(__name__)

ENDPOINTS = [
    {
        "title": "Halaman Home",
        "method": "GET",
        "path": "/anime/home",
        "description": "Mengambil data homepage — daftar anime ongoing terbaru dan anime populer.",
        "response": {
            "status": "success",
            "data": {
                "ongoing": [
                    {
                        "animeId": "hikuidori-ushuu-boro-tobi-gumi",
                        "title": "Hikuidori: Ushuu Boro Tobi-gumi",
                        "poster": "https://v1.animasu.app/wp-content/uploads/poster.jpg",
                        "episodes": "Episode 7",
                        "type": "TV",
                        "score": "7.5"
                    }
                ],
                "popular": [
                    {
                        "animeId": "one-piece",
                        "title": "One Piece",
                        "poster": "https://v1.animasu.app/wp-content/uploads/poster.jpg",
                        "episodes": "Episode 1122",
                        "type": "TV",
                        "score": "9.1"
                    }
                ],
                "schedule": {
                    "Senin": [{"title": "Hikuidori", "animeId": "hikuidori", "url": "https://..."}],
                    "Selasa": [{"title": "One Piece", "animeId": "one-piece", "url": "https://..."}]
                }
            }
        }
    },
    {
        "title": "Anime Ongoing",
        "method": "GET",
        "path": "/anime/ongoing?page=1",
        "description": "Daftar anime yang sedang tayang. Gunakan parameter page untuk navigasi halaman.",
        "params": "?page=1",
        "response": {
            "status": "success",
            "data": {
                "animeList": [
                    {
                        "animeId": "hikuidori-ushuu-boro-tobi-gumi",
                        "title": "Hikuidori: Ushuu Boro Tobi-gumi",
                        "poster": "https://v1.animasu.app/wp-content/uploads/poster.jpg",
                        "episodes": "Episode 7",
                        "type": "TV",
                        "score": "7.5"
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
        "title": "Anime Completed",
        "method": "GET",
        "path": "/anime/completed?page=1",
        "description": "Daftar anime yang sudah selesai tayang (completed/tamat).",
        "response": {
            "status": "success",
            "data": {
                "animeList": [
                    {
                        "animeId": "attack-on-titan",
                        "title": "Attack on Titan",
                        "poster": "https://v1.animasu.app/wp-content/uploads/poster.jpg",
                        "episodes": "Episode 87",
                        "type": "TV",
                        "score": "9.0"
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
        "title": "Anime Movie",
        "method": "GET",
        "path": "/anime/movies?page=1",
        "description": "Daftar anime dengan tipe Movie.",
        "response": {
            "status": "success",
            "data": {
                "animeList": [
                    {
                        "animeId": "kimi-no-na-wa",
                        "title": "Kimi no Na wa.",
                        "poster": "https://v1.animasu.app/wp-content/uploads/poster.jpg",
                        "episodes": "1",
                        "type": "Movie",
                        "score": "8.9"
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
        "title": "Anime Populer",
        "method": "GET",
        "path": "/anime/popular?page=1",
        "description": "Daftar anime terpopuler berdasarkan jumlah views.",
        "response": {
            "status": "success",
            "data": {
                "animeList": [
                    {
                        "animeId": "one-piece",
                        "title": "One Piece",
                        "poster": "https://v1.animasu.app/wp-content/uploads/poster.jpg",
                        "episodes": "Episode 1122",
                        "type": "TV",
                        "score": "9.1"
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
        "title": "Cari Anime",
        "method": "GET",
        "path": "/anime/search?q={query}",
        "description": "Cari anime berdasarkan judul. Parameter q wajib diisi.",
        "example": "Contoh: /anime/search?q=naruto",
        "response": {
            "status": "success",
            "data": {
                "query": "naruto",
                "animeList": [
                    {
                        "animeId": "naruto",
                        "title": "Naruto",
                        "poster": "https://v1.animasu.app/wp-content/uploads/poster.jpg",
                        "episodes": "220",
                        "type": "TV",
                        "score": "8.3"
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
        "title": "Detail Lengkap Anime",
        "method": "GET",
        "path": "/anime/detail/{slug}",
        "description": "Mengambil detail lengkap sebuah anime beserta daftar episode.",
        "example": "Contoh: /anime/detail/naruto",
        "response": {
            "status": "success",
            "data": {
                "animeId": "naruto",
                "title": "Naruto",
                "poster": "https://v1.animasu.app/wp-content/uploads/poster.jpg",
                "synopsis": "Naruto Uzumaki adalah seorang ninja muda yang bermimpi...",
                "status": "Completed",
                "type": "TV",
                "score": "8.3",
                "studio": "Pierrot",
                "released": "2002",
                "genres": [
                    {"name": "Action", "genreId": "action"},
                    {"name": "Adventure", "genreId": "adventure"}
                ],
                "episodeList": [
                    {"episodeId": "nonton-naruto-episode-1", "title": "Episode 1", "num": "1", "date": "2002-10-03"},
                    {"episodeId": "nonton-naruto-episode-2", "title": "Episode 2", "num": "2", "date": "2002-10-10"}
                ]
            }
        }
    },
    {
        "title": "Detail Episode + Server",
        "method": "GET",
        "path": "/anime/episode/{slug}",
        "description": "Mengambil detail episode beserta daftar server streaming yang tersedia. Server di-decode dari base64.",
        "example": "Contoh: /anime/episode/nonton-naruto-episode-1",
        "response": {
            "status": "success",
            "data": {
                "episodeId": "nonton-naruto-episode-1",
                "title": "Nonton Naruto Episode 1 Sub Indo",
                "animeId": "naruto",
                "episodeNum": "1",
                "prevEpisode": None,
                "nextEpisode": "nonton-naruto-episode-2",
                "defaultEmbed": "https://www.blogger.com/video.g?token=AD6v5dy...",
                "servers": [
                    {"name": "480p [1]", "embedUrl": "https://www.blogger.com/video.g?token=AD6v5dy...", "type": "blogger"},
                    {"name": "720p [1]", "embedUrl": "https://vidhidepro.com/v/5e8a6jme7m22", "type": "vidhide"},
                    {"name": "720p [2]", "embedUrl": "https://mega.nz/embed/0UVl1Lgb#YEQXg...", "type": "mega"}
                ]
            }
        }
    },
    {
        "title": "Daftar Genre",
        "method": "GET",
        "path": "/anime/genres",
        "description": "Mengambil semua genre anime yang tersedia.",
        "response": {
            "status": "success",
            "data": {
                "genreList": [
                    {"name": "Action", "genreId": "action", "url": "https://v1.animasu.app/genre/action/"},
                    {"name": "Adventure", "genreId": "adventure", "url": "https://v1.animasu.app/genre/adventure/"},
                    {"name": "Comedy", "genreId": "comedy", "url": "https://v1.animasu.app/genre/comedy/"},
                    {"name": "Drama", "genreId": "drama", "url": "https://v1.animasu.app/genre/drama/"},
                    {"name": "Fantasy", "genreId": "fantasy", "url": "https://v1.animasu.app/genre/fantasy/"}
                ]
            }
        }
    },
    {
        "title": "Jadwal Rilis Anime",
        "method": "GET",
        "path": "/anime/schedule",
        "description": "Mengambil jadwal rilis anime per hari dalam seminggu.",
        "response": {
            "status": "success",
            "data": {
                "days": [
                    {
                        "day": "Senin",
                        "animeList": [
                            {"title": "Hikuidori", "animeId": "hikuidori", "url": "https://..."}
                        ]
                    },
                    {
                        "day": "Selasa",
                        "animeList": [
                            {"title": "One Piece", "animeId": "one-piece", "url": "https://..."}
                        ]
                    }
                ]
            }
        }
    },
]

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
  --bg:#0f1923;
  --bg2:#152030;
  --bg3:#1a2840;
  --card:#162035;
  --card2:#1e2d45;
  --border:rgba(255,255,255,0.07);
  --border2:rgba(255,255,255,0.13);
  --accent:#e8501a;
  --accent2:#ff6b35;
  --blue:#38bdf8;
  --green:#4ade80;
  --text:#e2eaf4;
  --text2:#8ba0b8;
  --text3:#4d6278;
  --sans:'Plus Jakarta Sans',sans-serif;
  --mono:'Fira Code',monospace;
}
html{scroll-behavior:smooth}
body{background:var(--bg);color:var(--text);font-family:var(--sans);min-height:100vh;line-height:1.6}

/* ── HEADER ── */
.header{
  background:linear-gradient(180deg,var(--bg2) 0%,var(--bg) 100%);
  border-bottom:1px solid var(--border);
  padding:48px 24px 40px;
  text-align:center;
  position:relative;
  overflow:hidden;
}
.header::before{
  content:'';position:absolute;top:-60px;left:50%;transform:translateX(-50%);
  width:600px;height:300px;
  background:radial-gradient(ellipse,rgba(232,80,26,0.12) 0%,transparent 70%);
  pointer-events:none;
}
.header-badge{
  display:inline-flex;align-items:center;gap:6px;
  background:rgba(232,80,26,0.12);border:1px solid rgba(232,80,26,0.25);
  border-radius:99px;padding:4px 14px;
  font-family:var(--mono);font-size:11px;color:var(--accent2);
  margin-bottom:20px;letter-spacing:0.5px;
}
.badge-dot{width:6px;height:6px;border-radius:50%;background:var(--accent2);animation:blink 1.5s ease-in-out infinite}
@keyframes blink{0%,100%{opacity:1}50%{opacity:0.3}}
.header-logo{
  font-size:clamp(28px,6vw,44px);font-weight:800;
  letter-spacing:-1px;margin-bottom:10px;
}
.header-logo .d{color:var(--accent)}
.header-logo .api{
  font-family:var(--mono);font-size:0.55em;font-weight:500;
  color:var(--text2);vertical-align:middle;margin-left:4px;
  background:var(--bg3);border:1px solid var(--border2);
  padding:2px 10px;border-radius:6px;letter-spacing:2px;
}
.header-desc{color:var(--text2);font-size:15px;max-width:480px;margin:0 auto 28px}
.base-url{
  display:inline-flex;align-items:center;gap:12px;
  background:var(--bg3);border:1px solid var(--border2);
  border-radius:10px;padding:10px 20px;
  font-family:var(--mono);font-size:13px;
}
.base-url-label{color:var(--text3);font-size:10px;letter-spacing:2px;text-transform:uppercase}
.base-url-val{color:var(--blue)}
.header-stats{
  display:flex;justify-content:center;gap:32px;margin-top:24px;flex-wrap:wrap;
}
.stat{font-size:13px;color:var(--text3)}
.stat strong{color:var(--text);font-weight:700;margin-right:4px}

/* ── MAIN ── */
.main{max-width:780px;margin:0 auto;padding:32px 20px 80px}

.section-header{
  display:flex;align-items:center;gap:12px;
  margin-bottom:20px;
}
.section-icon{font-size:22px}
.section-title{font-size:20px;font-weight:800;color:var(--text)}
.section-line{flex:1;height:2px;background:linear-gradient(to right,var(--accent),transparent)}

/* ── CARD ── */
.ep-card{
  background:var(--card);
  border:1px solid var(--border);
  border-left:3px solid var(--accent);
  border-radius:12px;
  margin-bottom:14px;
  overflow:hidden;
  transition:border-color 0.2s,box-shadow 0.2s;
  animation:fadeUp 0.4s ease both;
}
.ep-card:hover{
  border-color:rgba(232,80,26,0.4);
  box-shadow:0 4px 24px rgba(0,0,0,0.3);
}
@keyframes fadeUp{
  from{opacity:0;transform:translateY(16px)}
  to{opacity:1;transform:none}
}
{% for i in range(10) %}
.ep-card:nth-child({{ i+1 }}){animation-delay:{{ i*0.06 }}s}
{% endfor %}

.ep-header{
  display:flex;align-items:center;gap:12px;
  padding:16px 20px;cursor:pointer;
  user-select:none;
}
.ep-header:hover{background:rgba(255,255,255,0.02)}

.method-pill{
  font-family:var(--mono);font-size:10px;font-weight:600;
  padding:3px 10px;border-radius:6px;flex-shrink:0;letter-spacing:1px;
  background:rgba(74,222,128,0.1);color:var(--green);
  border:1px solid rgba(74,222,128,0.2);
}
.ep-title{font-size:15px;font-weight:700;color:var(--text);flex:1}
.chevron{
  width:18px;height:18px;color:var(--text3);
  transition:transform 0.25s cubic-bezier(.34,1.56,.64,1);flex-shrink:0;
}
.ep-card.open .chevron{transform:rotate(180deg)}

/* ── PATH BOX ── */
.path-box{
  margin:0 20px;
  background:var(--bg);border:1px solid var(--border);
  border-radius:8px;padding:11px 16px;
  font-family:var(--mono);font-size:13px;color:var(--text2);
  display:flex;align-items:center;gap:10px;
}
.path-method{color:var(--green);font-weight:600;margin-right:2px}
.path-static{color:var(--text2)}
.path-param{color:var(--accent2)}

/* ── BODY ── */
.ep-body{display:none;padding:14px 20px 20px}
.ep-card.open .ep-body{display:block}

.ep-desc{
  font-size:13px;color:var(--text2);margin-bottom:6px;line-height:1.65;
}
.ep-example{
  font-size:12px;color:var(--text3);font-family:var(--mono);
  margin-bottom:16px;
}
.ep-example span{color:var(--accent2)}

/* ── JSON BLOCK ── */
.json-label-row{
  display:flex;align-items:center;justify-content:space-between;
  margin-bottom:8px;
}
.json-label-text{
  font-family:var(--mono);font-size:10px;letter-spacing:2px;
  text-transform:uppercase;color:var(--text3);
}
.copy-btn{
  font-family:var(--mono);font-size:10px;
  background:var(--bg3);border:1px solid var(--border2);
  color:var(--text2);border-radius:6px;padding:4px 12px;
  cursor:pointer;transition:all 0.15s;
}
.copy-btn:hover{background:var(--card2);color:var(--text)}
.copy-btn.ok{color:var(--green);border-color:rgba(74,222,128,0.3)}

.json-wrap{
  background:var(--bg);border:1px solid var(--border);
  border-radius:10px;overflow:hidden;
}
.json-bar{
  background:var(--bg3);border-bottom:1px solid var(--border);
  padding:8px 14px;display:flex;align-items:center;gap:6px;
}
.dot{width:10px;height:10px;border-radius:50%}
.dot-r{background:#ff5f57}.dot-y{background:#febc2e}.dot-g{background:#28c840}

pre{
  font-family:var(--mono);font-size:12px;line-height:1.75;
  padding:16px;overflow-x:auto;color:var(--text);
}
pre::-webkit-scrollbar{height:3px}
pre::-webkit-scrollbar-thumb{background:var(--border2);border-radius:99px}

.jk{color:#7dd3fc}   /* key */
.js{color:#86efac}   /* string */
.jn{color:#fbbf24}   /* number */
.jb{color:#f472b6}   /* bool */
.jl{color:#94a3b8}   /* null */

/* ── FOOTER ── */
.footer{
  text-align:center;padding:32px 20px;
  border-top:1px solid var(--border);
  font-family:var(--mono);font-size:11px;color:var(--text3);
}
.footer a{color:var(--accent2);text-decoration:none}

/* Mobile */
@media(max-width:480px){
  .header{padding:36px 16px 32px}
  .main{padding:24px 14px 60px}
  .ep-header{padding:14px 16px}
  .path-box{margin:0 16px;font-size:12px}
  .ep-body{padding:12px 16px 18px}
}
</style>
</head>
<body>

<div class="header">
  <div class="header-badge">
    <span class="badge-dot"></span>
    API ONLINE
  </div>
  <div class="header-logo">
    <span class="d">D</span>AYYNIME<span class="api">API</span>
  </div>
  <p class="header-desc">REST API scraper untuk streaming anime sub Indo. Data diambil langsung dari sumber dengan sistem cache.</p>
  <div class="base-url">
    <span class="base-url-label">Base URL</span>
    <span class="base-url-val">https://dayynime-api.vercel.app</span>
  </div>
  <div class="header-stats">
    <div class="stat"><strong>{{ endpoints|length }}</strong>Endpoints</div>
    <div class="stat"><strong>v1.animasu.app</strong>Sumber</div>
    <div class="stat"><strong>Flask</strong>Framework</div>
    <div class="stat"><strong>JSON</strong>Format</div>
  </div>
</div>

<div class="main">

  <div class="section-header">
    <span class="section-icon">📡</span>
    <span class="section-title">Dayynime API Endpoints</span>
    <div class="section-line"></div>
  </div>

  {% for ep in endpoints %}
  <div class="ep-card" id="ep{{loop.index}}">
    <div class="ep-header" onclick="toggle(this)">
      <span class="method-pill">GET</span>
      <span class="ep-title">{{ ep.title }}</span>
      <svg class="chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
        <path d="M6 9l6 6 6-6"/>
      </svg>
    </div>

    <!-- Path box -->
    <div class="path-box">
      <span class="path-method">GET</span>
      {% set parts = ep.path.split('{') %}
      {% if parts|length > 1 %}
        <span class="path-static">{{ parts[0] }}</span><span class="path-param">{{'{'}}{{ parts[1] }}</span>
      {% else %}
        <span class="path-static">{{ ep.path }}</span>
      {% endif %}
    </div>

    <div class="ep-body">
      <p class="ep-desc">{{ ep.description }}</p>
      {% if ep.example is defined %}
      <p class="ep-example">📌 <span>{{ ep.example }}</span></p>
      {% endif %}

      <div class="json-label-row">
        <span class="json-label-text">Response JSON</span>
        <button class="copy-btn" onclick="copyJson(event,this,'pre{{loop.index}}')">Copy</button>
      </div>
      <div class="json-wrap">
        <div class="json-bar">
          <div class="dot dot-r"></div>
          <div class="dot dot-y"></div>
          <div class="dot dot-g"></div>
        </div>
        <pre id="pre{{loop.index}}">{{ ep.json_html }}</pre>
      </div>
    </div>
  </div>
  {% endfor %}

</div>

<div class="footer">
  Dayynime API v1.0.0 &nbsp;·&nbsp; Source: <a href="https://v1.animasu.app" target="_blank">v1.animasu.app</a> &nbsp;·&nbsp; Built with Flask + cloudscraper
</div>

<script>
function toggle(header) {
  if (event.target.closest('.copy-btn')) return;
  header.closest('.ep-card').classList.toggle('open');
}
function copyJson(e, btn, id) {
  e.stopPropagation();
  const text = document.getElementById(id).innerText;
  navigator.clipboard.writeText(text).then(() => {
    btn.textContent = '✓ Copied';
    btn.classList.add('ok');
    setTimeout(() => { btn.textContent = 'Copy'; btn.classList.remove('ok'); }, 2000);
  });
}
</script>
</body>
</html>'''


def highlight_json(value):
    """Convert dict → pretty JSON string dengan syntax highlight HTML."""
    text = _json.dumps(value, indent=2, ensure_ascii=False)
    def rep(m):
        t = m.group(0)
        safe = t.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')
        if re.match(r'^"[^"]*"(?=\s*:)', t):  return f'<span class="jk">{safe}</span>'
        if re.match(r'^"', t):                  return f'<span class="js">{safe}</span>'
        if re.match(r'^-?\d', t):               return f'<span class="jn">{safe}</span>'
        if t in ('true','false'):               return f'<span class="jb">{safe}</span>'
        if t == 'null':                         return f'<span class="jl">{safe}</span>'
        return safe
    highlighted = re.sub(
        r'"(?:[^"\\]|\\.)*"(?=\s*:)|"(?:[^"\\]|\\.)*"|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|true|false|null',
        rep, text
    )
    return Markup(highlighted)

@app.route('/')
def index():
    endpoints_rendered = []
    for ep in ENDPOINTS:
        ep2 = dict(ep)
        ep2['json_html'] = highlight_json(ep['response'])
        endpoints_rendered.append(ep2)
    return render_template_string(HTML, endpoints=endpoints_rendered)

if __name__ == '__main__':
    app.run(debug=True, port=5000)
