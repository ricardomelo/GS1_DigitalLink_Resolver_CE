import logging
from typing import Any

from pymongo import errors
from pymongo.collection import Collection
from bson import errors as bson_errors
from mongo_db_init import mongo

logger = logging.getLogger(__name__)

# Error answers carry fixed texts; what went wrong goes to the service's log with its traceback. The official code
# answered the exception's text ("Database error: " + str(e)), which names the database's host and port, the index
# and the key (finding U-006; Documentation/adr/0050-error-answers.md).
DATABASE_ERROR = "Database error: see the data entry service's log"
INTERNAL_ERROR = "Internal server error: see the data entry service's log"
INVALID_ID = "Invalid document id"

# Cached collection reference — PyMongo handles connection pooling underneath
_resolver_collection: Collection | None = None


def _get_collection() -> Collection:
    global _resolver_collection
    if _resolver_collection is None:
        resolver_db = mongo.cx['resolver_ce']
        _resolver_collection = resolver_db['gs1resolver']
    return _resolver_collection


# This script provides the four CRUD functions to interact with the MongoDB database

# The document id of an anchor: '/01/05392000229648' -> '01_05392000229648', '/8004/A_B' -> '8004_A_B'. The leading
# '/' is removed and the slash after the AI becomes '_' (some document databases do not allow '/' in the primary
# identifier). Only the first one: the data entry API stores /AI/value anchors only, the AI is digits, so the first '_'
# of an id ends the AI and the value keeps its own '_' (Documentation/adr/0049-data-entry-anchors.md). The official
# function turned every '/' into '_', so /8004/A/B and /8004/A_B were one document (finding U-004).
# Called with an id already in the internal form, it returns it unchanged.
def _reformat_id_for_db(document_id: str) -> str:
    if document_id[:1] == '/':
        document_id = document_id[1:]
    return document_id.replace('/', '_', 1)


# The reverse of _reformat_id_for_db(): '8004_A_B' -> '/8004/A_B' (the first '_' only; the official function turned
# every '_' into '/', so a value with '_' came back under another anchor). An anchor is returned unchanged.
def _reformat_id_for_external_use(document_id: str) -> str:
    if document_id[0:1] == '/':
        return document_id
    return '/' + document_id.replace('_', '/', 1)


# Create a new document in the 'gs1resolver' collection
def create_document(data: dict[str, Any]) -> dict[str, Any]:
    # Ensure 'data['_id']' (_id) is provided in 'data'
    if '_id' not in data:
        return {"response_status": 400, "error": "Missing '_id' in data"}

    try:
        resolver_coll = _get_collection()
        # Check if a document with same '_id' exists
        if resolver_coll.find_one({"_id": data['_id']}):
            return {"response_status": 409, "error": f"Document with id {data['_id']} already exists"}

        # No matching document exists, proceed with creation
        result = resolver_coll.insert_one(data)
        return {"response_status": 201, "data": f"Document with id {str(result.inserted_id)} created successfully"}

    except errors.DuplicateKeyError:
        # written by another request between the check above and the insert
        logger.warning("create_document: %s written in the meantime", data['_id'], exc_info=True)
        return {"response_status": 409, "error": f"Document with id {data['_id']} already exists"}

    except errors.PyMongoError:
        logger.error("Database error in create_document", exc_info=True)
        return {"response_status": 500, "error": DATABASE_ERROR}

    except Exception:
        logger.error("Internal error in create_document", exc_info=True)
        return {"response_status": 500, "error": INTERNAL_ERROR}


# Read a document from the 'gs1resolver' collection
def read_document(document_id: str) -> dict[str, Any]:
    try:
        resolver_coll = _get_collection()
        internal_document_id = _reformat_id_for_db(document_id)
        document = resolver_coll.find_one({"_id": internal_document_id})

        # Document not found
        if not document:
            return {"response_status": 404,
                    "error": f"No document found for anchor: {_reformat_id_for_external_use(document_id)}"}

        return {"response_status": 200, "data": document}

    except bson_errors.InvalidId:
        logger.warning("Invalid document id", exc_info=True)
        return {"response_status": 400, "error": INVALID_ID}

    except errors.PyMongoError:
        logger.error("Database error in read_document", exc_info=True)
        return {"response_status": 500, "error": DATABASE_ERROR}


def read_index() -> dict[str, Any]:
    try:
        resolver_coll = _get_collection()
        document_ids = [doc['_id'] for doc in resolver_coll.find({}, {'_id': 1})]

        # Document ids not found
        if not document_ids:
            return {"response_status": 404, "error": "No document ids found"}

        return {"response_status": 200, "data": document_ids}

    except bson_errors.InvalidId:
        logger.warning("Invalid document id", exc_info=True)
        return {"response_status": 400, "error": INVALID_ID}

    except errors.PyMongoError:
        logger.error("Database error in read_index", exc_info=True)
        return {"response_status": 500, "error": DATABASE_ERROR}


# Read every document (used for the summary of all records)
def read_all_documents() -> dict[str, Any]:
    try:
        resolver_coll = _get_collection()
        return {"response_status": 200, "data": list(resolver_coll.find({}))}

    except errors.PyMongoError:
        logger.error("Database error in read_all_documents", exc_info=True)
        return {"response_status": 500, "error": DATABASE_ERROR}


# Replace or delete a document only while it is still the one read (ADR 0023, ADR 0027): one atomic operation on the
# document, so removing one record never leaves the key without its others, and a write made in between is not lost
def write_document_if_unchanged(document: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
    """Writes document over the stored one, or deletes the stored one when document has no records left, provided the
    stored document is still expected, the document read: the filter names every field of it (_id, defaultLinktype,
    data...), so it acts as the document's revision. 200 when written, 409 when the stored document changed or went
    in the meantime (the caller reads it again). The official code replaced the document by its _id alone, so of two
    writers that read the same document the second undid the first, and both were answered as successful (F-009)."""
    try:
        resolver_coll = _get_collection()
        match = {**expected, "_id": document["_id"]}
        if document.get("data"):
            changed = resolver_coll.replace_one(match, document).matched_count
        else:
            changed = resolver_coll.delete_one(match).deleted_count
        if not changed:
            return {"response_status": 409, "error": f"Document {document['_id']} changed while it was being written"}
        return {"response_status": 200, "data": f"Document with anchor {document['_id']} written"}

    except errors.PyMongoError:
        logger.error("write_document_if_unchanged: Database error", exc_info=True)
        return {"response_status": 500, "error": DATABASE_ERROR}


# Delete a document from the 'gs1resolver' collection
def delete_document(document_id: str) -> dict[str, Any]:
    try:
        resolver_coll = _get_collection()
        document_id = _reformat_id_for_db(document_id)
        result = resolver_coll.delete_one({"_id": document_id})

        if result.deleted_count == 0:
            return {"response_status": 404, "error": f"No document found with id: {document_id}"}  # Document not found

        # Operation was successful and the document was deleted
        return {"response_status": 200, "data": f"Document with anchor {document_id} deleted successfully"}

    except bson_errors.InvalidId:
        logger.warning("Invalid document id", exc_info=True)
        return {"response_status": 400, "error": INVALID_ID}
    except errors.PyMongoError:
        logger.error("delete_document: Database error", exc_info=True)
        return {"response_status": 500, "error": DATABASE_ERROR}
    except Exception:
        logger.error("delete_document: Internal error", exc_info=True)
        return {"response_status": 500, "error": INTERNAL_ERROR}
