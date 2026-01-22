#!/usr/bin/env python3
"""
Normalize legacy support_tickets statuses:
- replied -> accepted
- open -> accepted

Usage: python fix_all_replied_statuses.py
"""
from pymongo import MongoClient
from bson import ObjectId
from datetime import datetime

MONGODB_URI = "mongodb+srv://mustafaylmaz3566_db_user:mustafa65@cluster0.x4l2qe7.mongodb.net/xcrover"
DB_NAME = "xcrover"

client = MongoClient(MONGODB_URI)
db = client[DB_NAME]
coll = db['support_tickets']

print("Scanning for legacy statuses (replied/open)...")
legacy = list(coll.find({ 'status': { '$in': ['replied','open'] } }, { '_id': 1, 'status': 1 }))
print(f"Found {len(legacy)} tickets to normalize")

if legacy:
    res = coll.update_many(
        { 'status': { '$in': ['replied','open'] } },
        { '$set': { 'status': 'accepted', 'updatedAt': datetime.utcnow() } }
    )
    print(f"Modified {res.modified_count} ticket(s)")
else:
    print("No legacy tickets found.")

client.close()
