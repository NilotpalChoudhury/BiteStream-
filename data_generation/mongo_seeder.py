"""
MongoDB seeder for BiteStream DriverPings (Workflow 3: nearest active driver).

Pings are timestamped within the last few minutes so none of them is already past the
2-hour TTL (idx_driverPings_created_at_ttl) when inserted. They cover the same Hyderabad
area as the restaurants seeded by postgres_seeder.py. Run mongo/01_collections_and_indexes.js
first. Re-run this script to get fresh pings (they all expire ~2 h after seeding).
"""
from datetime import datetime, timedelta, timezone
import random
from faker import Faker
from pymongo import MongoClient
import os
from dotenv import load_dotenv
load_dotenv()

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
DATABASE_NAME = "bitestream"
TOTAL_RECORDS = 510000
BATCH_SIZE = 5000
DRIVER_COUNT = 2000
SEED = 42

# Hyderabad bounding box (contains every restaurant from postgres_seeder.py)
LAT_RANGE = (17.25, 17.60)
LON_RANGE = (78.30, 78.60)

random.seed(SEED)
Faker.seed(SEED)
fake = Faker()

client = MongoClient(MONGO_URI)
db = client[DATABASE_NAME]
collection = db["DriverPings"]

collection.delete_many({})
batch = []
now = datetime.now(timezone.utc)

for i in range(1, TOTAL_RECORDS + 1):
    latitude = random.uniform(*LAT_RANGE)
    longitude = random.uniform(*LON_RANGE)

    document = {
        "driver_id": fake.random_int(min=1, max=DRIVER_COUNT),
        "active": random.random() < 0.75,
        "location": {
            "type": "Point",
            "coordinates": [longitude, latitude]
        },
        "created_at": now - timedelta(seconds=random.uniform(0, 600))
    }

    batch.append(document)

    if len(batch) == BATCH_SIZE:
        collection.insert_many(batch)
        if i % 50000 == 0:
            print(f"Inserted {i} records")
        batch = []

if batch:
    collection.insert_many(batch)

print("Data generation completed.")
print("Total DriverPings:", collection.count_documents({}))
client.close()
