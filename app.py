# app.py
from flask import Flask, render_template, request, jsonify, send_from_directory, redirect, url_for, after_this_request
from flask_socketio import SocketIO, emit
import os
import yt_dlp as ytdlp
from datetime import datetime
import subprocess
import re
import json
import tempfile
import shutil
import logging
import threading
import time
import instaloader
import stat

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['SECRET_KEY'] = 'instax_secret_key_2026'
# Using default async_mode (threading) for best local compatibility on Windows
socketio = SocketIO(app, cors_allowed_origins="*")

# Create directories if they don't exist
if os.environ.get('VERCEL'):
    DOWNLOAD_DIR = '/tmp/downloads'
else:
    DOWNLOAD_DIR = os.path.join(os.getcwd(), 'downloads')

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Store background jobs
background_jobs = {}
# Store all generated files for session cleanup
generated_files = set()

def log_to_socket(job_id, message, type='info'):
    """Emit a log message to the frontend console via Socket.IO"""
    socketio.emit('system_log', {
        'job_id': job_id,
        'message': message,
        'type': type
    })

def get_file_size(path):
    """Get formatted file size"""
    try:
        size = os.path.getsize(path)
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024.0:
                return f"{size:.2f} {unit}"
            size /= 1024.0
    except:
        return "N/A"

# Configure FFmpeg Path
def get_ffmpeg_path():
    system_path = shutil.which('ffmpeg')
    if system_path: return system_path
    local_bin_dir = os.path.join(os.getcwd(), 'bin')
    candidates = [os.path.join(local_bin_dir, 'ffmpeg'), os.path.join(local_bin_dir, 'ffmpeg.exe')]
    for candidate in candidates:
        if os.path.exists(candidate): return candidate
    return None

FFMPEG_PATH = get_ffmpeg_path()

def clean_filename(filename):
    cleaned = re.sub(r'[\\/*?:\"<>|]', '_', filename)
    return ' '.join(cleaned.split())

def track_file(filename):
    generated_files.add(filename)

def download_instagram(url, job_id):
    try:
        log_to_socket(job_id, "ESTABLISHING CONNECTION: instagram.com", "info")
        temp_dir = tempfile.mkdtemp()
        job_info = background_jobs[job_id]
        job_info['status'] = 'downloading'

        shortcode_match = re.search(r'instagram\.com/p/([^/]+)', url) or re.search(r'instagram\.com/reel/([^/]+)', url)
        if not shortcode_match:
            log_to_socket(job_id, "ERROR: INVALID POST ID", "error")
            job_info['status'] = 'failed'
            return

        shortcode = shortcode_match.group(1).rstrip('/')
        log_to_socket(job_id, f"METADATA EXTRACTED: ID {shortcode}", "acid")

        L = instaloader.Instaloader(dirname_pattern=temp_dir, download_videos=True, quiet=True)
        post = instaloader.Post.from_shortcode(L.context, shortcode)
        username = post.owner_username
        log_to_socket(job_id, f"SOURCE IDENTIFIED: @{username.upper()}", "acid")
        
        log_to_socket(job_id, "EXTRACTING RESOURCES...", "info")
        L.download_post(post, target=temp_dir)

        # Filter files: If a video exists for an ID, skip the JPG (thumbnail) for that same ID
        all_files = []
        for root, _, files in os.walk(temp_dir):
            for file in files:
                if file.endswith(('.jpg', '.mp4', '.webp')):
                    all_files.append(os.path.join(root, file))
        
        # Group by base name (instaloader usually uses the same base name for video and its thumb)
        # e.g. 2024-03-19_12-00-00_UTC.mp4 and 2024-03-19_12-00-00_UTC.jpg
        video_bases = {os.path.splitext(os.path.basename(f))[0] for f in all_files if f.endswith('.mp4')}
        
        downloaded_files = []
        for f in all_files:
            base = os.path.splitext(os.path.basename(f))[0]
            if f.endswith('.jpg') and base in video_bases:
                continue # Skip thumbnail if we have the video
            downloaded_files.append(f)

        current_date = datetime.now().strftime("%Y%m%d")
        result_files = []
        for i, file_path in enumerate(downloaded_files):
            _, ext = os.path.splitext(file_path)
            new_filename = f"{clean_filename(username)}_{current_date}_{i+1}{ext}"
            new_path = os.path.join(DOWNLOAD_DIR, new_filename)
            shutil.copy2(file_path, new_path)
            size = get_file_size(new_path)
            log_to_socket(job_id, f"SAVED: {new_filename} ({size})", "acid")
            result_files.append({"filename": new_filename})
            track_file(new_filename)

        job_info['status'] = 'completed'
        job_info['files'] = result_files
        shutil.rmtree(temp_dir)
    except Exception as e:
        log_to_socket(job_id, f"CRITICAL FAILURE: {str(e)}", "error")
        if job_id in background_jobs: background_jobs[job_id]['status'] = 'failed'

def download_twitter(url, job_id):
    try:
        log_to_socket(job_id, "ESTABLISHING CONNECTION: x.com", "info")
        temp_dir = tempfile.mkdtemp()
        job_info = background_jobs[job_id]
        job_info['status'] = 'downloading'

        username_match = re.search(r'twitter\.com/([^/]+)', url) or re.search(r'x\.com/([^/]+)', url)
        username = username_match.group(1) if username_match else "twitter_user"
        log_to_socket(job_id, f"METADATA EXTRACTED: SOURCE @{username.upper()}", "acid")

        output_template = os.path.join(temp_dir, f"%(id)s.%(ext)s")
        # Ensure we only download the best video format and skip others
        ydl_opts = {
            'outtmpl': output_template, 
            'quiet': True, 
            'noplaylist': True,
            'format': 'bestvideo+bestaudio/best', # Merge best video and audio
            'writethumbnail': False # Explicitly disable thumbnails to avoid duplicates
        }
        if FFMPEG_PATH: ydl_opts['ffmpeg_location'] = FFMPEG_PATH

        log_to_socket(job_id, "EXTRACTING RESOURCES...", "info")
        with ytdlp.YoutubeDL(ydl_opts) as ydl:
            ydl.extract_info(url, download=True)

        downloaded_files = []
        for root, _, files in os.walk(temp_dir):
            for file in files:
                if file.endswith(('.mp4', '.webp', '.png', '.webm', '.jpg')):
                    downloaded_files.append(os.path.join(root, file))

        current_date = datetime.now().strftime("%Y%m%d")
        result_files = []
        for i, file_path in enumerate(downloaded_files):
            _, ext = os.path.splitext(file_path)
            new_filename = f"{clean_filename(username)}_{current_date}_{i+1}{ext}"
            new_path = os.path.join(DOWNLOAD_DIR, new_filename)
            shutil.copy2(file_path, new_path)
            size = get_file_size(new_path)
            log_to_socket(job_id, f"SAVED: {new_filename} ({size})", "acid")
            result_files.append({"filename": new_filename})
            track_file(new_filename)

        job_info['status'] = 'completed'
        job_info['files'] = result_files
        shutil.rmtree(temp_dir)
    except Exception as e:
        log_to_socket(job_id, f"CRITICAL FAILURE: {str(e)}", "error")
        if job_id in background_jobs: background_jobs[job_id]['status'] = 'failed'

@app.route('/')
def index(): return render_template('index.html')

@app.route('/download', methods=['POST'])
def download():
    data = request.get_json()
    url = data.get('url', '')
    if not url: return jsonify({"error": "No URL provided"})
    job_id = str(int(time.time() * 1000))
    background_jobs[job_id] = {'status': 'pending', 'url': url}
    
    # Run synchronously for Vercel compatibility, but socket will stream progress
    if 'instagram.com' in url: download_instagram(url, job_id)
    elif 'twitter.com' in url or 'x.com' in url: download_twitter(url, job_id)
    else: return jsonify({"error": "Unsupported platform"})
    
    return jsonify(background_jobs[job_id])

@app.route('/get_file/<filename>')
def get_file(filename):
    return send_from_directory(DOWNLOAD_DIR, filename)

@app.route('/crop', methods=['POST'])
def crop_video():
    data = request.get_json()
    filename = data.get('filename')
    x, y, w, h = int(data.get('x', 0)), int(data.get('y', 0)), int(data.get('width', 0)), int(data.get('height', 0))
    start_time, end_time = data.get('start_time'), data.get('end_time')
    
    job_id = "crop_" + str(int(time.time()))
    log_to_socket(job_id, f"INITIATING PROCESSING: {filename}", "info")

    input_path = os.path.join(DOWNLOAD_DIR, filename)
    name, ext = os.path.splitext(filename)
    output_filename = f"{name}_processed_{int(time.time())}{ext}"
    output_path = os.path.join(DOWNLOAD_DIR, output_filename)
    
    filter_str = f"crop={w}:{h}:{x}:{y}"
    command = [FFMPEG_PATH, '-y']
    if start_time: command.extend(['-ss', str(start_time)])
    if end_time: command.extend(['-to', str(end_time)])
    command.extend(['-i', input_path, '-vf', filter_str, '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-preset', 'ultrafast', output_path])
    
    try:
        log_to_socket(job_id, "RUNNING FFMPEG TRANSCODE...", "info")
        subprocess.run(command, capture_output=True, text=True)
        size = get_file_size(output_path)
        log_to_socket(job_id, f"PROCESSING SUCCESS: {output_filename} ({size})", "acid")
        track_file(output_filename)
        return jsonify({"success": True, "filename": output_filename})
    except Exception as e:
        log_to_socket(job_id, f"FFMPEG FAILURE: {str(e)}", "error")
        return jsonify({"error": str(e)}), 500

@app.route('/cleanup_session', methods=['POST'])
def cleanup_session():
    for filename in list(generated_files):
        path = os.path.join(DOWNLOAD_DIR, filename)
        if os.path.exists(path):
            try: os.remove(path); generated_files.remove(filename)
            except: pass
    return jsonify({"success": True})

@app.route('/clear_job/<job_id>', methods=['POST'])
def clear_job(job_id):
    if job_id in background_jobs: del background_jobs[job_id]
    return jsonify({"success": True})

if __name__ == '__main__':
    socketio.run(app, debug=True)
