"""YouTube Data API v3 publisher for the SPOIL library (SPOIL/NNN_<long|short>_<slug>/).

    python tools/publishers/youtube_api.py auth --client-secret <client_secret.json>
    python tools/publishers/youtube_api.py whoami
    python tools/publishers/youtube_api.py captions <video> <folder> [--only fa,es] [--apply]
    python tools/publishers/youtube_api.py meta     <video> <folder> [--title B] [--apply]
    python tools/publishers/youtube_api.py comment  <video> <folder> [--apply]
    python tools/publishers/youtube_api.py upload   <folder> [--file x.mp4] [--apply]

<video> is a video ID or any YouTube link; <folder> is a library folder or just
its number (001). Every command is a dry run that reads only local files and
prints the quota it would spend; --apply writes to YouTube.

Files read from the folder (NNN = its number):
  NNN_subtitles_<lang>.srt          captions, one track per language
  NNN_titles.txt                    one title per line, option A first
  NNN_description.txt, NNN_tags.txt (comma separated)
  NNN_title_<lang>.txt, NNN_description_<lang>.txt   optional localizations
  NNN_pinned_comment.txt

Two channels can be signed in at once; every command takes --channel spoilfa
(default, or YOUTUBE_CHANNEL in .env) or --channel mr82, and refuses videos of
any other channel. Credentials live in .env only: YOUTUBE_CLIENT_ID,
YOUTUBE_CLIENT_SECRET and one YOUTUBE_REFRESH_TOKEN_<CHANNEL> per channel, all
written by `auth`. Google answers 403 to requests from Iran, so all
traffic goes through the local proxy (OPENMONTAGE_LOCAL_PROXY, default
http://127.0.0.1:10808) unless --direct is given.

Quota (10,000 units a day): videos.insert 1600, captions.insert 400,
captions.list / videos.update / commentThreads.insert 50, reads 1.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.server
import json
import os
import re
import secrets
import sys
import time
import urllib.parse
import uuid
import webbrowser
from datetime import date
from pathlib import Path

import requests
from dotenv import load_dotenv, set_key

REPO = Path(__file__).resolve().parents[2]
ENV_FILE = REPO / ".env"
LIBRARY = Path(os.environ.get("SPOIL_LIBRARY", REPO.parent / "SPOIL"))
README = LIBRARY / "README.md"

SCOPE = "https://www.googleapis.com/auth/youtube.force-ssl"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/youtube/v3"
UPLOAD_API = "https://www.googleapis.com/upload/youtube/v3"

DAILY_QUOTA = 10_000
COST = {
    "videos.list": 1,
    "channels.list": 1,
    "commentThreads.list": 1,
    "captions.list": 50,
    "videos.update": 50,
    "commentThreads.insert": 50,
    "captions.insert": 400,
    "videos.insert": 1600,
}
CHANNELS = {"spoilfa": "UCzcS-uRF9p36KmjzAWiEGqA", "mr82": "UCFKzubSKok8jKRXrHwjyBaw"}
CHUNK = 8 * 1024 * 1024
NOT_MAIN_VIDEO = ("phone-preview", "preview", "no-captions", "en-audio")
UPLOAD_HEADER = "| # | شناسه ویدیو |"


class ApiError(RuntimeError):
    pass


# --- auth -------------------------------------------------------------------


def make_session(direct: bool) -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    if not direct:
        proxy = os.environ.get("OPENMONTAGE_LOCAL_PROXY", "http://127.0.0.1:10808")
        session.proxies = {"http": proxy, "https": proxy}
    return session


class _Redirect(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        if "code" not in query and "error" not in query:
            self.send_response(404)
            self.end_headers()
            return
        self.server.query = {k: v[0] for k, v in query.items()}
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        page = "<p dir='rtl' style='font:20px sans-serif'>تمام شد. این صفحه رو ببندید و برگردید به ترمینال.</p>"
        self.wfile.write(page.encode("utf-8"))

    def log_message(self, *args):
        pass


def authorize(session: requests.Session, client_file: Path, channel: str) -> None:
    client = json.loads(client_file.read_text(encoding="utf-8"))
    if "installed" not in client:
        raise SystemExit("This is not a Desktop app client. In Google Cloud create an OAuth client of type 'Desktop app'.")
    client = client["installed"]

    server = http.server.HTTPServer(("127.0.0.1", 0), _Redirect)
    server.timeout = 300
    server.query = None
    redirect_uri = f"http://127.0.0.1:{server.server_port}/"
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    url = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": client["client_id"],
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
    })
    print("Sign in with the channel's Google account in the browser (VPN on).")
    print("If no browser opened, open this address yourself:\n" + url)
    webbrowser.open(url)

    deadline = time.time() + 300
    while server.query is None and time.time() < deadline:
        server.handle_request()
    server.server_close()
    query = server.query
    if query is None:
        raise SystemExit("No answer from the browser within 5 minutes; run auth again.")
    if "error" in query:
        raise SystemExit(f"Google refused the sign-in: {query['error']}")
    if query.get("state") != state:
        raise SystemExit("The browser answer does not match this sign-in; run auth again.")

    r = session.post(TOKEN_URL, timeout=60, data={
        "code": query["code"],
        "client_id": client["client_id"],
        "client_secret": client["client_secret"],
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
        "code_verifier": verifier,
    })
    if r.status_code != 200:
        raise SystemExit(f"Token exchange failed: {r.status_code} {r.json().get('error', '')}")
    tokens = r.json()
    if not tokens.get("refresh_token"):
        raise SystemExit("Google sent no refresh token; remove the app's access at myaccount.google.com/permissions and run auth again.")

    # The account may own several channels; make sure the one picked in the browser is the one asked for.
    r = session.get(f"{API}/channels", params={"part": "snippet", "mine": "true"}, timeout=60,
                    headers={"Authorization": f"Bearer {tokens['access_token']}"})
    if r.status_code != 200:
        fail(r)
    items = r.json().get("items") or [{"id": "none", "snippet": {"title": "no channel"}}]
    if items[0]["id"] != CHANNELS[channel]:
        raise SystemExit(f"The browser sign-in chose {items[0]['snippet']['title']} ({items[0]['id']}), not {channel} "
                         f"({CHANNELS[channel]}); nothing saved. Run auth again and pick that channel.")

    ENV_FILE.touch()
    for key, value in (("YOUTUBE_CLIENT_ID", client["client_id"]),
                       ("YOUTUBE_CLIENT_SECRET", client["client_secret"]),
                       (f"YOUTUBE_REFRESH_TOKEN_{channel.upper()}", tokens["refresh_token"])):
        set_key(str(ENV_FILE), key, value)
        os.environ[key] = value
    print(f"Signed in as {items[0]['snippet']['title']} ({items[0]['id']}); "
          f"saved the client and refresh token to {ENV_FILE} (not shown).")


# --- API --------------------------------------------------------------------


class YouTube:
    def __init__(self, session: requests.Session, channel: str):
        self.token_key = f"YOUTUBE_REFRESH_TOKEN_{channel.upper()}"
        missing = [k for k in ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", self.token_key) if not os.environ.get(k)]
        if missing:
            raise SystemExit(f"{', '.join(missing)} not in .env; run "
                             f"`auth --channel {channel} --client-secret <client_secret.json>` first.")
        self.channel = channel
        self.channel_id = CHANNELS[channel]
        self.session = session
        self.spent = 0
        self._token = None
        self._expires = 0.0

    def _headers(self) -> dict:
        if time.time() > self._expires:
            r = self.session.post(TOKEN_URL, timeout=60, data={
                "client_id": os.environ["YOUTUBE_CLIENT_ID"],
                "client_secret": os.environ["YOUTUBE_CLIENT_SECRET"],
                "refresh_token": os.environ[self.token_key],
                "grant_type": "refresh_token",
            })
            if r.status_code != 200:
                error = r.json().get("error", "") if r.headers.get("content-type", "").startswith("application/json") else r.text[:200]
                if error == "invalid_grant":
                    # Apps left in "Testing" get refresh tokens that die after 7 days.
                    raise SystemExit(f"The saved sign-in for {self.channel} expired or was revoked; "
                                     f"run `auth --channel {self.channel}` again.")
                raise ApiError(f"token refresh failed: {r.status_code} {error}")
            body = r.json()
            self._token = body["access_token"]
            self._expires = time.time() + body.get("expires_in", 3600) - 120
        return {"Authorization": f"Bearer {self._token}"}

    def call(self, method: str, url: str, cost_name: str, **kwargs) -> dict:
        headers = {**self._headers(), **kwargs.pop("headers", {})}
        r = self.session.request(method, url, headers=headers, timeout=kwargs.pop("timeout", 120), **kwargs)
        self.spent += COST[cost_name]
        if r.status_code >= 300:
            fail(r)
        return r.json() if r.content else {}

    def video(self, video_id: str) -> dict:
        body = self.call("GET", f"{API}/videos", "videos.list",
                         params={"part": "snippet,status,localizations", "id": video_id})
        if not body.get("items"):
            raise SystemExit(f"Video {video_id} not found, or this account cannot see it.")
        return body["items"][0]

    def my_channel(self) -> dict:
        body = self.call("GET", f"{API}/channels", "channels.list", params={"part": "snippet", "mine": "true"})
        if not body.get("items"):
            raise SystemExit("This Google account has no YouTube channel.")
        return body["items"][0]

    def owned_video(self, video_id: str) -> dict:
        video = self.video(video_id)
        if video["snippet"]["channelId"] != self.channel_id:
            raise SystemExit(f"Video {video_id} belongs to channel {video['snippet']['channelId']}, "
                             f"not {self.channel} ({self.channel_id}); nothing written.")
        return video

    def upload_file(self, url: str, path: Path) -> dict:
        size = path.stat().st_size
        offset, failures = 0, 0
        with path.open("rb") as f:
            while True:
                f.seek(offset)
                chunk = f.read(CHUNK)
                headers = {**self._headers(), "Content-Range": f"bytes {offset}-{offset + len(chunk) - 1}/{size}"}
                try:
                    r = self.session.put(url, data=chunk, headers=headers, timeout=300)
                except requests.RequestException as e:
                    r, error = None, e
                if r is not None and r.status_code in (200, 201):
                    return r.json()
                if r is not None and r.status_code == 308:
                    offset = _next_offset(r)
                    failures = 0
                    print(f"  {offset * 100 // size:3d}%  {offset // 2**20} / {size // 2**20} MB", flush=True)
                    continue
                if r is not None and r.status_code < 500 and r.status_code != 429:
                    fail(r)
                failures += 1
                if failures > 8:
                    raise ApiError(f"upload stopped after {failures} failed tries at {offset // 2**20} MB")
                print(f"  network trouble ({r.status_code if r is not None else error}); retrying", flush=True)
                time.sleep(min(60, 2 ** failures))
                # Ask the server how much it really has before sending again.
                try:
                    r = self.session.put(url, headers={**self._headers(), "Content-Range": f"bytes */{size}"}, timeout=60)
                except requests.RequestException:
                    continue
                if r.status_code in (200, 201):
                    return r.json()
                if r.status_code == 308:
                    offset = _next_offset(r)


def _next_offset(r: requests.Response) -> int:
    received = r.headers.get("Range")  # "bytes=0-1048575"
    return int(received.rsplit("-", 1)[1]) + 1 if received else 0


def fail(r: requests.Response):
    try:
        err = r.json()["error"]
        reason = err.get("errors", [{}])[0].get("reason", "")
        message = err.get("message", "")
    except (ValueError, KeyError, TypeError, AttributeError):
        reason, message = "", r.text[:300]
    if reason in ("quotaExceeded", "dailyLimitExceeded"):
        message += " (daily quota used up; it resets at midnight Pacific time)"
    raise ApiError(f"{r.status_code} {reason}: {message}")


# --- library ----------------------------------------------------------------


def resolve_folder(arg: str) -> Path:
    folder = Path(arg)
    if not folder.is_dir() and re.fullmatch(r"\d{1,3}", arg):
        hits = [p for p in LIBRARY.glob(f"{int(arg):03d}_*") if p.is_dir()]
        folder = hits[0] if len(hits) == 1 else folder
    if not folder.is_dir():
        raise SystemExit(f"No library folder {arg!r} (looked in {LIBRARY}).")
    if not re.match(r"\d{3}_", folder.name):
        raise SystemExit(f"{folder} is not a numbered library folder (NNN_...).")
    return folder


def number(folder: Path) -> str:
    return folder.name[:3]


def video_id_from(arg: str) -> str:
    m = re.search(r"(?:v=|youtu\.be/|/shorts/|/video/|/live/)([A-Za-z0-9_-]{11})", arg)
    vid = m.group(1) if m else arg
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", vid):
        raise SystemExit(f"{arg!r} is not a YouTube video ID or link.")
    return vid


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig").strip()


def subtitle_files(folder: Path) -> dict[str, Path]:
    prefix = f"{number(folder)}_subtitles_"
    return {p.stem[len(prefix):]: p for p in sorted(folder.glob(f"{prefix}*.srt"))}


def pick_title(folder: Path, option: str) -> str:
    path = folder / f"{number(folder)}_titles.txt"
    titles = {}
    for i, line in enumerate(l for l in read_text(path).splitlines() if l.strip()):
        m = re.match(r"\s*(?:[-*]\s*)?(?:\*\*)?([A-Ea-e])(?:\*\*)?\s*[:).\-]\s*(.+)", line)
        if m:
            titles[m.group(1).upper()] = m.group(2).strip()
        else:
            titles.setdefault("ABCDE"[i] if i < 5 else str(i), line.strip())
    if option.upper() not in titles:
        raise SystemExit(f"No title option {option} in {path.name} (has {', '.join(titles)}).")
    return titles[option.upper()]


def read_tags(folder: Path) -> list[str]:
    path = folder / f"{number(folder)}_tags.txt"
    if not path.exists():
        return []
    tags = [t.strip() for t in re.split(r"[,\n]", read_text(path)) if t.strip()]
    # YouTube counts quotes around tags with spaces and the commas between tags.
    kept, used = [], 0
    for tag in tags:
        cost = len(tag) + (2 if " " in tag else 0) + (1 if kept else 0)
        if used + cost > 500:
            print(f"  note: tags over YouTube's 500-character limit; dropped from {tag!r} on")
            break
        kept.append(tag)
        used += cost
    return kept


def check_text(title: str, description: str, where: str) -> None:
    problems = []
    if len(title) > 100:
        problems.append(f"title is {len(title)} characters (max 100)")
    if len(description.encode("utf-8")) > 5000:
        problems.append(f"description is {len(description.encode('utf-8'))} bytes (max 5000)")
    if re.search(r"[<>]", title + description):
        problems.append("YouTube rejects < and > in titles and descriptions")
    if problems:
        raise SystemExit(f"{where}: " + "; ".join(problems))


def metadata(folder: Path, title_option: str, language: str) -> tuple[dict, dict]:
    num = number(folder)
    title = pick_title(folder, title_option)
    description = read_text(folder / f"{num}_description.txt")
    check_text(title, description, folder.name)
    snippet = {
        "title": title,
        "description": description,
        "tags": read_tags(folder),
        "defaultLanguage": language,
        "defaultAudioLanguage": language,
    }
    localizations = {}
    for path in sorted(folder.glob(f"{num}_title_*.txt")):
        lang = path.stem[len(f"{num}_title_"):]
        desc_path = folder / f"{num}_description_{lang}.txt"
        if desc_path.exists():
            desc = read_text(desc_path)
        else:
            desc = description
            print(f"  note: no {desc_path.name}; {lang} viewers get the {language} description")
        check_text(read_text(path), desc, path.name)
        localizations[lang] = {"title": read_text(path), "description": desc}
    return snippet, localizations


def main_video(folder: Path) -> Path:
    videos = [p for p in folder.glob("*.mp4") if not any(tag in p.stem for tag in NOT_MAIN_VIDEO)]
    if len(videos) != 1:
        found = ", ".join(p.name for p in videos) or "none"
        raise SystemExit(f"Cannot tell the main video in {folder.name} ({found}); pass --file.")
    return videos[0]


def record(num: str, video_id: str, uploaded: str = "", note: str = "") -> None:
    """Fill the video's row in README's upload table."""
    lines = README.read_text(encoding="utf-8").splitlines()
    start = next((i for i, l in enumerate(lines) if l.startswith(UPLOAD_HEADER)), None)
    if start is None:
        print(f"  note: no upload table in {README}; not recorded")
        return
    end = start + 2
    while end < len(lines) and lines[end].startswith("|"):
        end += 1
    rows = {}
    for line in lines[start + 2:end]:
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        rows[cells[0]] = cells + [""] * (5 - len(cells))
    row = rows.get(num, [num, "", "", "", ""])
    row[1] = f"`{video_id}`"
    row[2] = f"https://youtu.be/{video_id}"
    row[3] = row[3] or uploaded
    if note:
        row[4] = "; ".join(filter(None, [row[4], f"{date.today():%Y-%m-%d}: {note}"]))
    rows[num] = row
    lines[start + 2:end] = ["| " + " | ".join(r) + " |" for _, r in sorted(rows.items())]
    README.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  recorded in {README.name}")


def print_quota(calls: list[tuple[str, int]]) -> None:
    total = sum(COST[name] * n for name, n in calls if n)
    parts = ", ".join(f"{name} x{n} = {COST[name] * n}" for name, n in calls if n)
    print(f"Quota: {parts} -> {total} of {DAILY_QUOTA:,} units/day")


# --- commands ---------------------------------------------------------------


def cmd_captions(args, session) -> None:
    folder = resolve_folder(args.folder)
    video_id = video_id_from(args.video)
    tracks = subtitle_files(folder)
    if args.only:
        wanted = {l.strip() for l in args.only.split(",")}
        tracks = {lang: p for lang, p in tracks.items() if lang in wanted}
    if not tracks:
        raise SystemExit(f"No {number(folder)}_subtitles_<lang>.srt files to upload in {folder.name}.")
    print(f"{folder.name} -> {video_id}: {', '.join(tracks)} (track name {args.name!r})")
    print_quota([("videos.list", 1), ("captions.list", 1), ("captions.insert", len(tracks))])
    if not args.apply:
        print("Dry run. Languages the video already has are skipped with --apply (their 400 units are not spent).")
        return

    yt = YouTube(session, args.channel)
    video = yt.owned_video(video_id)
    existing = yt.call("GET", f"{API}/captions", "captions.list", params={"part": "snippet", "videoId": video_id})
    have = {item["snippet"]["language"].lower() for item in existing.get("items", [])
            if item["snippet"].get("trackKind") != "asr"}
    have |= {lang.split("-")[0] for lang in have}
    done = []
    try:
        for lang, path in tracks.items():
            if lang.lower() in have or lang.lower().split("-")[0] in have:
                print(f"  {lang}: already on the video, skipped")
                continue
            meta = json.dumps({"snippet": {"videoId": video_id, "language": lang, "name": args.name, "isDraft": False}})
            boundary = uuid.uuid4().hex
            body = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{meta}\r\n"
                    f"--{boundary}\r\nContent-Type: application/octet-stream\r\n\r\n").encode() \
                + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
            caption = yt.call("POST", f"{UPLOAD_API}/captions", "captions.insert", data=body,
                              params={"part": "snippet", "uploadType": "multipart"},
                              headers={"Content-Type": f"multipart/related; boundary={boundary}"})
            done.append(lang)
            print(f"  {lang}: uploaded ({caption.get('id', '?')})")
    finally:
        print(f"Spent {yt.spent} quota units.")
        if done:
            record(number(folder), video_id, video["snippet"].get("publishedAt", "")[:10],
                   "زیرنویس " + ", ".join(done))


def cmd_meta(args, session) -> None:
    folder = resolve_folder(args.folder)
    video_id = video_id_from(args.video)
    snippet, localizations = metadata(folder, args.title, args.language)
    print(f"{folder.name} -> {video_id}")
    print(f"  title ({args.title}): {snippet['title']}")
    print(f"  description: {len(snippet['description'])} characters, first line: {snippet['description'].splitlines()[0]}")
    print(f"  tags: {len(snippet['tags'])}")
    print(f"  localizations: {', '.join(localizations) or 'none'}")
    print_quota([("videos.list", 1), ("videos.update", 1)])
    if not args.apply:
        print("Dry run. --apply replaces the video's title, description and tags with these.")
        return

    yt = YouTube(session, args.channel)
    video = yt.owned_video(video_id)
    body = {"id": video_id, "snippet": {**snippet, "categoryId": video["snippet"]["categoryId"]}}
    part = "snippet"
    if localizations or video.get("localizations"):
        body["localizations"] = {**video.get("localizations", {}), **localizations}
        part += ",localizations"
    try:
        yt.call("PUT", f"{API}/videos", "videos.update", params={"part": part}, json=body)
        print("  updated")
    finally:
        print(f"Spent {yt.spent} quota units.")
    note = "عنوان، توضیحات و تگ‌ها" + (f" (+ {', '.join(localizations)})" if localizations else "")
    record(number(folder), video_id, video["snippet"].get("publishedAt", "")[:10], note)


def cmd_comment(args, session) -> None:
    folder = resolve_folder(args.folder)
    video_id = video_id_from(args.video)
    text = read_text(folder / f"{number(folder)}_pinned_comment.txt")
    print(f"{folder.name} -> {video_id}, comment:\n{text}")
    print_quota([("videos.list", 1), ("commentThreads.list", 1), ("commentThreads.insert", 1)])
    print("The API cannot pin comments: pin it by hand in YouTube Studio > Comments (or on the watch page, ⋮ > Pin).")
    if not args.apply:
        print("Dry run.")
        return

    yt = YouTube(session, args.channel)
    video = yt.owned_video(video_id)
    channel = video["snippet"]["channelId"]
    try:
        if not args.again:
            threads = yt.call("GET", f"{API}/commentThreads", "commentThreads.list",
                              params={"part": "snippet", "videoId": video_id, "maxResults": 100})
            for thread in threads.get("items", []):
                if thread["snippet"]["topLevelComment"]["snippet"].get("authorChannelId", {}).get("value") == channel:
                    raise SystemExit("The channel already has a comment on this video; pass --again to post another.")
        thread = yt.call("POST", f"{API}/commentThreads", "commentThreads.insert", params={"part": "snippet"},
                         json={"snippet": {"videoId": video_id, "topLevelComment": {"snippet": {"textOriginal": text}}}})
        print(f"  posted: https://www.youtube.com/watch?v={video_id}&lc={thread['id']}")
        print("  Now pin it by hand.")
    finally:
        print(f"Spent {yt.spent} quota units.")
    record(number(folder), video_id, video["snippet"].get("publishedAt", "")[:10], "کامنت (پین دستی)")


def cmd_upload(args, session) -> None:
    folder = resolve_folder(args.folder)
    path = Path(args.file) if args.file else main_video(folder)
    if not path.is_absolute() and not path.exists():
        path = folder / path
    snippet, localizations = metadata(folder, args.title, args.language)
    snippet["categoryId"] = args.category
    print(f"{path.name} ({path.stat().st_size / 2**20:.0f} MB) -> new private video on {args.channel} ({CHANNELS[args.channel]})")
    print(f"  title ({args.title}): {snippet['title']}")
    print(f"  tags: {len(snippet['tags'])}, localizations: {', '.join(localizations) or 'none'}")
    print_quota([("channels.list", 1), ("videos.insert", 1)])
    print("Note: a Google Cloud project that has not passed YouTube's API audit can only make private videos;\n"
          "YouTube keeps them locked private. Upload by hand in Studio when the video should go public.")
    if not args.apply:
        print("Dry run.")
        return

    yt = YouTube(session, args.channel)
    channel = yt.my_channel()
    if channel["id"] != yt.channel_id:
        raise SystemExit(f"Signed in as channel {channel['id']} ({channel['snippet']['title']}), "
                         f"not {args.channel} ({yt.channel_id}); nothing uploaded.")
    body = {"snippet": snippet,
            "status": {"privacyStatus": "private", "selfDeclaredMadeForKids": False}}
    part = "snippet,status"
    if localizations:
        body["localizations"] = localizations
        part += ",localizations"
    try:
        r = session.post(f"{UPLOAD_API}/videos", params={"uploadType": "resumable", "part": part}, json=body,
                         timeout=120, headers={**yt._headers(), "X-Upload-Content-Type": "video/mp4",
                                               "X-Upload-Content-Length": str(path.stat().st_size)})
        if r.status_code != 200:
            fail(r)
        yt.spent += COST["videos.insert"]
        video = yt.upload_file(r.headers["Location"], path)
    finally:
        print(f"Spent {yt.spent} quota units.")
    print(f"  uploaded as private: https://youtu.be/{video['id']}")
    print(f"  Studio: https://studio.youtube.com/video/{video['id']}/edit")
    record(number(folder), video["id"], date.today().strftime("%Y-%m-%d"), "آپلود خصوصی از راه API")


def cmd_whoami(args, session) -> None:
    yt = YouTube(session, args.channel)
    channel = yt.my_channel()
    match = "matches" if channel["id"] == yt.channel_id else f"does NOT match {args.channel} ({yt.channel_id})"
    print(f"Signed in as {channel['snippet']['title']} ({channel['id']}); {match}.")


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv(ENV_FILE)
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--direct", action="store_true", help="skip the local proxy")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("auth", help="one-time sign-in; saves the refresh token to .env")
    p.add_argument("--client-secret", required=True, type=Path, help="client_secret_*.json of a Desktop app client")
    sub.add_parser("whoami", help="show the signed-in channel (1 unit)")

    p = sub.add_parser("captions", help="upload NNN_subtitles_<lang>.srt files")
    p.add_argument("video")
    p.add_argument("folder")
    p.add_argument("--only", help="comma-separated languages, e.g. fa,es")
    p.add_argument("--name", default="SPOIL", help="caption track name shown next to the language")

    p = sub.add_parser("meta", help="set title, description, tags and localizations")
    p.add_argument("video")
    p.add_argument("folder")

    p = sub.add_parser("comment", help="post NNN_pinned_comment.txt (pin it by hand)")
    p.add_argument("video")
    p.add_argument("folder")
    p.add_argument("--again", action="store_true", help="post even if the channel already commented")

    p = sub.add_parser("upload", help="upload the main MP4 as a private video")
    p.add_argument("folder")
    p.add_argument("--file", help="the MP4 to upload when the folder has more than one")
    p.add_argument("--category", default="27", help="YouTube category ID (27 = Education)")

    for name in ("meta", "upload"):
        sub.choices[name].add_argument("--title", default="A", help="title option from NNN_titles.txt")
        sub.choices[name].add_argument("--language", default="fa", help="the video's own language")
    for name in ("captions", "meta", "comment", "upload"):
        sub.choices[name].add_argument("--apply", action="store_true", help="write to YouTube (default: dry run)")
    for p in sub.choices.values():
        p.add_argument("--channel", choices=CHANNELS, default=os.environ.get("YOUTUBE_CHANNEL", "spoilfa"))

    args = parser.parse_args(argv)
    session = make_session(args.direct)
    commands = {"captions": cmd_captions, "meta": cmd_meta, "comment": cmd_comment,
                "upload": cmd_upload, "whoami": cmd_whoami}
    try:
        if args.command == "auth":
            authorize(session, args.client_secret, args.channel)
        else:
            commands[args.command](args, session)
    except ApiError as e:
        print(f"YouTube error: {e}", file=sys.stderr)
        return 1
    except requests.RequestException as e:
        print(f"Network error ({type(e).__name__}). Is v2rayN on? Proxy: {session.proxies.get('https', 'none')}",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
