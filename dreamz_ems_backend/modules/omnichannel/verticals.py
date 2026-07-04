"""Meta WhatsApp Business Profile `vertical` enum (plan 06 §2).

Single source of truth for the save-time whitelist; mirrored on the frontend
(`lib/whatsapp-verticals.ts`) which drives the SearchSelect. Keep both in sync.
"""

WHATSAPP_VERTICALS = [
    "UNDEFINED",
    "OTHER",
    "AUTO",
    "BEAUTY",
    "APPAREL",
    "EDU",
    "ENTERTAIN",
    "EVENT_PLAN",
    "FINANCE",
    "GROCERY",
    "GOVT",
    "HOTEL",
    "HEALTH",
    "NONPROFIT",
    "PROF_SERVICES",
    "RETAIL",
    "TRAVEL",
    "RESTAURANT",
    "ALCOHOL",
    "ONLINE_GAMBLING",
    "PHYSICAL_GAMBLING",
    "OTC_DRUGS",
]

WHATSAPP_VERTICAL_SET = set(WHATSAPP_VERTICALS)
