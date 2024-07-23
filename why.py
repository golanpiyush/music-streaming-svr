from flask import Flask, request, jsonify
import requests
import json
import os
from ytmusicapi import YTMusic  # Ensure you have ytmusicapi installed
from time import time

app = Flask(__name__)

CACHE_FILE = 'SeverCacher.json'
CACHE_EXPIRY_TIME = 600  # 10 minutes
MAX_CACHE_SIZE = 30  # Number of entries to keep in cache

class Cache:
    def __init__(self, filename, expiry_time, max_size):
        self.filename = filename
        self.expiry_time = expiry_time
        self.max_size = max_size
        self.load_cache()

    def load_cache(self):
        if os.path.exists(self.filename):
            with open(self.filename, 'r') as f:
                self.cache = json.load(f)
        else:
            self.cache = {}

    def save_cache(self):
        with open(self.filename, 'w') as f:
            json.dump(self.cache, f)

    def get(self, key):
        entry = self.cache.get(key)
        if entry:
            if time() - entry['timestamp'] <= self.expiry_time:
                return entry['data']
            else:
                del self.cache[key]
        return None

    def put(self, key, data):
        if len(self.cache) >= self.max_size:
            self.evict()
        self.cache[key] = {'data': data, 'timestamp': time()}
        self.save_cache()

    def evict(self):
        # Sort cache by timestamp and remove the oldest entry
        sorted_items = sorted(self.cache.items(), key=lambda x: x[1]['timestamp'])
        oldest_items = sorted_items[:len(sorted_items) - self.max_size + 1]
        for item in oldest_items:
            del self.cache[item[0]]
        self.save_cache()

class YouTubeClient:
    def __init__(self, client_name, client_version, api_key, user_agent, referer=None):
        self.client_name = client_name
        self.client_version = client_version
        self.api_key = api_key
        self.user_agent = user_agent
        self.referer = referer

    def to_context(self, locale, visitor_data=None):
        return {
            "client": {
                "clientName": self.client_name,
                "clientVersion": self.client_version,
                "gl": locale['gl'],
                "hl": locale['hl'],
                "visitorData": visitor_data
            }
        }
    
    @staticmethod
    def get_default_clients():
        return {
            "ANDROID_MUSIC": YouTubeClient(
                client_name="ANDROID_MUSIC",
                client_version="5.01",
                api_key="AIzaSyAOghZGza2MQSZkY_zfZ370N-PUdXEo8AI",
                user_agent="Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/65.0.3325.181 Mobile Safari/537.36"
            ),
            "ANDROID": YouTubeClient(
                client_name="ANDROID",
                client_version="17.13.3",
                api_key="AIzaSyA8eiZmM1FaDVjRy-df2KTyQ_vz_yYM39w",
                user_agent="Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/65.0.3325.181 Mobile Safari/537.36"
            )
        }

def convert_seconds(seconds):
    minutes, seconds = divmod(seconds, 60)
    return minutes, seconds

# Initialize Cache
cache = Cache(CACHE_FILE, CACHE_EXPIRY_TIME, MAX_CACHE_SIZE)

def get_video_id(song_name):
    ytmusic = YTMusic()

    try:
        search_results = ytmusic.search(song_name, filter="songs")

        if search_results:
            video_id = search_results[0]['videoId']
            return video_id
        else:
            return None
    except Exception as e:
        return None

def get_video_info(video_id):
    client = YouTubeClient.get_default_clients()['ANDROID_MUSIC']
    locale = {'gl': 'US', 'hl': 'en'}
    context = client.to_context(locale)
    
    endpoint = f"https://music.youtube.com/youtubei/v1/player?key={client.api_key}"
    data = {"context": context, "videoId": video_id}
    headers = {
        "Origin": "https://music.youtube.com",
        "Referer": client.referer if client.referer else "https://music.youtube.com/",
        "Accept-Language": "en-US,en;q=0.9",
        "User-Agent": client.user_agent,
        "Content-Type": "application/json"
    }

    response = requests.post(endpoint, json=data, headers=headers)

    if response.status_code == 200:
        try:
            response_json = response.json()
            video_details = response_json.get('videoDetails', {})
            title = video_details.get('title', 'No title available')
            thumbnail_url = video_details.get('thumbnail', {}).get('thumbnails', [{}])[0].get('url', 'No thumbnail available')
            artistName = video_details.get('author', 'No artist available')
            length_seconds = int(video_details.get('lengthSeconds', '0'))
            minutes, seconds = convert_seconds(length_seconds)
            streaming_data = response_json.get('streamingData', {})
            formats = streaming_data.get('formats', [])
            adaptive_formats = streaming_data.get('adaptiveFormats', [])
            best_bitrate = 0
            best_audio_url = None
            all_formats = formats + adaptive_formats
            for fmt in all_formats:
                mime_type = fmt.get('mimeType', '')
                bitrate = fmt.get('bitrate', 0)
                url = fmt.get('url')
                if mime_type.startswith('audio/') and bitrate > best_bitrate:
                    best_bitrate = bitrate
                    best_audio_url = url
            
            result = {
                "title": title,
                "artist": artistName,
                "thumbnail_url": thumbnail_url,
                "duration": f"{minutes} minutes and {seconds} seconds",
                "best_audio_url": best_audio_url
            }

            cache.put(video_id, result)
            return result
        except json.JSONDecodeError:
            return {"error": "Error decoding JSON response"}
    else:
        return {"error": "Failed to retrieve video details"}

@app.route('/check_connection', methods=['GET'])
def check_connection():
    return jsonify({"status": "Server is up and running"}), 200

@app.route('/get_video_info', methods=['GET'])
def get_video_info_endpoint():
    song_name = request.args.get('q')
    username = request.args.get('username')  # Fetch the username from the request

    if not song_name:
        return jsonify({"error": "Song name is required"}), 400

    video_id = get_video_id(song_name)
    
    if not video_id:
        return jsonify({"error": f"No video ID found for '{song_name}'"}), 404

    video_info = get_video_info(video_id)
    
    if 'error' in video_info:
        return jsonify(video_info), 400
    else:
        return jsonify(video_info)

# Future endpoint for getting video details by ID
# @app.route('/get_video_details', methods=['GET'])
# def get_video_details_endpoint():
#     video_id = request.args.get('video_id')
#     if not video_id:
#         return jsonify({"error": "Video ID is required"}), 400
#     video_details = get_video_details(video_id)
#     return jsonify(video_details)

# Future endpoint for searching songs
# @app.route('/search_songs', methods=['GET'])
# def search_songs_endpoint():
#     query = request.args.get('query')
#     if not query:
#         return jsonify({"error": "Search query is required"}), 400
#     search_results = search_songs(query)
#     return jsonify(search_results)

if __name__ == '__main__':
    app.run(debug=True)
