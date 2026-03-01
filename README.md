# Dayynime API

Flask API scraper untuk animasu.app — sebagai pengganti/alternatif sankavollerei.com

## Struktur Folder

```
dayynime-api/
├── api/
│   └── index.py        ← Flask app utama
├── vercel.json         ← Config deploy Vercel
├── requirements.txt    ← Dependencies
└── README.md
```

## Endpoint

| Method | Endpoint | Deskripsi |
|--------|----------|-----------|
| GET | `/` | Info API |
| GET | `/anime/home` | Homepage (ongoing + popular) |
| GET | `/anime/ongoing?page=1` | Ongoing list |
| GET | `/anime/completed?page=1` | Completed list |
| GET | `/anime/movies?page=1` | Movie list |
| GET | `/anime/popular?page=1` | Popular list |
| GET | `/anime/search?q=naruto` | Search anime |
| GET | `/anime/detail/{slug}` | Detail anime + episode list |
| GET | `/anime/episode/{slug}` | Episode detail + server list |
| GET | `/anime/genres` | Daftar genre |
| GET | `/anime/schedule` | Jadwal rilis |

## Format Response

```json
{
  "status": "success",
  "data": { ... }
}
```

## Deploy ke Vercel

```bash
# 1. Install Vercel CLI
npm install -g vercel

# 2. Login
vercel login

# 3. Deploy production
vercel --prod
```

## Pakai di animeku.id (app.py)

```python
# Ganti API_BASE di app.py
API_BASE = "https://dayynime-api.vercel.app"
```

## Run Lokal

```bash
pip install -r requirements.txt
python api/index.py
# → http://localhost:5001
```
