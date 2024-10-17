import os
import json
import argparse
import google.auth
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import re

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
script_dir = os.path.dirname(os.path.abspath(__file__))
TOKEN_FILE = os.path.join(script_dir, "YTtoken.json")   # Path where token will be saved

def get_authenticated_service():
    credentials = None


    # Load credentials from token.json if it exists
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "r") as token_file:
            credentials = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    # If credentials don't exist or are invalid, generate them
    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(google.auth.transport.requests.Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(os.path.join(script_dir, "youtube_client_secret.json"), SCOPES)
            credentials = flow.run_local_server(port=0)

        # Save the credentials for future use
        with open(TOKEN_FILE, "w") as token_file:
            token_file.write(credentials.to_json())

    return build("youtube", "v3", credentials=credentials)

def upload_video(youtube, video_file, description):

    title, _ = os.path.splitext(os.path.basename(video_file))
    sanitized_title = re.sub(r'[^\x00-\x7F]+', '', title)
    print("Uploading: "+ sanitized_title)

    body = {
        "snippet": {
            "title": sanitized_title,  # Video title is the filename
            "description": sanitized_title + " #shorts #short",
            "tags": ["shorts"],  # Add tag for YouTube Shorts
            "categoryId": "22"  # Category ID for People & Blogs
        },
        "status": {
            "privacyStatus": "public",  # Can also be "private" or "unlisted"
             "madeForKids": False
        }
    }

    media = MediaFileUpload(video_file, chunksize=-1, resumable=True)
    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"Uploading... {int(status.progress() * 100)}% complete.")
    print(f"Video uploaded successfully: https://youtu.be/{response['id']}")

def main():
    parser = argparse.ArgumentParser(description="Upload a YouTube Short")
    parser.add_argument("video_file", help="Path to the video file")
    parser.add_argument("description", help="Description of the video")
    args = parser.parse_args()

    youtube = get_authenticated_service()
    upload_video(youtube, args.video_file, args.description)

if __name__ == "__main__":
    main()
