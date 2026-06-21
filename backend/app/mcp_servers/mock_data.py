"""
Mock data for MCP servers - extracted to external file for maintainability.
Separates data from logic to keep server files clean.
"""

# ── report_server.py 的 mock 数据 ──────────────────────────────

MOCK_PERFORMANCE_DATA = {
    "BeautyQueen": {
        "campaign_id": "CMP001",
        "exposure": 1200000,
        "engagement_rate": 8.5,
        "click_rate": 4.2,
        "conversion_rate": 2.8,
        "sales_count": 156,
        "revenue": 46800,
        "cost": 15000,
        "platform": "douyin",
        "category": "beauty"
    },
    "LisaBeauty": {
        "campaign_id": "CMP002",
        "exposure": 980000,
        "engagement_rate": 7.2,
        "click_rate": 3.8,
        "conversion_rate": 2.1,
        "sales_count": 98,
        "revenue": 29400,
        "cost": 12000,
        "platform": "xiaohongshu",
        "category": "beauty"
    },
    "TechGuru": {
        "campaign_id": "CMP003",
        "exposure": 890000,
        "engagement_rate": 9.1,
        "click_rate": 5.2,
        "conversion_rate": 3.5,
        "sales_count": 142,
        "revenue": 42600,
        "cost": 18000,
        "platform": "weibo",
        "category": "tech"
    }
}

MOCK_STRATEGY_DATA = {
    "douyin": {
        "beauty": {
            "best_posting_time": "19:00-21:00",
            "optimal_duration": "60-90秒",
            "top_hashtags": ["#美妆护肤", "#种草", "#好物分享"],
            "avg_engagement": 7.5,
            "trending_formats": ["产品测评", "使用教程", "前后对比"]
        },
        "fashion": {
            "best_posting_time": "18:00-20:00",
            "optimal_duration": "45-75秒",
            "top_hashtags": ["#穿搭分享", "#时尚达人", "#ootd"],
            "avg_engagement": 6.8,
            "trending_formats": ["搭配展示", "购物分享", "季节推荐"]
        }
    },
    "xiaohongshu": {
        "beauty": {
            "best_posting_time": "20:00-22:00",
            "optimal_duration": "图文为主",
            "top_hashtags": ["#护肤心得", "#美妆种草", "产品推荐"],
            "avg_engagement": 8.2,
            "trending_formats": ["详细测评", "成分分析", "使用心得"]
        },
        "food": {
            "best_posting_time": "12:00-14:00, 18:00-20:00",
            "optimal_duration": "图文为主",
            "top_hashtags": ["#美食探店", "#食谱分享", "美食推荐"],
            "avg_engagement": 7.8,
            "trending_formats": ["探店vlog", "食谱教程", "美食测评"]
        }
    }
}

# ── kol_search_server.py 的 mock 数据 ──────────────────────────

MOCK_KOLS = {
    "beauty": [
        {"name": "LisaBeauty", "platform": "xiaohongshu", "followers": 850000,
         "engagement_rate": 6.8, "price_range": "15000-25000",
         "tags": ["skincare", "makeup", "review", "tutorial"]},
        {"name": "EmmaMakeup", "platform": "douyin", "followers": 620000,
         "engagement_rate": 7.2, "price_range": "12000-20000",
         "tags": ["makeup", "tutorial", "beauty", "lifestyle"]},
        {"name": "SophieSkincare", "platform": "xiaohongshu", "followers": 980000,
         "engagement_rate": 5.9, "price_range": "18000-30000",
         "tags": ["skincare", "dermatology", "review", "anti-aging"]},
        {"name": "NinaBeauty", "platform": "weibo", "followers": 450000,
         "engagement_rate": 8.1, "price_range": "10000-18000",
         "tags": ["makeup", "skincare", "tutorial", "review"]},
        {"name": "KaraGlam", "platform": "douyin", "followers": 1200000,
         "engagement_rate": 4.5, "price_range": "20000-35000",
         "tags": ["glamour", "luxury", "makeup", "lifestyle"]},
    ],
    "fashion": [
        {"name": "MikiStyle", "platform": "xiaohongshu", "followers": 720000,
         "engagement_rate": 6.5, "price_range": "13000-22000",
         "tags": ["fashion", "style", "outfit", "trend"]},
        {"name": "CocoFashion", "platform": "douyin", "followers": 1100000,
         "engagement_rate": 5.8, "price_range": "18000-28000",
         "tags": ["luxury", "designer", "runway", "review"]},
        {"name": "LilyChic", "platform": "weibo", "followers": 380000,
         "engagement_rate": 7.9, "price_range": "9000-15000",
         "tags": ["casual", "affordable", "daily", "style"]},
        {"name": "AnnaTrend", "platform": "xiaohongshu", "followers": 650000,
         "engagement_rate": 6.2, "price_range": "14000-24000",
         "tags": ["trend", "forecast", "seasonal", "fashion"]},
        {"name": "BellaMode", "platform": "douyin", "followers": 890000,
         "engagement_rate": 4.8, "price_range": "16000-26000",
         "tags": ["elegant", "classic", "timeless", "style"]},
    ],
    "food": [
        {"name": "ChefWang", "platform": "douyin", "followers": 1500000,
         "engagement_rate": 7.5, "price_range": "25000-40000",
         "tags": ["cooking", "recipe", "restaurant", "review"]},
        {"name": "FoodieLi", "platform": "xiaohongshu", "followers": 580000,
         "engagement_rate": 8.2, "price_range": "12000-20000",
         "tags": ["street_food", "local", "authentic", "taste"]},
        {"name": "TinaKitchen", "platform": "weibo", "followers": 420000,
         "engagement_rate": 9.1, "price_range": "10000-18000",
         "tags": ["home_cooking", "baking", "tutorial", "healthy"]},
        {"name": "MikeFoodie", "platform": "douyin", "followers": 920000,
         "engagement_rate": 6.8, "price_range": "18000-30000",
         "tags": ["gourmet", "fine_dining", "critic", "luxury"]},
        {"name": "SarahTaste", "platform": "xiaohongshu", "followers": 780000,
         "engagement_rate": 5.2, "price_range": "15000-25000",
         "tags": ["vegetarian", "healthy", "organic", "lifestyle"]},
    ],
    "tech": [
        {"name": "TechGuru", "platform": "weibo", "followers": 680000,
         "engagement_rate": 8.5, "price_range": "20000-32000",
         "tags": ["gadgets", "smartphone", "review", "innovation"]},
        {"name": "DigitalLife", "platform": "douyin", "followers": 890000,
         "engagement_rate": 6.3, "price_range": "18000-28000",
         "tags": ["digital", "lifestyle", "smart_home", "iot"]},
        {"name": "AIExpert", "platform": "xiaohongshu", "followers": 1200000,
         "engagement_rate": 4.7, "price_range": "22000-35000",
         "tags": ["AI", "machine_learning", "future", "tech"]},
        {"name": "CodeMaster", "platform": "weibo", "followers": 350000,
         "engagement_rate": 9.2, "price_range": "12000-20000",
         "tags": ["programming", "development", "tutorial", "coding"]},
        {"name": "GamerPro", "platform": "douyin", "followers": 560000,
         "engagement_rate": 7.1, "price_range": "15000-25000",
         "tags": ["gaming", "esports", "review", "setup"]},
    ],
}

# ── monitor_server.py 的 mock 数据 ─────────────────────────────

MOCK_DELIVERY_STATUS = {
    "ORD001": {"status": "已发货", "tracking_number": "SF1234567890", "estimated_delivery": "2024-01-15"},
    "ORD002": {"status": "运输中", "tracking_number": "YT9876543210", "estimated_delivery": "2024-01-16"},
    "ORD003": {"status": "已签收", "tracking_number": "JD5555666677", "estimated_delivery": "2024-01-14"},
    "ORD004": {"status": "异常", "tracking_number": "ZF1111222333", "estimated_delivery": "待确认"},
    "ORD005": {"status": "已发货", "tracking_number": "ST9999888877", "estimated_delivery": "2024-01-17"},
}