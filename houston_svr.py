from flask import Flask, request, jsonify, send_file
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from dotenv import load_dotenv
import os
import requests
from functools import lru_cache
import yt_dlp as ydl

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)

# Get Spotify API credentials from environment variables
SPOTIFY_CLIENT_ID = os.getenv('SPOTIFY_CLIENT_ID')
SPOTIFY_CLIENT_SECRET = os.getenv('SPOTIFY_CLIENT_SECRET')

if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
    raise ValueError("Missing Spotify API credentials. Please check your .env file.")

# Set up Spotipy client
sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
    client_id=SPOTIFY_CLIENT_ID,
    client_secret=SPOTIFY_CLIENT_SECRET
))

# Function to fetch audio info using yt-dlp
def get_audio_info(song_name):
    ydl_opts = {
        'format': 'bestaudio/best',
        'quiet': True,  # Disable yt_dlp console output
    }
    with ydl.YoutubeDL(ydl_opts) as ydl_instance:
        try:
            search_results = ydl_instance.extract_info(f"ytsearch:{song_name}", download=False)
            if search_results and 'entries' in search_results:
                first_result = search_results['entries'][0]
                audio_url = first_result['url']
                title = first_result['title']
                duration = first_result['duration']
                return audio_url, title, duration
            else:
                print("No results found for the provided song name.")
                return None, None, None
        except Exception as e:
            print(f"Error: {e}")
            return None, None, None

# Function to fetch Spotify info
def get_spotify_info(song_name):
    try:
        results = sp.search(q=song_name, limit=1, type='track')
        if results['tracks']['items']:
            track = results['tracks']['items'][0]
            artist_name = track['artists'][0]['name']
            album_name = track['album']['name']
            album_cover_url = track['album']['images'][0]['url']
            return artist_name, album_name, album_cover_url
        else:
            return None, None, None
    except Exception as e:
        print(f"Spotify API Error: {e}")
        return None, None, None

# LRU Cache decorator to cache song details
@lru_cache(maxsize=128)
def fetch_song_details(song_name):
    audio_url, title, duration = get_audio_info(song_name)
    artist_name, album_name, album_cover_url = get_spotify_info(song_name)
    if audio_url and title and duration and artist_name and album_name and album_cover_url:
        return {
            'audio_url': audio_url,
            'title': title,
            'artist_name': artist_name,
            'album_name': album_name,
            'album_cover_url': album_cover_url,
            'duration': duration
        }
    else:
        return None

@app.after_request
def add_newline(response):
    """Add a newline after every response."""
    print()  # Print an empty line to stdout (logs)
    return response

@app.route('/setup', methods=['GET'])
def first_time_setup():
    username = request.args.get('username')
    ip_address = request.args.get('ip')

    if username:
        print(f"Request received from user '{username}' with IP address '{ip_address}'")
        return jsonify({'message': 'Request received successfully'}), 200
    else:
        return jsonify({'error': 'Username parameter is required'}), 400

@app.route('/search', methods=['GET'])
def search_song():
    song_name = request.args.get('q')
    ip_address = request.remote_addr
    if not song_name:
        return jsonify({'error': 'q parameter is required'}), 400

    # Print the IP address and requested song name
    print(f"IP: {ip_address} requested for {song_name}")

    # Check if song details are already cached
    song_details = fetch_song_details(song_name)
    if song_details:
        print(f"Song details found in cache for: {song_name}")
        return jsonify(song_details), 200
    else:
        print(f"Fetching song details from sources for: {song_name}")
        # Fetch song details if not in cache
        song_details = {
            'audio_url': None,
            'title': None,
            'artist_name': None,
            'album_name': None,
            'album_cover_url': None,
            'duration': None
        }
        audio_url, title, duration = get_audio_info(song_name)
        if audio_url and title and duration:
            song_details['audio_url'] = audio_url
            song_details['title'] = title
            song_details['duration'] = duration

        artist_name, album_name, album_cover_url = get_spotify_info(song_name)
        if artist_name and album_name and album_cover_url:
            song_details['artist_name'] = artist_name
            song_details['album_name'] = album_name
            song_details['album_cover_url'] = album_cover_url

        # Cache the fetched song details
        if song_details['audio_url'] and song_details['title'] and song_details['duration']:
            fetch_song_details.cache_clear()  # Clear cache before setting new entry
            fetch_song_details(song_name)  # Add to cache

        return jsonify(song_details), 200

@app.route('/download', methods=['GET'])
def download_song():
    song_name = request.args.get('q')
    if not song_name:
        return jsonify({'error': 'q parameter is required'}), 400

    # Fetch audio URL using yt-dlp
    audio_url, title, _ = get_audio_info(song_name)
    if not audio_url:
        return jsonify({'error': 'Failed to fetch audio URL'}), 500

    try:
        # Stream the file content from the audio URL
        with requests.get(audio_url, stream=True) as r:
            r.raise_for_status()
            # Specify the path where the file should be saved on the client side
            client_download_path = 'houston/songs/' + title + '.mp3'
            with open(client_download_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)

        return jsonify({'message': 'Song downloaded successfully', 'file_path': client_download_path}), 200
    except requests.exceptions.RequestException as e:
        print(f"Error downloading song: {e}")
        return jsonify({'error': 'Failed to download song'}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
