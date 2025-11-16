import os
from typing import List, Optional, Any, Dict
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from bson import ObjectId
from datetime import datetime

# Database helpers
from database import db, create_document, get_documents

app = FastAPI(title="ShootUp API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- Utils ----------

def to_str_id(value: Any) -> str:
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, (bytes, bytearray)):
        try:
            return str(ObjectId(value))
        except Exception:
            return value.decode() if isinstance(value, (bytes, bytearray)) else str(value)
    return str(value)


def serialize_doc(doc: Dict[str, Any]) -> Dict[str, Any]:
    out = {}
    for k, v in doc.items():
        if isinstance(v, ObjectId):
            out[k] = str(v)
        elif isinstance(v, datetime):
            out[k] = v.isoformat()
        elif isinstance(v, list):
            out[k] = [serialize_doc(i) if isinstance(i, dict) else (str(i) if isinstance(i, ObjectId) else i) for i in v]
        elif isinstance(v, dict):
            out[k] = serialize_doc(v)
        else:
            out[k] = v
    return out

# ---------- Request Models ----------

class CreateEvent(BaseModel):
    title: str
    date_iso: Optional[str] = None
    location: Optional[str] = None
    access: str = Field("public", description="public|private")
    cover_url: Optional[str] = None
    challenges: List[str] = Field(default_factory=list)

class JoinEvent(BaseModel):
    code: str
    user_id: str
    username: Optional[str] = None

class UploadMedia(BaseModel):
    event_id: str
    user_id: str
    url: str
    media_type: str = Field("photo", description="photo|video")
    challenge: Optional[str] = None

class ToggleLike(BaseModel):
    user_id: str

class AddComment(BaseModel):
    user_id: str
    text: str

class UpdateUser(BaseModel):
    username: Optional[str] = None
    avatar_url: Optional[str] = None
    bio: Optional[str] = None

# ---------- Routes ----------

@app.get("/")
def read_root():
    return {"message": "ShootUp Backend is running"}

@app.get("/api/hello")
def hello():
    return {"message": "Hello from ShootUp API"}

@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
            response["database_name"] = db.name if hasattr(db, 'name') else "✅ Connected"
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:80]}"
        else:
            response["database"] = "⚠️  Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:80]}"
    return response

# ---- Event Endpoints ----

from random import choices
import string

def generate_code(length: int = 6) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return ''.join(choices(alphabet, k=length))

@app.post("/api/events")
def create_event(payload: CreateEvent):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    code = generate_code()
    event_doc = {
        "code": code,
        "title": payload.title,
        "date_iso": payload.date_iso,
        "location": payload.location,
        "access": payload.access,
        "cover_url": payload.cover_url,
        "participants": [],
        "challenges": payload.challenges,
        "ended": False,
    }
    inserted_id = db["event"].insert_one(event_doc).inserted_id
    event_doc["_id"] = inserted_id
    return serialize_doc(event_doc)

@app.get("/api/events/explore")
def explore_events(limit: int = 24):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    cursor = db["event"].find({"access": "public"}).sort("created_at", -1).limit(limit)
    events = []
    for e in cursor:
        participants_count = len(e.get("participants", []))
        media_count = db["media"].count_documents({"event_id": str(e["_id"])})
        e_ser = serialize_doc(e)
        e_ser["participants_count"] = participants_count
        e_ser["media_count"] = media_count
        # Choose a cover: event cover or first media
        if not e_ser.get("cover_url"):
            first_media = db["media"].find_one({"event_id": str(e["_id"])})
            if first_media:
                e_ser["cover_url"] = first_media.get("url")
        events.append(e_ser)
    return {"events": events}

@app.post("/api/events/join")
def join_event(payload: JoinEvent):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    event = db["event"].find_one({"code": payload.code.upper()}) or db["event"].find_one({"code": payload.code})
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    participants = set(event.get("participants", []))
    participants.add(payload.user_id)
    db["event"].update_one({"_id": event["_id"]}, {"$set": {"participants": list(participants)}})
    # upsert user profile minimal
    db["userprofile"].update_one({"user_id": payload.user_id}, {"$setOnInsert": {"username": payload.username or "Guest", "following_events": []}}, upsert=True)
    event = db["event"].find_one({"_id": event["_id"]})
    return serialize_doc(event)

@app.get("/api/events/by-code/{code}")
def get_event_by_code(code: str):
    event = db["event"].find_one({"code": code.upper()}) or db["event"].find_one({"code": code})
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return serialize_doc(event)

@app.get("/api/events/{event_id}")
def get_event(event_id: str):
    try:
        obj_id = ObjectId(event_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid event id")
    event = db["event"].find_one({"_id": obj_id})
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return serialize_doc(event)

# ---- Media Endpoints ----

@app.post("/api/media")
def upload_media(payload: UploadMedia):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    # ensure event exists
    try:
        _ = ObjectId(payload.event_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid event id")
    if not db["event"].find_one({"_id": ObjectId(payload.event_id)}):
        raise HTTPException(status_code=404, detail="Event not found")
    media_doc = {
        "event_id": payload.event_id,
        "user_id": payload.user_id,
        "url": payload.url,
        "media_type": payload.media_type,
        "challenge": payload.challenge,
        "likes_count": 0,
        "comments_count": 0,
    }
    inserted_id = db["media"].insert_one(media_doc).inserted_id
    media_doc["_id"] = inserted_id
    return serialize_doc(media_doc)

@app.get("/api/media/event/{event_id}")
def list_media_for_event(event_id: str, sort: str = "time"):
    try:
        _ = ObjectId(event_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid event id")
    query = {"event_id": event_id}
    cursor = db["media"].find(query)
    # Sorting options
    if sort == "time":
        cursor = cursor.sort("created_at", -1)
    elif sort == "participant":
        cursor = cursor.sort("user_id", 1)
    elif sort == "challenge":
        cursor = cursor.sort("challenge", 1)
    items = [serialize_doc(m) for m in cursor]
    return {"items": items}

@app.post("/api/media/{media_id}/like")
def toggle_like(media_id: str, payload: ToggleLike):
    try:
        _ = ObjectId(media_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid media id")
    media = db["media"].find_one({"_id": ObjectId(media_id)})
    if not media:
        raise HTTPException(status_code=404, detail="Media not found")
    like_q = {"media_id": media_id, "user_id": payload.user_id}
    exists = db["like"].find_one(like_q)
    if exists:
        db["like"].delete_one({"_id": exists["_id"]})
        delta = -1
    else:
        db["like"].insert_one(like_q)
        delta = 1
    new_count = max(0, (media.get("likes_count", 0) + delta))
    db["media"].update_one({"_id": media["_id"]}, {"$set": {"likes_count": new_count}})
    updated = db["media"].find_one({"_id": media["_id"]})
    return serialize_doc(updated)

@app.get("/api/media/{media_id}/comments")
def list_comments(media_id: str):
    try:
        _ = ObjectId(media_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid media id")
    cursor = db["comment"].find({"media_id": media_id}).sort("created_at", 1)
    return {"items": [serialize_doc(c) for c in cursor]}

@app.post("/api/media/{media_id}/comments")
def add_comment(media_id: str, payload: AddComment):
    try:
        _ = ObjectId(media_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid media id")
    media = db["media"].find_one({"_id": ObjectId(media_id)})
    if not media:
        raise HTTPException(status_code=404, detail="Media not found")
    comment_doc = {"media_id": media_id, "user_id": payload.user_id, "text": payload.text}
    db["comment"].insert_one(comment_doc)
    new_count = (media.get("comments_count", 0) + 1)
    db["media"].update_one({"_id": media["_id"]}, {"$set": {"comments_count": new_count}})
    return {"ok": True}

# ---- User Endpoints ----

@app.get("/api/user/{user_id}")
def get_user(user_id: str):
    prof = db["userprofile"].find_one({"user_id": user_id})
    if not prof:
        prof = {"user_id": user_id, "username": "Guest", "avatar_url": None, "following_events": []}
    # joined events
    joined = list(db["event"].find({"participants": {"$in": [user_id]}}))
    uploads = db["media"].count_documents({"user_id": user_id})
    out = serialize_doc(prof)
    out["joined_events"] = [serialize_doc(e) for e in joined]
    out["uploads_count"] = uploads
    return out

@app.put("/api/user/{user_id}")
def update_user(user_id: str, payload: UpdateUser):
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not updates:
        return {"ok": True}
    db["userprofile"].update_one({"user_id": user_id}, {"$set": updates}, upsert=True)
    prof = db["userprofile"].find_one({"user_id": user_id})
    return serialize_doc(prof)

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
