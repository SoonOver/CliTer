"""Geo Location Tracker — detect location via IP + broadcast to GitHub Gist.

Background service:
1. Detects approximate location using free IP geolocation API (ip-api.com)
2. Stores location history in SQLite
3. Publishes current location to a GitHub Gist (auto-updating)
4. Gist can be embedded in GitHub profile README

Privacy warning: IP-based geolocation is approximate. The gist is PUBLIC.
"""
import json
import time
import asyncio
import httpx
from pathlib import Path
from datetime import datetime, timezone

from cliter.utils.paths import db_path, home_dir
from cliter.config import settings
from cliter.utils.log import get_logger

log = get_logger("geotracker")

GEO_API_URL = "http://ip-api.com/json/"
GEO_FIELDS = "status,message,country,regionName,city,zip,lat,lon,isp,org,as,query"
FALLBACK_API_URL = "https://ipinfo.io/json"

# Gist config
GIST_FILENAME = "cliter-location.html"
GIST_JSON_FILENAME = "cliter-geolocation.json"
GIST_DESCRIPTION = "📍 CliTer Live Map — auto-updated via CliTer Agent"


class GeoLocation:
    """Single location snapshot."""

    def __init__(self, data: dict):
        self.ip = data.get("query", data.get("ip", "?"))
        self.country = data.get("country", "?")
        self.region = data.get("regionName", data.get("region", "?"))
        self.city = data.get("city", "?")
        self.zip = data.get("zip", data.get("postal", ""))
        self.lat = data.get("lat", data.get("latitude", 0))
        self.lon = data.get("lon", data.get("longitude", 0))
        self.isp = data.get("isp", data.get("org", "?"))
        self.timestamp = time.time()
        self.ts_iso = datetime.fromtimestamp(self.timestamp, tz=timezone.utc).isoformat()

    def __str__(self):
        return f"{self.city}, {self.region}, {self.country} ({self.lat:.4f}, {self.lon:.4f})"

    def to_dict(self) -> dict:
        return {
            "timestamp": self.ts_iso,
            "ip": self.ip,
            "country": self.country,
            "region": self.region,
            "city": self.city,
            "latitude": self.lat,
            "longitude": self.lon,
            "isp": self.isp,
        }


class GeoService:
    """Background geo-location tracking + GitHub gist broadcasting."""

    def __init__(self):
        self._task: asyncio.Task | None = None
        self._running = False
        self._current_location: GeoLocation | None = None
        self._gist_id: str | None = None
        self._check_interval = 60  # seconds between checks
        self._gist_update_interval = 1800  # 30 min between gist updates
        self._last_gist_update = 0
        self.db = str(db_path())

    async def _init_db(self):
        """Ensure database table exists."""
        import aiosqlite
        async with aiosqlite.connect(self.db) as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS geo_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL,
                    ip TEXT,
                    country TEXT,
                    region TEXT,
                    city TEXT,
                    latitude REAL,
                    longitude REAL,
                    isp TEXT
                )
            """)
            await conn.commit()

    async def detect_location(self) -> GeoLocation | None:
        """Detect current location using free IP geolocation APIs."""
        # Try primary API
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{GEO_API_URL}?fields={GEO_FIELDS}")
                data = resp.json()
                if data.get("status") == "success":
                    return GeoLocation(data)
        except Exception as e:
            log.warn(f"Primary geo API failed: {e}")

        # Try fallback API
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(FALLBACK_API_URL)
                data = resp.json()
                if data.get("ip"):
                    return GeoLocation(data)
        except Exception as e:
            log.warn(f"Fallback geo API failed: {e}")

        return None

    async def _save_to_db(self, loc: GeoLocation):
        """Save location snapshot to local database."""
        import aiosqlite
        async with aiosqlite.connect(self.db) as conn:
            await conn.execute(
                "INSERT INTO geo_history (timestamp, ip, country, region, city, latitude, longitude, isp) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (loc.timestamp, loc.ip, loc.country, loc.region, loc.city, loc.lat, loc.lon, loc.isp)
            )
            await conn.commit()

    async def get_history(self, limit: int = 20) -> list[dict]:
        """Get location history from database."""
        import aiosqlite
        async with aiosqlite.connect(self.db) as conn:
            conn.row_factory = aiosqlite.Row
            cur = await conn.execute(
                "SELECT * FROM geo_history ORDER BY timestamp DESC LIMIT ?", (limit,)
            )
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def get_last_location(self) -> dict | None:
        """Get the most recent location record."""
        import aiosqlite
        async with aiosqlite.connect(self.db) as conn:
            conn.row_factory = aiosqlite.Row
            cur = await conn.execute(
                "SELECT * FROM geo_history ORDER BY timestamp DESC LIMIT 1"
            )
            row = await cur.fetchone()
            return dict(row) if row else None

    # ── GitHub Gist Publishing ─────────────────

    async def _query_gist_id(self) -> str | None:
        """Find existing gist ID by either HTML or JSON filename."""
        token = settings.get("github", "token", default="")
        if not token:
            return None
        headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get("https://api.github.com/gists", headers=headers)
                gists = resp.json()
                for g in gists:
                    files = g.get("files", {})
                    if GIST_FILENAME in files or GIST_JSON_FILENAME in files:
                        return g["id"]
        except Exception:
            pass
        return None

    async def _update_gist(self, loc: GeoLocation, history: list[dict]) -> str | None:
        """Create or update a GitHub gist with interactive map + JSON data."""
        token = settings.get("github", "token", default="")
        if not token:
            log.warn("No GitHub token configured — gist publish disabled")
            return None

        # Build HTML map
        map_html = self._generate_map_html(loc, history)

        # Build JSON data (secondary file)
        current_data = loc.to_dict()
        json_content = json.dumps({
            "current": current_data,
            "history": history[:50],
            "updated_at": current_data["timestamp"],
            "source": "CliTer Geo Tracker",
        }, indent=2)

        files = {
            GIST_FILENAME: {"content": map_html},
            GIST_JSON_FILENAME: {"content": json_content},
        }
        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
        }

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                if self._gist_id:
                    url = f"https://api.github.com/gists/{self._gist_id}"
                    resp = await client.patch(url, json={"files": files}, headers=headers)
                else:
                    resp = await client.post(
                        "https://api.github.com/gists",
                        json={"description": GIST_DESCRIPTION, "public": True, "files": files},
                        headers=headers,
                    )
                    if resp.status_code == 201:
                        self._gist_id = resp.json().get("id")

                if resp.status_code in (200, 201):
                    data = resp.json()
                    url = data.get("html_url")
                    log.info(f"📍 Map updated: {url}")
                    self._last_gist_update = time.time()
                    return url

        except Exception as e:
            log.warn(f"Gist update failed: {e}")

        return None

    def _generate_map_html(self, loc: GeoLocation, history: list[dict]) -> str:
        """Generate a self-contained HTML page with Leaflet interactive map."""
        lat = loc.lat
        lon = loc.lon
        city = loc.city
        region = loc.region
        country = loc.country
        isp = loc.isp
        ts = loc.ts_iso
        ip = loc.ip

        # Build history markers JS
        history_markers = ""
        for h in history[:20]:
            hlats = h.get("latitude", 0)
            hlons = h.get("longitude", 0)
            hcity = h.get("city", "?")
            hregion = h.get("region", "")
            hcountry = h.get("country", "")
            htime = datetime.fromtimestamp(h.get("timestamp", 0), tz=timezone.utc).isoformat()
            history_markers += f"""
                L.circleMarker([{hlats}, {hlons}], {{
                    radius: 4, color: '#ff6b6b', fillColor: '#ff6b6b', fillOpacity: 0.7,
                    weight: 1
                }}).addTo(map)
                .bindPopup('<b>{hcity}</b>, {hregion}, {hcountry}<br><small>{htime}</small>');
            """

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>CliTer Live Location</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: 'Segoe UI', -apple-system, sans-serif; background: #0d1117; color: #c9d1d9; }}
  #header {{
    position: fixed; top: 0; left: 0; right: 0; z-index: 1000;
    background: linear-gradient(135deg, #0d1117 0%, #161b22 100%);
    border-bottom: 1px solid #30363d;
    padding: 10px 20px;
    display: flex; align-items: center; justify-content: space-between;
  }}
  #header h1 {{ font-size: 18px; font-weight: 600; color: #58a6ff; }}
  #header .info {{ font-size: 12px; color: #8b949e; text-align: right; }}
  #header .info strong {{ color: #c9d1d9; }}
  #map {{ position: fixed; top: 55px; left: 0; right: 0; bottom: 0; }}
  .location-card {{
    position: fixed; bottom: 20px; left: 20px; z-index: 1000;
    background: rgba(13,17,23,0.92);
    border: 1px solid #30363d;
    border-radius: 8px;
    padding: 12px 16px;
    font-size: 13px;
    backdrop-filter: blur(8px);
    min-width: 220px;
  }}
  .location-card .city {{ font-size: 22px; font-weight: 700; color: #f0f6fc; }}
  .location-card .detail {{ color: #8b949e; margin-top: 2px; }}
  .location-card .detail span {{ color: #58a6ff; }}
  .update-btn {{
    position: fixed; bottom: 20px; right: 20px; z-index: 1000;
    background: #238636; color: white; border: none; border-radius: 6px;
    padding: 8px 16px; font-size: 13px; cursor: pointer;
    text-decoration: none;
  }}
  .update-btn:hover {{ background: #2ea043; }}
  @media (max-width: 600px) {{
    #header h1 {{ font-size: 14px; }}
    #header .info {{ font-size: 10px; }}
    .location-card {{ left: 10px; bottom: 10px; padding: 8px 12px; }}
    .location-card .city {{ font-size: 16px; }}
    .update-btn {{ right: 10px; bottom: 10px; font-size: 11px; padding: 6px 12px; }}
  }}
</style>
</head>
<body>
<div id="header">
  <h1>📍 CliTer — Live Location</h1>
  <div class="info">
    <strong>{city}</strong>, {region} &middot; {country}<br>
    <small>Updated: {ts[:19].replace('T', ' ')} UTC</small>
  </div>
</div>
<div id="map"></div>

<div class="location-card">
  <div class="city">{city}</div>
  <div class="detail">{region}, {country}</div>
  <div class="detail">ISP: <span>{isp}</span></div>
  <div class="detail">IP: <span>{ip}</span></div>
  <div class="detail">Lat/Lon: <span>{lat:.4f}, {lon:.4f}</span></div>
  <div class="detail" style="margin-top:4px;font-size:11px;">{ts[:19].replace('T', ' ')} UTC</div>
</div>

<a class="update-btn" href="https://github.com/SoonOver/CliTer" target="_blank">⚡ CliTer</a>

<script>
  var map = L.map('map', {{
    center: [{lat}, {lon}],
    zoom: 6,
    zoomControl: true,
    attributionControl: true,
  }});

  L.tileLayer('https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/">CARTO</a>',
    subdomains: 'abcd',
    maxZoom: 19,
  }}).addTo(map);

  // Current location marker
  var marker = L.marker([{lat}, {lon}], {{
    icon: L.divIcon({{
      className: '',
      html: '<div style="width:24px;height:24px;background:#238636;border:3px solid #fff;border-radius:50%;box-shadow:0 0 12px rgba(35,134,54,0.6);"></div>',
      iconSize: [24, 24],
      iconAnchor: [12, 12],
    }})
  }}).addTo(map);
  marker.bindPopup(`
    <b style="font-size:16px;">📍 {city}</b><br>
    {region}, {country}<br>
    <small>ISP: {isp}<br>{ts[:19].replace('T', ' ')} UTC</small>
  `).openPopup();

  // Pulse animation circle
  L.circleMarker([{lat}, {lon}], {{
    radius: 40, color: '#238636', fillColor: '#238636',
    fillOpacity: 0.1, weight: 2, opacity: 0.3
  }}).addTo(map);

  // History markers
  {history_markers}
</script>
</body>
</html>"""
        return html

    # ── Background Loop ────────────────────────

    async def start(self, interval: int = 60):
        """Start the background geo-tracking loop."""
        await self._init_db()

        if self._running:
            return

        self._check_interval = interval
        self._running = True

        # Try to find existing gist
        self._gist_id = await self._query_gist_id()

        self._task = asyncio.create_task(self._loop())
        log.info("Geo tracker started")

    def stop(self):
        """Stop the background loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None
        log.info("Geo tracker stopped")

    async def _loop(self):
        """Main background loop — detect location + update gist periodically."""
        # Do an immediate check on start
        loc = await self.detect_location()
        if loc:
            self._current_location = loc
            await self._save_to_db(loc)
            log.info(f"Location: {loc}")

        while self._running:
            await asyncio.sleep(self._check_interval)

            # Detect location
            try:
                new_loc = await self.detect_location()
                if new_loc:
                    self._current_location = new_loc
                    await self._save_to_db(new_loc)
                    log.info(f"Location updated: {new_loc}")
            except Exception as e:
                log.warn(f"Location detection failed: {e}")
                continue

            # Update gist periodically
            if time.time() - self._last_gist_update > self._gist_update_interval:
                try:
                    history = await self.get_history(limit=50)
                    gist_url = await self._update_gist(new_loc, history)
                    if gist_url:
                        log.info(f"📍 Broadcast: {gist_url}")
                except Exception as e:
                    log.warn(f"Gist update failed: {e}")

    @property
    def status(self) -> dict:
        return {
            "running": self._running,
            "last_location": str(self._current_location) if self._current_location else None,
            "gist_id": self._gist_id,
            "check_interval": self._check_interval,
            "last_gist_update": self._last_gist_update,
        }

    async def force_update(self) -> str | None:
        """Force immediate location check + gist update."""
        await self._init_db()
        loc = await self.detect_location()
        if not loc:
            return None
        self._current_location = loc
        await self._save_to_db(loc)
        history = await self.get_history(limit=50)
        gist_url = await self._update_gist(loc, history)
        return gist_url or str(loc)


# Global singleton
_service: GeoService | None = None


def get_service() -> GeoService:
    global _service
    if _service is None:
        _service = GeoService()
    return _service
