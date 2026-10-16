use("bitestream");

// Restaurant ids are PostgreSQL UUIDs (strings). Default: the demo restaurant.
const restaurantId = "00000000-0000-4000-8000-0000000000a1";

const results = db.Reviews.aggregate([
    {
        $match: {
            restaurant_id: restaurantId
        }
    },

    {
        $facet: {

            rating_distribution: [
                {
                    $group: {
                        _id: "$rating",
                        count: { $sum: 1 }
                    }
                },
                {
                    $sort: {
                        _id: 1
                    }
                },
                {
                    $project: {
                        _id: 0,
                        rating: "$_id",
                        count: 1
                    }
                }
            ],

            most_frequent_tags: [
                {
                    $unwind: "$sentiment_tags"
                },
                {
                    $group: {
                        _id: "$sentiment_tags",
                        count: { $sum: 1 }
                    }
                },
                {
                    $sort: {
                        count: -1
                    }
                },
                {
                    $limit: 10
                },
                {
                    $project: {
                        _id: 0,
                        tag: "$_id",
                        count: 1
                    }
                }
            ],

            overall_average_rating: [
                {
                    $group: {
                        _id: null,
                        average_rating: {
                            $avg: "$rating"
                        },
                        total_reviews: {
                            $sum: 1
                        }
                    }
                },
                {
                    $project: {
                        _id: 0,
                        average_rating: {
                            $round: [
                                "$average_rating",
                                2
                            ]
                        },
                        total_reviews: 1
                    }
                }
            ]
        }
    }
]).toArray();

print("Review analytics for restaurant:", restaurantId);
printjson(results);