import firebase_admin
from firebase_admin import firestore

from backend.config import FIREBASE_PROJECT_ID, GOOGLE_APPLICATION_CREDENTIALS

if not firebase_admin._apps:
    options = {"projectId": FIREBASE_PROJECT_ID} if FIREBASE_PROJECT_ID else None
    firebase_admin.initialize_app(options=options)

class _LazyFirestoreClient:
    def __init__(self) -> None:
        self._client = None

    def __getattr__(self, name: str):
        if self._client is None:
            self._client = firestore.client()
        return getattr(self._client, name)


db = _LazyFirestoreClient()
