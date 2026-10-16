"""
MongoDB seeder for BiteStream Menus (flexible catalog documents).

One menu per PostgreSQL restaurant: restaurant_id is the Postgres UUID (as a string),
restaurant_name matches Postgres, and location holds the restaurant's coordinates as a
GeoJSON Point (handy as the $geoNear origin). Run postgres_seeder.py first.
"""
from datetime import datetime, timezone
import random
import uuid
from pymongo import MongoClient
import psycopg2
import os
from dotenv import load_dotenv
load_dotenv()

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
DATABASE_NAME = "bitestream"
SEED = 42

CATALOG = {
    "Biryani": ["Chicken Dum Biryani", "Mutton Biryani", "Veg Biryani", "Egg Biryani", "Paneer Biryani"],
    "Pizza": ["Margherita Pizza", "Farmhouse Pizza", "Pepperoni Pizza", "Paneer Tikka Pizza"],
    "Burgers": ["Chicken Burger", "Veg Burger", "Double Cheese Burger", "Crispy Paneer Burger"],
    "South Indian": ["Masala Dosa", "Idli Sambar", "Medu Vada", "Pesarattu", "Uttapam"],
    "North Indian": ["Butter Chicken", "Paneer Butter Masala", "Dal Makhani", "Butter Naan", "Chole Bhature"],
    "Chinese": ["Veg Fried Rice", "Hakka Noodles", "Chilli Chicken", "Veg Manchurian"],
    "Desserts": ["Gulab Jamun", "Double Ka Meetha", "Chocolate Cake", "Qubani Ka Meetha", "Rasmalai"],
    "Beverages": ["Irani Chai", "Cold Coffee", "Fresh Lime Soda", "Mango Lassi", "Badam Milk"],
}

ADDONS = {
    "Biryani": [("Extra raita", 30), ("Extra salan", 40), ("Boiled egg", 25)],
    "Pizza": [("Extra cheese", 60), ("Jalapenos", 40), ("Thin crust", 0)],
    "Burgers": [("Extra patty", 70), ("Cheese slice", 30), ("Fries", 60)],
    "South Indian": [("Extra chutney", 15), ("Ghee roast", 30)],
    "North Indian": [("Extra gravy", 50), ("Butter on top", 20)],
    "Chinese": [("Extra sauce", 20), ("Add egg", 25)],
    "Desserts": [("Extra scoop of ice cream", 50)],
    "Beverages": [("Less sugar", 0), ("Extra ice", 0), ("Large size", 30)],
}

DIETARY = ["veg", "non-veg", "vegan", "contains-nuts", "gluten-free", "spicy"]
DESCRIPTORS = ["Freshly made", "House-special", "Classic", "Chef's signature", "Slow-cooked", "Hyderabadi-style"]
SERVED = ["served hot", "made to order", "serves one", "best enjoyed fresh", "packed for delivery"]

random.seed(SEED)

pg = psycopg2.connect(
    host=os.getenv("PGHOST", "localhost"),
    port=int(os.getenv("PGPORT", 5432)),
    user=os.getenv("PGUSER", "postgres"),
    password=os.getenv("PGPASSWORD", "postgres"),
    dbname=os.getenv("PGDATABASE", "bitestream"),
)
with pg.cursor() as cursor:
    cursor.execute("SELECT id::text, name, latitude, longitude FROM restaurants ORDER BY id;")
    restaurants = cursor.fetchall()
pg.close()

if not restaurants:
    raise SystemExit("No restaurants in PostgreSQL. Run postgres_seeder.py first.")

client = MongoClient(MONGO_URI)
db = client[DATABASE_NAME]
collection = db["Menus"]

collection.delete_many({})
documents = []

for restaurant_id, name, latitude, longitude in restaurants:
    categories = []
    for category in random.sample(list(CATALOG), random.randint(2, 5)):
        items = []
        for item_name in random.sample(CATALOG[category], random.randint(2, len(CATALOG[category]))):
            item = {
                "item_id": str(uuid.UUID(int=random.getrandbits(128), version=4)),
                "name": item_name,
                "description": f"{random.choice(DESCRIPTORS)} {item_name.lower()}, {random.choice(SERVED)}.",
                "price": round(random.uniform(60, 600), 2),
                "available": random.random() < 0.85,
            }
            # Flexible schema: only some items carry add-ons / dietary tags.
            if random.random() < 0.7:
                item["customization_addons"] = [
                    {"name": a, "price": p}
                    for a, p in random.sample(ADDONS[category], random.randint(1, len(ADDONS[category])))
                ]
            if random.random() < 0.5:
                item["dietary_tags"] = random.sample(DIETARY, random.randint(1, 2))
            items.append(item)
        categories.append({"name": category, "items": items})

    documents.append({
        "restaurant_id": restaurant_id,
        "restaurant_name": name,
        "location": {"type": "Point", "coordinates": [longitude, latitude]},
        "categories": categories,
        "updated_at": datetime.now(timezone.utc)
    })

collection.insert_many(documents)

print("Menus data generation completed.")
print("Total menus:", collection.count_documents({}))
client.close()
