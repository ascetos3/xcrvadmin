#!/usr/bin/env python3
"""
Fix ticket status from 'replied' to 'accepted'
"""
from pymongo import MongoClient
from bson import ObjectId

# MongoDB connection
MONGODB_URI = "mongodb+srv://mustafaylmaz3566_db_user:mustafa65@cluster0.x4l2qe7.mongodb.net/xcrover"
client = MongoClient(MONGODB_URI)
db = client['xcrover']
tickets = db['support_tickets']

# Ticket ID from console log
ticket_id = "68ffabf98778ae2b6e92d9ac"

# Find ticket
ticket = tickets.find_one({'_id': ObjectId(ticket_id)})
if ticket:
    print(f"Current status: {ticket.get('status')}")
    
    # Fix status
    result = tickets.update_one(
        {'_id': ObjectId(ticket_id)},
        {'$set': {'status': 'accepted'}}
    )
    
    print(f"Updated {result.modified_count} ticket(s)")
    
    # Verify
    updated = tickets.find_one({'_id': ObjectId(ticket_id)})
    print(f"New status: {updated.get('status')}")
else:
    print("Ticket not found!")

client.close()
