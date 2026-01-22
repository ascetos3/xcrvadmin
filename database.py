from pymongo import MongoClient
import os
import sys
import logging
from datetime import datetime
import requests
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

# Default fallback URI (used only if environment variable is missing)
DEFAULT_MONGODB_URI = "mongodb+srv://osmangugurluosman_db_user:osman6565@cluster0.fom4byi.mongodb.net/xcrover"

class Database:
    def __init__(self):
        # Read initial flags and names
        self.use_driver = os.getenv('USE_MONGODB_DRIVER', 'false').lower() == 'true'
        self.database_name = os.getenv('MONGODB_DATABASE', 'xcrover')
        self.client = None
        self.db = None

        # Resolve Mongo URI with safe fallback
        env_uri = os.getenv('MONGODB_URI', '').strip()
        if env_uri:
            self.uri = env_uri
            logger.info("MONGODB_URI detected from environment.")
        else:
            # Use fallback URI to avoid Data API misconfiguration crashes in production
            self.uri = DEFAULT_MONGODB_URI
            logger.warning("MONGODB_URI not set. Using built-in fallback URI. Set MONGODB_URI in environment for production.")
            # Force driver mode if we have any usable URI
            self.use_driver = True

        logger.info(f"Database initialization - USE_DRIVER: {self.use_driver}")

        # Try driver mode first when enabled
        if self.use_driver:
            try:
                logger.info("Attempting MongoDB connection via driver...")
                self.client = MongoClient(self.uri, serverSelectionTimeoutMS=5000)
                self.db = self.client[self.database_name]
                self.client.admin.command('ping')
                logger.info(f"✓ MongoDB bağlantısı başarılı: {self.database_name}")
            except Exception as e:
                logger.error(f"✗ MongoDB hatası: {e}")
                logger.exception("Full traceback:")
                # If driver fails, fall back to Data API path
                self.use_driver = False

        # Configure Data API if driver not in use
        if not self.use_driver:
            self.api_url = os.getenv('MONGODB_API_URL', '').rstrip('/')
            self.api_key = os.getenv('MONGODB_API_KEY', '')
            self.cluster = os.getenv('MONGODB_CLUSTER', 'Cluster0')

            if self.api_url and self.api_key:
                logger.info(f"✓ Data API yapılandırıldı: {self.cluster}/{self.database_name}")
            else:
                logger.warning("Neither MongoDB Driver nor Data API configured properly! Set USE_MONGODB_DRIVER=true and MONGODB_URI, or configure MONGODB_API_URL+MONGODB_API_KEY.")
    
    def _api_request(self, action, collection, document=None, filter_query=None, options=None):
        endpoint = f"{self.api_url}/action/{action}"
        payload = {
            "dataSource": self.cluster,
            "database": self.database_name,
            "collection": collection
        }
        
        if document:
            payload["document"] = document
        if filter_query is not None:
            payload["filter"] = filter_query
        if options:
            if 'sort' in options:
                payload["sort"] = options['sort']
            if 'limit' in options:
                payload["limit"] = options['limit']
        
        headers = {"Content-Type": "application/json", "api-key": self.api_key}
        
        try:
            response = requests.post(endpoint, json=payload, headers=headers, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"Data API hatası: {e}")
            raise
    
    def find(self, collection, filter_query=None, options=None):
        if filter_query is None:
            filter_query = {}
        if options is None:
            options = {}
        
        if self.use_driver:
            coll = self.db[collection]
            cursor = coll.find(filter_query)
            
            if 'sort' in options:
                cursor = cursor.sort(list(options['sort'].items()))
            if 'limit' in options:
                cursor = cursor.limit(options['limit'])
            
            return list(cursor)
        else:
            result = self._api_request('find', collection, filter_query=filter_query, options=options)
            return result.get('documents', [])
    
    def find_one(self, collection, filter_query):
        if self.use_driver:
            return self.db[collection].find_one(filter_query)
        else:
            result = self._api_request('findOne', collection, filter_query=filter_query)
            return result.get('document')
    
    def insert(self, collection, document):
        if self.use_driver:
            result = self.db[collection].insert_one(document)
            return result.inserted_id
        else:
            result = self._api_request('insertOne', collection, document=document)
            return result.get('insertedId')
    
    def update(self, collection, filter_query, update_data):
        if self.use_driver:
            # If update_data already contains operators like $set, $inc, etc., use it directly
            # Otherwise, wrap it in $set
            if any(key.startswith('$') for key in update_data.keys()):
                result = self.db[collection].update_one(filter_query, update_data)
            else:
                result = self.db[collection].update_one(filter_query, {'$set': update_data})
            return result
        else:
            # Data API always needs the update document structure
            if not any(key.startswith('$') for key in update_data.keys()):
                update_data = {'$set': update_data}
            result = self._api_request('updateOne', collection, 
                                      filter_query=filter_query, 
                                      document=update_data)
            class UpdateResult:
                def __init__(self, modified_count):
                    self.modified_count = modified_count
            return UpdateResult(result.get('modifiedCount', 0))
    
    def delete(self, collection, filter_query):
        if self.use_driver:
            result = self.db[collection].delete_one(filter_query)
            return result
        else:
            result = self._api_request('deleteOne', collection, filter_query=filter_query)
            class DeleteResult:
                def __init__(self, deleted_count):
                    self.deleted_count = deleted_count
            return DeleteResult(result.get('deletedCount', 0))
    
    def count(self, collection, filter_query=None):
        if filter_query is None:
            filter_query = {}
        
        if self.use_driver:
            return self.db[collection].count_documents(filter_query)
        else:
            result = self._api_request('find', collection, filter_query=filter_query)
            return len(result.get('documents', []))
