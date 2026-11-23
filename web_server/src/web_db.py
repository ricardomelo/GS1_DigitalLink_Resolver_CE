import logging
from typing import Any

from pymongo import errors
from pymongo.collection import Collection
from bson import errors as bson_errors
from mongo_db_init import mongo

logger = logging.getLogger(__name__)

# Cached collection reference — PyMongo handles connection pooling underneath
_resolver_collection: Collection | None = None


def _get_collection() -> Collection:
    global _resolver_collection
    if _resolver_collection is None:
        resolver_db = mongo.cx['resolver_ce']
        _resolver_collection = resolver_db['gs1resolver']
    return _resolver_collection


def _reformat_id(anchor_id: str) -> str:
    """The document id of an anchor, as the data entry API writes it: '01/0950...' or '/01/0950...' -> '01_0950...';
    an id ('8004_A_B') is returned unchanged. Only a slash right after the AI's digits becomes '_': a value keeps its
    own '_', and a value with a '/' (a %2F in the request; the data entry API never stores one) gives an id no
    document has (Documentation/adr/0049-data-entry-anchors.md). The official code turned every '/' into '_', so
    /8004/A%2FB read the document of /8004/A_B (finding U-004)."""
    if anchor_id[:1] == '/':
        anchor_id = anchor_id[1:]
    ai = len(anchor_id) - len(anchor_id.lstrip('0123456789'))
    if anchor_id[ai:ai + 1] == '/':
        anchor_id = anchor_id[:ai] + '_' + anchor_id[ai + 1:]
    return anchor_id


# Read a document from the 'gs1resolver' collection
def read_document(anchor: str) -> dict[str, Any]:
    try:
        resolver_coll = _get_collection()
        anchor = _reformat_id(anchor)
        document = resolver_coll.find_one({"_id": anchor})

        # Document not found
        if not document:
            return {"response_status": 404, "error": f"No document found for anchor: {anchor}"}

        return {"response_status": 200, "data": document}

    except (bson_errors.InvalidId, errors.PyMongoError):
        # the exception (it names the database's host and port) to the log, a fixed text to the caller (finding
        # U-006, Documentation/adr/0050-error-answers.md)
        logger.error("Database error reading %s", anchor, exc_info=True)
        return {"response_status": 500, "error": "Database error: see the resolver's log"}
