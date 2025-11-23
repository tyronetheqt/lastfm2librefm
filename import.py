#!/usr/bin/env python3
import time
import requests
import sys
import os
import json
import webbrowser
from urllib.parse import urlencode, urlparse, parse_qs
from urllib.request import urlopen, Request

API_URL = "https://libre.fm/2.0/"
API_KEY = "LibreImporter"
CALLBACK_URL = "http://localhost/libre-importer-callback"
MAX_RETRIES = 3
RETRY_DELAY = 2
SESSION_KEY = None
SLEEP_BETWEEN_SCROBBLES = 1

RESUME_FILE = "scrobble_progress.txt"
SESSION_KEY_FILE = "session_key.txt"

def get_auth_url(api_key: str, callback_url: str) -> str:
    params = urlencode({
        "api_key": api_key,
        "cb": callback_url
    })
    return f"https://libre.fm/api/auth/?{params}"

def extract_token(redirect_url: str) -> str | None:
    try:
        parsed_url = urlparse(redirect_url)
        query_params = parse_qs(parsed_url.query)
        token = query_params.get("token", [None])[0]
        return token
    except:
        return None

def get_session_key(api_key: str, token: str) -> str | None:
    data = {
        "method": "auth.getSession",
        "api_key": api_key,
        "token": token,
        "format": "json"
    }
    encoded_data = urlencode(data).encode("utf-8")

    for attempt in range(MAX_RETRIES):
        try:
            req = Request(API_URL, data=encoded_data)
            with urlopen(req, timeout=10) as resp:
                resp_json = json.load(resp)

            if "error" in resp_json:
                print(f"API Error Code {resp_json.get('error')}: {resp_json.get('message')}")
                return None

            session_key = resp_json.get("session", {}).get("key")
            return session_key

        except Exception:
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY)
            else:
                return None
    return None

def get_libre_session_key() -> str | None:
    auth_url = get_auth_url(API_KEY, CALLBACK_URL)

    print("Hey, first we need to get your Libre.fm key.")
    print("1. A browser tab is about to pop open for authorization.")
    print("2. After you log in and approve, copy the ENTIRE URL from the address bar.")

    webbrowser.open(auth_url)

    redirect_input = input("\nPaste that full URL here: ").strip()

    if not redirect_input:
        print("Oops, authorization canceled.")
        return None

    one_time_token = extract_token(redirect_input)

    if not one_time_token:
        print("Couldn't find the token in that URL. Did you copy it right? Try again.")
        return None

    session_key = get_session_key(API_KEY, one_time_token)

    if session_key:
        print("\nSuccess! We've got your permanent session key.")
        return session_key
    else:
        print("\nSomething went wrong trying to get the final key. Sorry!")
        return None

def load_session_key():
    if os.path.exists(SESSION_KEY_FILE):
        try:
            with open(SESSION_KEY_FILE, "r") as f:
                return f.read().strip()
        except Exception:
            return None
    return None

def save_session_key(key):
    try:
        with open(SESSION_KEY_FILE, "w") as f:
            f.write(key)
        print(f"Key saved to {SESSION_KEY_FILE} for next time.")
    except IOError as e:
        print(f"Whoops, couldn't save the session key to file: {e}")

def get_last_scrobbled_line():
    if os.path.exists(RESUME_FILE):
        try:
            with open(RESUME_FILE, "r") as f:
                last_line = int(f.read().strip())
                return last_line + 1
        except ValueError:
            print(f"Heads up: Couldn't read the resume file. Starting from the first line.")
            return 1
    return 1

def save_current_line(line_number):
    try:
        with open(RESUME_FILE, "w") as f:
            f.write(str(line_number))
    except IOError as e:
        print(f"Error saving progress to {RESUME_FILE}: {e}")

def scrobble_track(artist, track, album="", timestamp=None):
    global SESSION_KEY
    if SESSION_KEY is None:
        print("Error: No session key. Can't scrobble.")
        return None

    if timestamp is None:
        timestamp = int(time.time())

    payload = {
        "method": "track.scrobble",
        "artist": artist,
        "track": track,
        "album": album,
        "timestamp": timestamp,
        "sk": SESSION_KEY,
        "api_key": API_KEY,
        "format": "json"
    }

    response = None
    try:
        response = requests.post(API_URL, data=payload, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        if response is not None and response.status_code >= 400:
            print(f"Server bounced scrobble (HTTP {response.status_code}): {response.text}")
        else:
            print(f"Network or server error: {e}")
        return None

def main():
    global SESSION_KEY

    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} exported_tracks.txt")
        sys.exit(1)

    SESSION_KEY = os.environ.get("LIBRE_SESSION_KEY")

    if not SESSION_KEY:
        SESSION_KEY = load_session_key()

    if not SESSION_KEY:
        print("Can't find your session key locally or in your environment. Let's get it now.")
        SESSION_KEY = get_libre_session_key()
        if SESSION_KEY:
            save_session_key(SESSION_KEY)
        if not SESSION_KEY:
            print("Stopping. We need a valid session key to proceed.")
            sys.exit(1)

    filename = sys.argv[1]
    start_line = get_last_scrobbled_line()
    print("--- Starting scrobbler ---")
    print(f"File: {filename}")
    print(f"Initial/Resume Start Line (1-indexed): {start_line}")
    print("--------------------------")

    try:
        with open(filename, "r", encoding="utf-8") as f:
            current_line_number = 0
            for line in f:
                current_line_number += 1
                if current_line_number < start_line:
                    continue

                parts = line.strip().split("\t")
                if len(parts) < 4:
                    print(f"Skipping malformed line {current_line_number}: {line.strip()}")
                    continue

                timestamp, track, artist, album = parts[:4]
                try:
                    timestamp = int(timestamp)
                except ValueError:
                    print(f"Warning: Invalid timestamp on line {current_line_number}. Using current time.")
                    timestamp = int(time.time())

                result = scrobble_track(artist, track, album, timestamp)
                if result:
                    save_current_line(current_line_number)
                    print(f"SUCCESS {current_line_number}: {artist} - {track} | response: {result}")
                else:
                    print(f"FAIL {current_line_number}: {artist} - {track} | Failed to scrobble.")

                time.sleep(SLEEP_BETWEEN_SCROBBLES)
    except FileNotFoundError:
        print(f"File not found: {filename}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nScript interrupted by user (Ctrl+C). Progress saved.")
        sys.exit(0)
    except Exception as e:
        print(f"Something totally unexpected happened: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
