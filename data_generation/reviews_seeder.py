"""
MongoDB seeder for BiteStream Reviews (Workflow 4: $facet review analytics).

restaurant_id and user_id are the PostgreSQL UUIDs (as strings), so the API can join a
restaurant's reviews to its row in Postgres. Run postgres_seeder.py first.
"""
from datetime import datetime, timedelta, timezone
import random
from pymongo import MongoClient
import psycopg2
import os
from dotenv import load_dotenv
load_dotenv()

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
DATABASE_NAME = "bitestream"
TOTAL_REVIEWS = 110000
BATCH_SIZE = 5000
SEED = 42

POSITIVE_TAGS = ["tasty", "delicious", "fresh", "fast delivery", "good packaging",
                 "friendly", "value for money", "excellent", "generous portions"]
NEGATIVE_TAGS = ["late delivery", "cold food", "bland", "overpriced", "wrong order",
                 "poor packaging", "small portions"]
NEUTRAL_TAGS = ["average", "spicy", "okay"]

COMMENTS = {
    5: ["Absolutely loved it, will order again!", "Best {dish} in town.", "Perfect meal, arrived hot and on time."],
    4: ["Really good food, delivery was quick.", "Tasty {dish}, slightly late but worth it.", "Good portions and well packed."],
    3: ["Decent food, nothing special.", "The {dish} was okay, delivery took a while.", "Average experience overall."],
    2: ["Food arrived cold.", "The {dish} was bland and overpriced.", "Not great, expected better."],
    1: ["Terrible experience, wrong order delivered.", "Very late and the {dish} was inedible.", "Would not order again."],
}
DISHES = ["biryani", "dosa", "pizza", "burger", "paneer tikka", "noodles", "haleem", "butter chicken"]

random.seed(SEED)

pg = psycopg2.connect(
    host=os.getenv("PGHOST", "localhost"),
    port=int(os.getenv("PGPORT", 5432)),
    user=os.getenv("PGUSER", "postgres"),
    password=os.getenv("PGPASSWORD", "postgres"),
    dbname=os.getenv("PGDATABASE", "bitestream"),
)
with pg.cursor() as cursor:
    cursor.execute("SELECT id::text FROM restaurants ORDER BY id;")
    restaurant_ids = [row[0] for row in cursor.fetchall()]
    cursor.execute("SELECT id::text FROM users ORDER BY id;")
    user_ids = [row[0] for row in cursor.fetchall()]
pg.close()

if not restaurant_ids or not user_ids:
    raise SystemExit("No restaurants/users in PostgreSQL. Run postgres_seeder.py first.")

# Each restaurant gets its own typical rating, so rating distributions differ between restaurants.
restaurant_quality = {r_id: random.uniform(2.3, 4.7) for r_id in restaurant_ids}

client = MongoClient(MONGO_URI)
db = client[DATABASE_NAME]
collection = db["Reviews"]

collection.delete_many({})
batch = []
now = datetime.now(timezone.utc)

for i in range(1, TOTAL_REVIEWS + 1):
    restaurant_id = random.choice(restaurant_ids)
    rating = min(5, max(1, round(random.gauss(restaurant_quality[restaurant_id], 1.0))))

    if rating >= 4:
        pool = POSITIVE_TAGS + NEUTRAL_TAGS
    elif rating <= 2:
        pool = NEGATIVE_TAGS + NEUTRAL_TAGS
    else:
        pool = POSITIVE_TAGS + NEGATIVE_TAGS + NEUTRAL_TAGS

    document = {
        "restaurant_id": restaurant_id,
        "user_id": random.choice(user_ids),
        "rating": rating,
        "comment": random.choice(COMMENTS[rating]).format(dish=random.choice(DISHES)),
        "sentiment_tags": random.sample(pool, random.randint(1, 3)),
        "created_at": now - timedelta(days=random.uniform(0, 365))
    }

    batch.append(document)

    if len(batch) == BATCH_SIZE:
        collection.insert_many(batch)
        print(f"Inserted {i} reviews")
        batch = []

if batch:
    collection.insert_many(batch)

print("Reviews data generation completed.")
print("Total reviews:", collection.count_documents({}))

client.close()
