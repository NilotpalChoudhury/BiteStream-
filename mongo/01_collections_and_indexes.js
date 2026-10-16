use("bitestream");

// Collection names follow the spec: Menus, Reviews, DriverPings.
// Remove old collections so the script can be safely rerun
// (also the lowercase names used by the original submission).
["Menus", "Reviews", "DriverPings", "menus", "reviews", "driverPings"].forEach(
    (name) => db.getCollection(name).drop()
);

// -------------------------
// CREATE COLLECTIONS WITH VALIDATION
// -------------------------
// Validators only enforce the core fields each workflow relies on. Everything
// else stays flexible (e.g. optional add-ons / dietary tags on menu items).

db.createCollection("Menus", {
    validator: {
        $jsonSchema: {
            bsonType: "object",
            required: ["restaurant_id", "restaurant_name", "categories"],
            properties: {
                restaurant_id: { bsonType: "string", description: "PostgreSQL restaurants.id (UUID)" },
                restaurant_name: { bsonType: "string" },
                location: {
                    bsonType: "object",
                    required: ["type", "coordinates"],
                    properties: {
                        type: { enum: ["Point"] },
                        coordinates: { bsonType: "array", minItems: 2, maxItems: 2 }
                    }
                },
                categories: {
                    bsonType: "array",
                    items: {
                        bsonType: "object",
                        required: ["name", "items"],
                        properties: {
                            name: { bsonType: "string" },
                            items: {
                                bsonType: "array",
                                items: {
                                    bsonType: "object",
                                    required: ["name", "price"],
                                    properties: {
                                        name: { bsonType: "string" },
                                        price: { bsonType: "number", minimum: 0 },
                                        customization_addons: { bsonType: "array" }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
});

db.createCollection("Reviews", {
    validator: {
        $jsonSchema: {
            bsonType: "object",
            required: ["restaurant_id", "user_id", "rating", "sentiment_tags", "created_at"],
            properties: {
                restaurant_id: { bsonType: "string", description: "PostgreSQL restaurants.id (UUID)" },
                user_id: { bsonType: "string", description: "PostgreSQL users.id (UUID)" },
                rating: { bsonType: "int", minimum: 1, maximum: 5 },
                comment: { bsonType: "string" },
                sentiment_tags: { bsonType: "array", items: { bsonType: "string" } },
                created_at: { bsonType: "date" }
            }
        }
    }
});

db.createCollection("DriverPings", {
    validator: {
        $jsonSchema: {
            bsonType: "object",
            required: ["driver_id", "active", "location", "created_at"],
            properties: {
                driver_id: { bsonType: "int" },
                active: { bsonType: "bool" },
                location: {
                    bsonType: "object",
                    required: ["type", "coordinates"],
                    properties: {
                        type: { enum: ["Point"] },
                        coordinates: {
                            bsonType: "array",
                            minItems: 2,
                            maxItems: 2,
                            items: { bsonType: "double" }
                        }
                    }
                },
                created_at: { bsonType: "date" }
            }
        }
    }
});

// -------------------------
// MENUS INDEXES
// -------------------------

db.Menus.createIndex(
    { restaurant_id: 1 },
    { name: "idx_menus_restaurant", unique: true }
);

db.Menus.createIndex(
    { "categories.name": 1 },
    { name: "idx_menus_category" }
);

// -------------------------
// REVIEWS INDEXES
// -------------------------

db.Reviews.createIndex(
    { restaurant_id: 1 },
    { name: "idx_reviews_restaurant" }
);

db.Reviews.createIndex(
    { rating: 1 },
    { name: "idx_reviews_rating" }
);

// -------------------------
// DRIVER PINGS INDEXES
// -------------------------

// Required 2dsphere index
db.DriverPings.createIndex(
    { location: "2dsphere" },
    { name: "idx_driverPings_location_2dsphere" }
);

// Required TTL index: 2 hours
db.DriverPings.createIndex(
    { created_at: 1 },
    {
        name: "idx_driverPings_created_at_ttl",
        expireAfterSeconds: 7200
    }
);

// Index for active-driver filtering
db.DriverPings.createIndex(
    { active: 1 },
    { name: "idx_driverPings_active" }
);

// -------------------------
// VERIFY
// -------------------------

print("Menus indexes:");
printjson(db.Menus.getIndexes());

print("Reviews indexes:");
printjson(db.Reviews.getIndexes());

print("DriverPings indexes:");
printjson(db.DriverPings.getIndexes());

print("MongoDB setup completed successfully.");
