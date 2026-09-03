#!/usr/bin/env python3
"""
CFB ANALYTICS — Weather Engine v1

Builds:
    data/game_conditions.json

Goals:
- Fetch real kickoff-hour forecast data from Open-Meteo.
- Treat indoor venues as Weather Neutral.
- Apply additive TOTAL adjustments from wind + precipitation + temperature.
- Cap weather TOTAL adjustment at -6.0 points.
- Preserve Model A spread and base total unchanged in the audit trail.
- Unlock directional SPREAD weather adjustment only when BOTH offenses have:
    * 100+ current-2026 offensive plays
    * non-zero EPA/pass
    * non-zero EPA/rush
- Require a meaningful pass-lean gap (0.15 EPA) for directional movement.
- Cap spread weather adjustment at +/-1.5 points.

Important:
This is a separate situational overlay. It does not edit data/projections.json,
Model A ratings, HFA, or the production projection builder.
"""

from __future__ import annotations

import json
import math
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECTIONS_PATH = ROOT / "data" / "projections.json"
METRICS_PATH = ROOT / "data" / "cfb_metrics.json"
OUTPUT_PATH = ROOT / "data" / "game_conditions.json"

USER_AGENT = "cfb-analytics-weather-engine-v1/1.0 (+https://github.com/thecadeharp/cfb-analytics)"
TIMEOUT = 20

# ---------------------------------------------------------------------------
# Weather Engine v1 rules
# ---------------------------------------------------------------------------

TOTAL_CAP = -6.0
SPREAD_CAP = 1.5

MIN_TENDENCY_PLAYS = 100
MIN_PASS_LEAN_GAP = 0.15


def fetch_json(url: str) -> dict:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def finite_number(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def round_tenth(value: float) -> float:
    return round(float(value) + 1e-12, 1)


# ---------------------------------------------------------------------------
# Venue + location
# ---------------------------------------------------------------------------

def espn_venue(game_id: str) -> dict:
    """
    ESPN is used only for venue metadata (indoor / city / state / venue name).
    No model metric comes from ESPN.
    """
    url = (
        "https://site.api.espn.com/apis/site/v2/sports/football/"
        f"college-football/summary?event={urllib.parse.quote(str(game_id))}"
    )
    payload = fetch_json(url)
    competition = ((payload.get("header") or {}).get("competitions") or [{}])[0]
    venue = competition.get("venue") or {}
    address = venue.get("address") or {}

    # Some ESPN payloads expose venue in gameInfo instead.
    game_info_venue = (payload.get("gameInfo") or {}).get("venue") or {}
    game_info_address = game_info_venue.get("address") or {}

    return {
        "name": venue.get("fullName") or game_info_venue.get("fullName"),
        "indoor": (
            venue.get("indoor")
            if venue.get("indoor") is not None
            else game_info_venue.get("indoor")
        ),
        "city": address.get("city") or game_info_address.get("city"),
        "state": address.get("state") or game_info_address.get("state"),
        "country": address.get("country") or game_info_address.get("country"),
    }


def geocode_venue(
    venue_name: str | None,
    city: str | None,
    state: str | None,
    country: str | None,
) -> dict | None:
    """
    Try venue name first so the forecast is as close to the stadium as the
    geocoder permits. Fall back to city/state if the venue name is unresolved.
    """
    attempts = []

    if venue_name:
        attempts.append(", ".join(part for part in [venue_name, city, state, country] if part))
    if city:
        attempts.append(", ".join(part for part in [city, state, country] if part))
        attempts.append(city)

    state_upper = (state or "").upper()
    country_upper = (country or "").upper()

    for query in dict.fromkeys(attempts):
        params = urllib.parse.urlencode({
            "name": query,
            "count": 10,
            "language": "en",
            "format": "json",
        })
        payload = fetch_json(f"https://geocoding-api.open-meteo.com/v1/search?{params}")
        results = payload.get("results") or []
        if not results:
            continue

        def score(result: dict) -> int:
            points = 0
            admin = str(result.get("admin1") or "").upper()
            code = str(result.get("country_code") or "").upper()
            result_country = str(result.get("country") or "").upper()
            result_name = str(result.get("name") or "").upper()

            if venue_name and str(venue_name).upper() in result_name:
                points += 5
            if state_upper and (state_upper == admin or state_upper in admin):
                points += 3
            if country_upper and (country_upper == code or country_upper in result_country):
                points += 2
            return points

        best = max(results, key=score)
        lat = finite_number(best.get("latitude"))
        lon = finite_number(best.get("longitude"))
        if lat is None or lon is None:
            continue

        return {
            "latitude": lat,
            "longitude": lon,
            "resolved_name": best.get("name"),
            "resolved_admin1": best.get("admin1"),
            "resolved_country": best.get("country"),
            "query": query,
        }

    return None


# ---------------------------------------------------------------------------
# Open-Meteo kickoff-hour forecast
# ---------------------------------------------------------------------------

def weather_code_text(code: int | None) -> str:
    if code is None:
        return "Variable"
    if code == 0:
        return "Clear"
    if code in (1, 2):
        return "Partly cloudy"
    if code == 3:
        return "Cloudy"
    if code in (45, 48):
        return "Fog"
    if code in (51, 53, 55, 56, 57):
        return "Drizzle"
    if code in (61, 63, 65, 66, 67, 80, 81, 82):
        return "Rain"
    if code in (71, 73, 75, 77, 85, 86):
        return "Snow"
    if code in (95, 96, 99):
        return "Thunderstorms"
    return "Variable"


def forecast_at(latitude: float, longitude: float, kickoff: datetime) -> dict | None:
    params = urllib.parse.urlencode({
        "latitude": latitude,
        "longitude": longitude,
        "hourly": ",".join([
            "temperature_2m",
            "precipitation_probability",
            "precipitation",
            "rain",
            "snowfall",
            "weather_code",
            "wind_speed_10m",
            "wind_gusts_10m",
        ]),
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "precipitation_unit": "inch",
        "timezone": "UTC",
        "forecast_days": 8,
    })

    payload = fetch_json(f"https://api.open-meteo.com/v1/forecast?{params}")
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    if not times:
        return None

    kickoff_naive = kickoff.astimezone(timezone.utc).replace(tzinfo=None)

    parsed = []
    for value in times:
        try:
            parsed.append(datetime.fromisoformat(value))
        except ValueError:
            parsed.append(None)

    valid = [i for i, value in enumerate(parsed) if value is not None]
    if not valid:
        return None

    idx = min(valid, key=lambda i: abs(parsed[i] - kickoff_naive))
    if abs(parsed[idx] - kickoff_naive) > timedelta(hours=2):
        return None

    def at(field):
        values = hourly.get(field) or []
        return values[idx] if idx < len(values) else None

    raw_code = finite_number(at("weather_code"))
    code = int(raw_code) if raw_code is not None else None

    return {
        "forecast_time_utc": times[idx] + "Z",
        "temperature_f": finite_number(at("temperature_2m")),
        "precip_probability_pct": finite_number(at("precipitation_probability")),
        "precipitation_in": finite_number(at("precipitation")),
        "rain_in": finite_number(at("rain")),
        "snowfall_in": finite_number(at("snowfall")),
        "wind_mph": finite_number(at("wind_speed_10m")),
        "wind_gust_mph": finite_number(at("wind_gusts_10m")),
        "weather_code": code,
        "summary": weather_code_text(code),
    }


# ---------------------------------------------------------------------------
# Weather classification
# ---------------------------------------------------------------------------

def wind_total_adjustment(wind_mph: float | None) -> float:
    if wind_mph is None or wind_mph < 10:
        return 0.0
    if wind_mph < 15:
        return -0.5
    if wind_mph < 20:
        return -1.5
    if wind_mph < 25:
        return -2.5
    if wind_mph < 30:
        return -3.5
    return -5.0


def temperature_total_adjustment(temp_f: float | None) -> float:
    if temp_f is None:
        return 0.0
    if temp_f < 25:
        return -2.5
    if temp_f < 35:
        return -1.5
    if temp_f < 50:
        return -0.5
    if temp_f <= 85:
        return 0.0
    if temp_f > 90:
        return -0.5
    return 0.0


def precipitation_class(weather: dict | None) -> str:
    if not weather:
        return "Dry"

    code = weather.get("weather_code")
    rain = weather.get("rain_in")
    snow = weather.get("snowfall_in")
    precip = weather.get("precipitation_in")
    prob = weather.get("precip_probability_pct")

    heavy_snow_codes = {75, 86}
    snow_codes = {71, 73, 75, 77, 85, 86}
    heavy_rain_codes = {65, 67, 82, 95, 96, 99}
    rain_codes = {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82}

    if code in heavy_snow_codes or (snow is not None and snow >= 0.20):
        return "Heavy snow"

    if code in snow_codes or (snow is not None and snow > 0):
        return "Light snow"

    if code in heavy_rain_codes or (rain is not None and rain >= 0.10):
        return "Heavy rain"

    if (
        code in rain_codes
        or (rain is not None and rain > 0)
        or (precip is not None and precip > 0)
        or (prob is not None and prob >= 50 and code not in snow_codes)
    ):
        return "Light rain"

    return "Dry"


def precipitation_total_adjustment(label: str) -> float:
    return {
        "Dry": 0.0,
        "Light rain": -0.5,
        "Heavy rain": -1.5,
        "Light snow": -2.0,
        "Heavy snow": -3.5,
    }.get(label, 0.0)


def spread_weather_magnitude(wind_mph: float | None, precip_label: str) -> float:
    """
    Conservative side rule:
    - 15-19 mph remains TOTAL-only.
    - Directional spread movement starts at 20+ mph.
    - Heavy rain / snow can add directional pressure.
    """
    wind_component = 0.0
    if wind_mph is not None:
        if wind_mph >= 30:
            wind_component = 1.0
        elif wind_mph >= 25:
            wind_component = 0.6
        elif wind_mph >= 20:
            wind_component = 0.4

    precip_component = {
        "Dry": 0.0,
        "Light rain": 0.0,
        "Heavy rain": 0.3,
        "Light snow": 0.5,
        "Heavy snow": 1.0,
    }.get(precip_label, 0.0)

    return min(SPREAD_CAP, round_tenth(wind_component + precip_component))


def conditions_impact(
    total_adjustment: float,
    wind_mph: float | None,
    temp_f: float | None,
    precip_label: str,
) -> str:
    """
    Holistic UX label, not another point adjustment.

    This intentionally makes a dry 20-24 mph game Moderate rather than
    automatically Significant. Combined severe factors can elevate it.
    """
    if (
        total_adjustment <= -3.5
        or (wind_mph is not None and wind_mph >= 25)
        or (temp_f is not None and temp_f < 25)
        or precip_label == "Heavy snow"
    ):
        return "Significant"

    if (
        total_adjustment <= -1.0
        or (wind_mph is not None and wind_mph >= 10)
        or (temp_f is not None and temp_f < 35)
        or precip_label in {"Light rain", "Heavy rain", "Light snow"}
    ):
        return "Moderate"

    return "Minimal"


def condition_note(
    impact: str,
    wind_mph: float | None,
    temp_f: float | None,
    precip_label: str,
) -> str:
    reasons = []

    if wind_mph is not None and wind_mph >= 20:
        reasons.append("Wind may reduce downfield passing efficiency and kicking range")
    elif wind_mph is not None and wind_mph >= 10:
        reasons.append("Wind may modestly suppress passing and kicking efficiency")

    if precip_label == "Heavy rain":
        reasons.append("heavy rain may reduce offensive efficiency and ball security")
    elif precip_label == "Light rain":
        reasons.append("rain may slightly suppress scoring efficiency")
    elif precip_label == "Light snow":
        reasons.append("snow may reduce passing efficiency and footing")
    elif precip_label == "Heavy snow":
        reasons.append("heavy snow may materially suppress passing and overall scoring")

    if temp_f is not None and temp_f < 25:
        reasons.append("extreme cold creates an additional scoring drag")
    elif temp_f is not None and temp_f < 35:
        reasons.append("cold temperatures create an additional scoring drag")

    if not reasons:
        return "No material weather-driven scoring effect is projected."

    note = "; ".join(reasons[:2])
    return note[0].upper() + note[1:] + "."


def conditions_line(indoor: bool, weather: dict | None, precip_label: str) -> str:
    if indoor:
        return "Indoor · Climate controlled · Weather Neutral"

    if not weather:
        return "Forecast unavailable"

    parts = []
    temp = weather.get("temperature_f")
    wind = weather.get("wind_mph")
    gust = weather.get("wind_gust_mph")

    if temp is not None:
        parts.append(f"{round(temp):.0f}°F")

    if wind is not None:
        wind_text = f"{round(wind):.0f} mph wind"
        if gust is not None and gust >= wind + 5:
            wind_text += f" · gusts {round(gust):.0f}"
        parts.append(wind_text)

    parts.append(precip_label)
    return " · ".join(parts)


# ---------------------------------------------------------------------------
# Tendencies + directional spread logic
# ---------------------------------------------------------------------------

def team_live_offense(metrics: dict, team_name: str) -> dict:
    team = (metrics.get("teams") or {}).get(team_name) or {}
    offense = team.get("offense") or {}
    return offense.get("live_2026") or {}


def tendency_snapshot(metrics: dict, team_name: str) -> dict:
    live = team_live_offense(metrics, team_name)

    plays = finite_number(live.get("n_plays")) or 0.0
    epa_pass = finite_number(live.get("epa_pass"))
    epa_rush = finite_number(live.get("epa_rush"))

    nonzero_splits = (
        epa_pass is not None
        and epa_rush is not None
        and abs(epa_pass) > 1e-9
        and abs(epa_rush) > 1e-9
    )

    eligible = plays >= MIN_TENDENCY_PLAYS and nonzero_splits
    pass_lean = (
        round(epa_pass - epa_rush, 4)
        if epa_pass is not None and epa_rush is not None
        else None
    )

    return {
        "team": team_name,
        "plays": int(plays),
        "epa_pass": epa_pass,
        "epa_rush": epa_rush,
        "pass_lean_score": pass_lean,
        "eligible": eligible,
    }


def spread_adjustment(
    metrics: dict,
    home_team: str,
    away_team: str,
    wind_mph: float | None,
    precip_label: str,
) -> dict:
    home = tendency_snapshot(metrics, home_team)
    away = tendency_snapshot(metrics, away_team)

    if not home["eligible"] or not away["eligible"]:
        return {
            "status": "LOCKED",
            "home_spread_points": 0.0,
            "favored_style_team": None,
            "pass_lean_gap": None,
            "reason": (
                f"requires 100+ 2026 offensive plays and non-zero EPA/pass + EPA/rush "
                f"for both teams ({away_team}: {away['plays']} plays; "
                f"{home_team}: {home['plays']} plays)"
            ),
            "home_tendency": home,
            "away_tendency": away,
        }

    magnitude = spread_weather_magnitude(wind_mph, precip_label)

    if magnitude <= 0:
        return {
            "status": "ACTIVE",
            "home_spread_points": 0.0,
            "favored_style_team": None,
            "pass_lean_gap": round_tenth(home["pass_lean_score"] - away["pass_lean_score"]),
            "reason": "tendency data is mature, but conditions do not justify a directional spread adjustment",
            "home_tendency": home,
            "away_tendency": away,
        }

    gap = home["pass_lean_score"] - away["pass_lean_score"]

    if abs(gap) < MIN_PASS_LEAN_GAP:
        return {
            "status": "ACTIVE",
            "home_spread_points": 0.0,
            "favored_style_team": None,
            "pass_lean_gap": round(gap, 3),
            "reason": (
                f"pass-lean gap {gap:+.3f} is below the {MIN_PASS_LEAN_GAP:.2f} EPA threshold"
            ),
            "home_tendency": home,
            "away_tendency": away,
        }

    # Positive home-spread adjustment moves the line toward the away team.
    # Negative home-spread adjustment moves the line toward the home team.
    if gap > 0:
        adjustment = magnitude
        favored_style_team = away_team
    else:
        adjustment = -magnitude
        favored_style_team = home_team

    return {
        "status": "ACTIVE",
        "home_spread_points": max(-SPREAD_CAP, min(SPREAD_CAP, round_tenth(adjustment))),
        "favored_style_team": favored_style_team,
        "pass_lean_gap": round(gap, 3),
        "reason": (
            f"weather favors the less pass-reliant offense; directional magnitude "
            f"is {magnitude:.1f} before the +/-{SPREAD_CAP:.1f} cap"
        ),
        "home_tendency": home,
        "away_tendency": away,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    if not PROJECTIONS_PATH.exists():
        print(f"Missing {PROJECTIONS_PATH}", file=sys.stderr)
        return 1

    if not METRICS_PATH.exists():
        print(f"Missing {METRICS_PATH}", file=sys.stderr)
        return 1

    projections = json.loads(PROJECTIONS_PATH.read_text(encoding="utf-8"))
    metrics = json.loads(METRICS_PATH.read_text(encoding="utf-8"))

    now = datetime.now(timezone.utc)
    window_start = now - timedelta(hours=6)
    window_end = now + timedelta(days=7, hours=18)

    candidates = []
    for game in projections.get("games") or []:
        kickoff = parse_utc(game.get("start_date"))
        if kickoff is None:
            continue
        if not (window_start <= kickoff <= window_end):
            continue
        if str(game.get("status") or "").lower() == "completed":
            continue
        candidates.append((game, kickoff))

    output = {
        "meta": {
            "version": "weather-engine-v1",
            "generated": now.isoformat(),
            "forecast_source": "Open-Meteo",
            "venue_source": "ESPN event venue metadata",
            "total_adjustment_cap": TOTAL_CAP,
            "spread_adjustment_cap": SPREAD_CAP,
            "tendency_min_plays": MIN_TENDENCY_PLAYS,
            "pass_lean_gap_threshold": MIN_PASS_LEAN_GAP,
            "model_a_modified": False,
            "rules": {
                "wind_total": {
                    "0-9": 0.0,
                    "10-14": -0.5,
                    "15-19": -1.5,
                    "20-24": -2.5,
                    "25-29": -3.5,
                    "30+": -5.0,
                },
                "precip_total": {
                    "Dry": 0.0,
                    "Light rain": -0.5,
                    "Heavy rain": -1.5,
                    "Light snow": -2.0,
                    "Heavy snow": -3.5,
                },
                "temperature_total": {
                    "50-85": 0.0,
                    "35-49": -0.5,
                    "25-34": -1.5,
                    "under_25": -2.5,
                    "86-90": 0.0,
                    "over_90": -0.5,
                },
                "spread_note": (
                    "Directional spread adjustment starts at 20+ mph wind or "
                    "heavy rain/snow and only after both teams pass the tendency-data gate."
                ),
            },
        },
        "games": {},
    }

    location_cache = {}

    for game, kickoff in candidates:
        game_id = str(game.get("game_id") or "")
        if not game_id:
            continue

        home_team = (game.get("home") or {}).get("team") or "Home"
        away_team = (game.get("away") or {}).get("team") or "Away"

        baseline_spread = finite_number((game.get("projection") or {}).get("home_spread"))
        baseline_total = finite_number((game.get("projection") or {}).get("total"))

        if baseline_spread is None or baseline_total is None:
            continue

        entry = {
            "game_id": game_id,
            "kickoff_utc": kickoff.isoformat(),
            "venue": game.get("venue"),
            "indoor": False,
            "forecast": None,
            "conditions_line": "Forecast unavailable",
            "impact": "Minimal",
            "note": "Forecast unavailable; Model A baseline remains unchanged.",
            "baseline": {
                "home_spread": baseline_spread,
                "total": baseline_total,
            },
            "adjustments": {
                "breakdown": {
                    "wind": 0.0,
                    "precipitation": 0.0,
                    "temperature": 0.0,
                },
                "raw_total_points": 0.0,
                "total_points": 0.0,
                "home_spread_points": 0.0,
            },
            "adjusted": {
                "home_spread": baseline_spread,
                "total": baseline_total,
            },
            "spread_logic": {
                "status": "LOCKED",
                "reason": "forecast or tendency inputs unavailable",
            },
        }

        try:
            venue = espn_venue(game_id)
            if venue.get("name"):
                entry["venue"] = venue["name"]

            indoor = bool(venue.get("indoor"))
            entry["indoor"] = indoor

            weather = None
            precip_label = "Dry"

            if indoor:
                entry["conditions_line"] = "Indoor · Climate controlled · Weather Neutral"
                entry["impact"] = "Minimal"
                entry["note"] = "Indoor venue; weather adjustment is automatically zero."
            else:
                cache_key = (
                    venue.get("name"),
                    venue.get("city"),
                    venue.get("state"),
                    venue.get("country"),
                )

                if cache_key not in location_cache:
                    location_cache[cache_key] = geocode_venue(*cache_key)
                    time.sleep(0.08)

                location = location_cache.get(cache_key)

                if location:
                    weather = forecast_at(
                        location["latitude"],
                        location["longitude"],
                        kickoff,
                    )

                if weather:
                    precip_label = precipitation_class(weather)

                    wind_adj = wind_total_adjustment(weather.get("wind_mph"))
                    precip_adj = precipitation_total_adjustment(precip_label)
                    temp_adj = temperature_total_adjustment(weather.get("temperature_f"))

                    raw_total = round_tenth(wind_adj + precip_adj + temp_adj)
                    total_adj = max(TOTAL_CAP, raw_total)

                    spread = spread_adjustment(
                        metrics,
                        home_team,
                        away_team,
                        weather.get("wind_mph"),
                        precip_label,
                    )
                    spread_adj = finite_number(spread.get("home_spread_points")) or 0.0

                    entry["forecast"] = {
                        **weather,
                        "precipitation_label": precip_label,
                        "location": location,
                    }
                    entry["conditions_line"] = conditions_line(False, weather, precip_label)
                    entry["impact"] = conditions_impact(
                        total_adj,
                        weather.get("wind_mph"),
                        weather.get("temperature_f"),
                        precip_label,
                    )
                    entry["note"] = condition_note(
                        entry["impact"],
                        weather.get("wind_mph"),
                        weather.get("temperature_f"),
                        precip_label,
                    )
                    entry["adjustments"] = {
                        "breakdown": {
                            "wind": wind_adj,
                            "precipitation": precip_adj,
                            "temperature": temp_adj,
                        },
                        "raw_total_points": raw_total,
                        "total_points": total_adj,
                        "home_spread_points": spread_adj,
                    }
                    entry["adjusted"] = {
                        "home_spread": round_tenth(baseline_spread + spread_adj),
                        "total": round_tenth(baseline_total + total_adj),
                    }
                    entry["spread_logic"] = spread
                else:
                    entry["spread_logic"] = spread_adjustment(
                        metrics,
                        home_team,
                        away_team,
                        None,
                        "Dry",
                    )
                    entry["spread_logic"]["status"] = "LOCKED"
                    entry["spread_logic"]["reason"] = (
                        "forecast unavailable; directional weather adjustment cannot be evaluated"
                    )

        except Exception as exc:
            entry["note"] = f"Weather source unavailable: {type(exc).__name__}; Model A baseline remains unchanged."
            print(f"[WARN] game {game_id}: {exc}", file=sys.stderr)

        output["games"][game_id] = entry
        time.sleep(0.08)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")

    print(f"Wrote {OUTPUT_PATH} with {len(output['games'])} upcoming games.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
