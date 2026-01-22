from datetime import datetime
from bson import ObjectId
import secrets
import string

def doc_get(doc, key, default=''):
    if doc is None:
        return default
    if isinstance(doc, dict):
        return doc.get(key, default)
    return getattr(doc, key, default)

def to_ts(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, dict) and '$date' in value:
        date_val = value['$date']
        if isinstance(date_val, dict) and '$numberLong' in date_val:
            timestamp_ms = int(date_val['$numberLong'])
            return datetime.fromtimestamp(timestamp_ms / 1000.0)
        if isinstance(date_val, str):
            try:
                return datetime.fromisoformat(date_val.replace('Z', '+00:00'))
            except:
                pass
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace('Z', '+00:00'))
        except:
            pass
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value / 1000.0 if value > 10000000000 else value)
        except:
            pass
    return None

def boolval_safe(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ['true', '1', 'yes', 'on']
    if isinstance(value, (int, float)):
        return value != 0
    return bool(value)

def format_date(dt, format_str='%d.%m.%Y %H:%M'):
    if dt is None:
        return '-'
    if isinstance(dt, datetime):
        return dt.strftime(format_str)
    normalized = to_ts(dt)
    if normalized:
        return normalized.strftime(format_str)
    return '-'

def generate_license_key(length=24):
    chars = string.ascii_uppercase + string.digits
    return ''.join(secrets.choice(chars) for _ in range(length))

def get_status_badge(status):
    # Normalize legacy statuses for badge purposes
    normalized = status
    if status in ('replied', 'open'):
        normalized = 'accepted'
    badges = {
        'pending': 'badge-warning',
        'accepted': 'badge-success',
        'closed': 'badge-secondary'
    }
    return badges.get(normalized, 'badge-info')

def serialize_doc(doc):
    """Convert MongoDB document to JSON-serializable dict"""
    if doc is None:
        return None
    if isinstance(doc, list):
        return [serialize_doc(item) for item in doc]
    if isinstance(doc, dict):
        result = {}
        for key, value in doc.items():
            if isinstance(value, ObjectId):
                result[key] = str(value)
            elif isinstance(value, datetime):
                result[key] = value.isoformat()
            elif isinstance(value, dict):
                result[key] = serialize_doc(value)
            elif isinstance(value, list):
                result[key] = serialize_doc(value)
            else:
                # Legacy status normalization at serialization boundary
                if key == 'status' and value in ('replied', 'open'):
                    result[key] = 'accepted'
                else:
                    result[key] = value
        return result
    if isinstance(doc, ObjectId):
        return str(doc)
    if isinstance(doc, datetime):
        return doc.isoformat()
    return doc
