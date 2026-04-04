import os
import base64
import uuid
import datetime as dt
import json

import requests
from fastapi import FastAPI, Depends, HTTPException, status, Request, File, UploadFile
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import Response
import firebase_admin
from firebase_admin import credentials, auth, firestore, storage


app = FastAPI(title="Firebase FastAPI Backend")

# Firebase init
cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
if not cred_path:
    raise RuntimeError("GOOGLE_APPLICATION_CREDENTIALS não definida.")
cred = credentials.Certificate(cred_path)

bucket_name = os.environ.get("FIREBASE_STORAGE_BUCKET")
if bucket_name:
    firebase_admin.initialize_app(cred, {"storageBucket": bucket_name})
else:
    firebase_admin.initialize_app(cred)

db = firestore.client()
bucket = storage.bucket()

auth_scheme = HTTPBearer(auto_error=False)


def get_current_user(token: HTTPAuthorizationCredentials = Depends(auth_scheme)) -> str:
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciais de autenticação não fornecidas.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        decoded = auth.verify_id_token(token.credentials)
        return decoded.get("uid")
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de autenticação inválido ou expirado.",
            headers={"WWW-Authenticate": "Bearer"},
        )


PIXEL_GIF_BASE64 = "R0lGODlhAQABAIAAAAAAAP///yH5BAEHAAEALAAAAAABAAEAAAICTAEAOw=="
PIXEL_GIF_BYTES = base64.b64decode(PIXEL_GIF_BASE64)


@app.get("/health")
def health():
    return {"ok": True, "ts": int(dt.datetime.now(dt.timezone.utc).timestamp())}


@app.post("/cases")
def create_case(case: dict = None, user_id: str = Depends(get_current_user)):
    data = {
        "owner_uid": user_id,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    if case:
        if case.get("title"):
            data["title"] = case["title"]
        if case.get("description"):
            data["description"] = case["description"]
    _, ref = db.collection("cases").add(data)
    data["id"] = ref.id
    return data


@app.get("/cases")
def list_cases(user_id: str = Depends(get_current_user)):
    q = db.collection("cases").where("owner_uid", "==", user_id).stream()
    items = []
    for d in q:
        x = d.to_dict()
        x["id"] = d.id
        items.append(x)
    return {"cases": items}


@app.get("/cases/{case_id}")
def get_case(case_id: str, user_id: str = Depends(get_current_user)):
    doc = db.collection("cases").document(case_id).get()
    if not doc.exists:
        raise HTTPException(404, "Caso não encontrado.")
    data = doc.to_dict()
    if data.get("owner_uid") != user_id:
        raise HTTPException(403, "Acesso negado.")
    data["id"] = case_id
    return data


@app.post("/cases/{case_id}/evidences")
def add_evidence(
    case_id: str,
    request: Request,
    url: str = None,
    headers: str = None,
    file: UploadFile = File(None),
    user_id: str = Depends(get_current_user),
):
    cref = db.collection("cases").document(case_id)
    cdoc = cref.get()
    if not cdoc.exists:
        raise HTTPException(404, "Caso não encontrado.")
    if cdoc.to_dict().get("owner_uid") != user_id:
        raise HTTPException(403, "Acesso negado.")

    if not url and not headers and not file:
        raise HTTPException(422, "Informe ao menos um dos campos: url, headers ou file.")

    ev = {"added_at": dt.datetime.now(dt.timezone.utc).isoformat()}
    if url:
        ev["url"] = url
    if headers:
        try:
            ev["headers"] = json.loads(headers)
        except Exception:
            ev["headers"] = headers

    if file:
        _, ext = os.path.splitext(file.filename or "")
        unique = f"{uuid.uuid4()}{ext}"
        blob_path = f"cases/{case_id}/{unique}"
        blob = bucket.blob(blob_path)
        blob.upload_from_file(file.file, content_type=file.content_type)
        signed = blob.generate_signed_url(dt.timedelta(days=1))
        ev.update({"file_name": file.filename, "file_path": blob_path, "file_url": signed})

    _, ref = cref.collection("evidences").add(ev)
    ev["id"] = ref.id
    return ev


@app.get("/cases/{case_id}/evidences")
def list_evidences(case_id: str, user_id: str = Depends(get_current_user)):
    cref = db.collection("cases").document(case_id)
    cdoc = cref.get()
    if not cdoc.exists:
        raise HTTPException(404, "Caso não encontrado.")
    if cdoc.to_dict().get("owner_uid") != user_id:
        raise HTTPException(403, "Acesso negado.")
    items = []
    for d in cref.collection("evidences").stream():
        x = d.to_dict()
        x["id"] = d.id
        items.append(x)
    return {"case_id": case_id, "evidences": items}


@app.get("/canary/{case_id}")
def canary(case_id: str, request: Request):
    cref = db.collection("cases").document(case_id)
    if not cref.get().exists:
        raise HTTPException(404, "Caso não encontrado.")
    ip = request.headers.get("x-forwarded-for") or request.client.host
    ua = request.headers.get("user-agent", "N/A")
    cref.collection("canary_logs").add({
        "ip": ip,
        "user_agent": ua,
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
    })
    return Response(content=PIXEL_GIF_BYTES, media_type="image/gif")


@app.get("/osint/{username}")
def osint_lookup(username: str, user_id: str = Depends(get_current_user)):
    found = []
    try:
        r = requests.get(f"https://api.github.com/users/{username}", timeout=5)
        if r.status_code == 200:
            found.append({"site": "GitHub", "url": f"https://github.com/{username}"})
    except Exception:
        pass
    try:
        h = {"User-Agent": "FastAPI-OSINT/0.1"}
        r = requests.get(
            f"https://www.reddit.com/user/{username}/about.json",
            headers=h,
            timeout=5,
        )
        if r.status_code == 200 and r.json().get("error") != 404:
            found.append({"site": "Reddit", "url": f"https://reddit.com/u/{username}"})
    except Exception:
        pass
    return {"username": username, "found_accounts": found}
