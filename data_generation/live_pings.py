"""
Live DriverPings generator for BiteStream (keeps the Workflow 3 map alive).

Seeded pings (mongo_seeder.py) all share one timestamp window, so they leave the map's
freshness window (API: last 30 min) and are deleted by the 2-hour TTL index. This script
simulates drivers on the road: every --interval seconds each driver moves a short distance
and a new GeoJSON ping is inserted with created_at = now. Drivers start near restaurants
(locations from the Menus collection), with a share of them around the demo restaurant, so
the map shows nearby drivers that move between polls.

Runs until stopped (Ctrl+C / docker compose stop). In Docker it runs as the `live-pings`
service; from the host:  .venv/bin/python live_pings.py --interval 5 --drivers 150
"""
import argparse
import math
import os
import random
import signal
import sys
import time
from datetime import datetime, timezone

from pymongo import MongoClient

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # optional: the Docker image has no python-dotenv
    pass

DATABASE_NAME = os.getenv("MONGO_DB", "bitestream")
DRIVER_COUNT = 2000  # driver ids 1..2000, same as mongo_seeder.py

# Hyderabad bounding box (same as mongo_seeder.py / postgres_seeder.py)
LAT_RANGE = (17.25, 17.60)
LON_RANGE = (78.30, 78.60)
DEMO_RESTAURANT = (78.4747, 17.3616)  # [lng, lat] of "Demo Restaurant (Charminar)"

METERS_PER_DEG_LAT = 111_320.0

running = True


def stop(*_):
    global running
    running = False


def offset(lng, lat, meters, bearing):
    """Point `meters` away from (lng, lat) in direction `bearing` (radians)."""
    d_lat = meters * math.cos(bearing) / METERS_PER_DEG_LAT
    d_lng = meters * math.sin(bearing) / (METERS_PER_DEG_LAT * math.cos(math.radians(lat)))
    return lng + d_lng, lat + d_lat


def clamp(lng, lat):
    return min(max(lng, LON_RANGE[0]), LON_RANGE[1]), min(max(lat, LAT_RANGE[0]), LAT_RANGE[1])


def hotspots(db):
    """Restaurant locations from Menus (copied from PostgreSQL by menus_seeder.py)."""
    points = [
        tuple(doc["location"]["coordinates"])
        for doc in db["Menus"].find({"location.coordinates": {"$size": 2}}, {"location": 1})
    ]
    return points or [DEMO_RESTAURANT]


def start_drivers(db, count, demo_share):
    spots = hotspots(db)
    drivers = []
    for driver_id in random.sample(range(1, DRIVER_COUNT + 1), count):
        center = DEMO_RESTAURANT if random.random() < demo_share else random.choice(spots)
        lng, lat = clamp(*offset(*center, random.uniform(0, 3000), random.uniform(0, 2 * math.pi)))
        drivers.append({
            "driver_id": driver_id,
            "lng": lng,
            "lat": lat,
            "bearing": random.uniform(0, 2 * math.pi),
            "active": random.random() < 0.8,
        })
    return drivers, len(spots)


def tick(drivers, step_range):
    now = datetime.now(timezone.utc)
    documents = []
    for d in drivers:
        d["bearing"] += random.uniform(-0.6, 0.6)  # mostly keep heading, like a car on a road
        d["lng"], d["lat"] = clamp(*offset(d["lng"], d["lat"], random.uniform(*step_range), d["bearing"]))
        if random.random() < 0.02:  # occasionally go on / off duty
            d["active"] = not d["active"]
        documents.append({
            "driver_id": d["driver_id"],
            "active": d["active"],
            "location": {"type": "Point", "coordinates": [float(d["lng"]), float(d["lat"])]},
            "created_at": now,
        })
    return documents


def main():
    parser = argparse.ArgumentParser(description="Insert live DriverPings so the map keeps moving.")
    parser.add_argument("--interval", type=float, default=float(os.getenv("LIVE_PINGS_INTERVAL", 5)),
                        help="Seconds between ping rounds (default: 5)")
    parser.add_argument("--drivers", type=int, default=int(os.getenv("LIVE_PINGS_DRIVERS", 150)),
                        help="Number of simulated drivers (default: 150)")
    parser.add_argument("--demo-share", type=float, default=float(os.getenv("LIVE_PINGS_DEMO_SHARE", 0.15)),
                        help="Share of drivers that start around the demo restaurant (default: 0.15)")
    parser.add_argument("--duration", type=float, default=float(os.getenv("LIVE_PINGS_DURATION", 0)),
                        help="Stop after this many seconds (default: 0 = run until stopped)")
    args = parser.parse_args()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017/"), serverSelectionTimeoutMS=5000)
    collection = client[DATABASE_NAME]["DriverPings"]

    # Mongo may still be starting (or not yet seeded): wait instead of crashing.
    while running:
        try:
            client.admin.command("ping")
            break
        except Exception as exc:
            print(f"Waiting for MongoDB: {exc}", flush=True)
            time.sleep(3)

    drivers, spot_count = start_drivers(client[DATABASE_NAME], max(1, args.drivers), args.demo_share)
    step_range = (8.0 * args.interval, 25.0 * args.interval)  # ~30–90 km/h
    print(f"Live pings: {len(drivers)} drivers around {spot_count} restaurants, every {args.interval:g}s "
          f"({len(drivers) * 3600 / args.interval:,.0f} pings/hour; the 2 h TTL removes old ones).", flush=True)

    started, rounds = time.monotonic(), 0
    while running and (not args.duration or time.monotonic() - started < args.duration):
        try:
            collection.insert_many(tick(drivers, step_range), ordered=False)
            rounds += 1
            if rounds == 1 or rounds % 12 == 0:
                print(f"{datetime.now(timezone.utc):%H:%M:%S} UTC  round {rounds}: inserted {len(drivers)} pings", flush=True)
        except Exception as exc:  # keep going if Mongo blips
            print(f"Insert failed, retrying next round: {exc}", flush=True)
        end = time.monotonic() + args.interval
        while running and time.monotonic() < end:
            time.sleep(0.2)

    print(f"Stopped after {rounds} rounds.", flush=True)
    client.close()


if __name__ == "__main__":
    sys.exit(main())
