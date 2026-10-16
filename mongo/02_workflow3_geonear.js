use("bitestream");

// Workflow 3: closest ACTIVE drivers within 5 km of a restaurant's coordinates.
// The origin is the restaurant's location stored in its Menus document
// (copied from PostgreSQL restaurants.latitude / longitude by menus_seeder.py).
// Default: the demo restaurant seeded by postgres_seeder.py.
const restaurantId = "00000000-0000-4000-8000-0000000000a1";

const restaurant = db.Menus.findOne(
    { restaurant_id: restaurantId },
    { restaurant_name: 1, location: 1 }
);

if (!restaurant) {
    throw new Error(`Restaurant ${restaurantId} not found in Menus. Run the seeders first.`);
}

const results = db.DriverPings.aggregate([
    {
        // Must be the first stage; uses idx_driverPings_location_2dsphere and
        // returns pings sorted by distance (nearest first).
        $geoNear: {
            near: restaurant.location,
            key: "location",
            distanceField: "distance_from_restaurant",
            maxDistance: 5000,
            spherical: true,
            query: {
                active: true
            }
        }
    },
    {
        // A driver sends many pings; keep only each driver's nearest one.
        $group: {
            _id: "$driver_id",
            distance_from_restaurant: { $first: "$distance_from_restaurant" },
            location: { $first: "$location" },
            created_at: { $first: "$created_at" }
        }
    },
    {
        $sort: {
            distance_from_restaurant: 1
        }
    },
    {
        $limit: 10
    },
    {
        $project: {
            _id: 0,
            driver_id: "$_id",
            location: 1,
            created_at: 1,
            distance_km: {
                $round: [
                    { $divide: ["$distance_from_restaurant", 1000] },
                    3
                ]
            }
        }
    }
]).toArray();

print(`Nearest active drivers within 5 km of ${restaurant.restaurant_name}:`);

printjson(results);
