# app.py
from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for
import os
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

# Set up logging
logging.basicConfig(level=logging.DEBUG, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Create directories if they don't exist
DOWNLOAD_DIR = '/tmp/downloads'
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Store background jobs
background_jobs = {}

def clean_filename(filename):
    """Clean filename to ensure it's valid for the filesystem"""
    # Replace invalid characters with underscores
    cleaned = re.sub(r'[\\/*?:"<>|]', '_', filename)
    # Remove extra whitespace
    cleaned = ' '.join(cleaned.split())
    return cleaned

def download_instagram(url, job_id):
    """Download media from Instagram using instaloader Python library"""
    try:
        import instaloader
        
        logger.info(f"Processing Instagram URL: {url}")
        
        # Create a temporary directory for instaloader output
        temp_dir = tempfile.mkdtemp()
        job_info = background_jobs[job_id]
        job_info['status'] = 'downloading'
        
        # Extract post shortcode from URL
        shortcode_match = re.search(r'instagram\.com/p/([^/]+)', url) or re.search(r'instagram\.com/reel/([^/]+)', url)
        
        if not shortcode_match:
            job_info['status'] = 'failed'
            job_info['error'] = "Could not extract post ID from URL"
            logger.error("Could not extract post ID from Instagram URL")
            return
        
        shortcode = shortcode_match.group(1)
        # Remove trailing slash if present
        shortcode = shortcode.rstrip('/')
        logger.info(f"Instagram post ID: {shortcode}")
        
        # Create instaloader instance
        L = instaloader.Instaloader(
            dirname_pattern=temp_dir,
            download_videos=True,
            download_video_thumbnails=False,
            download_geotags=False,
            download_comments=False,
            save_metadata=False,
            quiet=True
        )
        
        # Optional: Login (if needed)
        # L.login("your_username", "your_password")
        
        # Download the post
        post = instaloader.Post.from_shortcode(L.context, shortcode)
        L.download_post(post, target=temp_dir)
        
        # Find all files in the temp directory
        downloaded_files = []
        username = post.owner_username
        
        for root, _, files in os.walk(temp_dir):
            for file in files:
                if file.endswith(('.jpg', '.mp4', '.webp')):
                    file_path = os.path.join(root, file)
                    downloaded_files.append(file_path)
        
        if not downloaded_files:
            logger.error("No media files downloaded from Instagram")
            job_info['status'] = 'failed'
            job_info['error'] = "No media files found in the Instagram post"
            return
        
        # If we couldn't extract username, use a default
        if not username:
            username = "instagram_user"
        
        # Move files to downloads directory with proper naming
        current_date = datetime.now().strftime("%Y%m%d")
        result_files = []
        
        for i, file_path in enumerate(downloaded_files):
            # Get file extension
            _, ext = os.path.splitext(file_path)
            
            # Create new filename: username_date_number.ext
            new_filename = f"{clean_filename(username)}_{current_date}_{i+1}{ext}"
            new_path = os.path.join(DOWNLOAD_DIR, new_filename)
            
            # Copy the file (using copy2 to preserve metadata)
            shutil.copy2(file_path, new_path)
            logger.info(f"Saved Instagram media as: {new_filename}")
            
            result_files.append({"filename": new_filename, "path": new_path})
        
        # Update job info
        job_info['status'] = 'completed'
        job_info['files'] = result_files
        job_info['username'] = username
        
        # Clean up temporary directory
        shutil.rmtree(temp_dir)
        
    except Exception as e:
        logger.error(f"Error downloading from Instagram: {str(e)}")
        job_info = background_jobs.get(job_id)
        if job_info:
            job_info['status'] = 'failed'
            job_info['error'] = f"Error: {str(e)}"

def download_twitter(url, job_id):
    """Download media from Twitter using yt-dlp"""
    try:
        logger.info(f"Processing Twitter URL: {url}")
        
        # Create a temporary directory for yt-dlp output
        temp_dir = tempfile.mkdtemp()
        job_info = background_jobs[job_id]
        job_info['status'] = 'downloading'
        
        # Extract username from URL if possible
        username_match = re.search(r'twitter\.com/([^/]+)', url) or re.search(r'x\.com/([^/]+)', url)
        username = username_match.group(1) if username_match else "twitter_user"
        
        if username in ['i', 'search', 'hashtag', 'explore']:
            username = "twitter_user"  # Use generic name for non-profile URLs
        
        logger.info(f"Twitter username: {username}")
        
        # Prepare output template for yt-dlp
        current_date = datetime.now().strftime("%Y%m%d")
        output_template = os.path.join(temp_dir, f"%(id)s.%(ext)s")
        
        # Run yt-dlp to download the media
        command = [
            'yt-dlp',
            '--no-warnings',
            '--no-progress',
            '--no-playlist',
            '-o', output_template,
            url
        ]
        
        logger.debug(f"Running command: {' '.join(command)}")
        
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        stdout, stderr = process.communicate()
        
        if process.returncode != 0:
            logger.error(f"yt-dlp error: {stderr}")
            job_info['status'] = 'failed'
            job_info['error'] = f"yt-dlp error: {stderr}"
            return
        
        # Find all files in the temp directory
        downloaded_files = []
        
        for root, _, files in os.walk(temp_dir):
            for file in files:
                if file.endswith(('.jpg', '.mp4', '.webp', '.png', '.webm')):
                    file_path = os.path.join(root, file)
                    downloaded_files.append(file_path)
        
        if not downloaded_files:
            logger.error("No media files downloaded from Twitter")
            job_info['status'] = 'failed'
            job_info['error'] = "No media files found in the Twitter post"
            return
        
        # Move files to downloads directory with proper naming
        result_files = []
        
        for i, file_path in enumerate(downloaded_files):
            # Get file extension
            _, ext = os.path.splitext(file_path)
            
            # Create new filename: username_date_number.ext
            new_filename = f"{clean_filename(username)}_{current_date}_{i+1}{ext}"
            new_path = os.path.join(DOWNLOAD_DIR, new_filename)
            
            # Copy the file (using copy2 to preserve metadata)
            shutil.copy2(file_path, new_path)
            logger.info(f"Saved Twitter media as: {new_filename}")
            
            result_files.append({"filename": new_filename, "path": new_path})
        
        # Update job info
        job_info['status'] = 'completed'
        job_info['files'] = result_files
        job_info['username'] = username
        
        # Clean up temporary directory
        shutil.rmtree(temp_dir)
        
    except Exception as e:
        logger.error(f"Error downloading from Twitter: {str(e)}")
        job_info = background_jobs.get(job_id)
        if job_info:
            job_info['status'] = 'failed'
            job_info['error'] = f"Error: {str(e)}"

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/download', methods=['POST'])
def download():
    data = request.get_json()
    url = data.get('url', '')
    
    if not url:
        return jsonify({"error": "No URL provided"})
    
    logger.info(f"Processing download request for URL: {url}")
    
    # Generate a job ID
    job_id = str(int(time.time() * 1000))
    
    # Initialize job info
    background_jobs[job_id] = {
        'status': 'pending',
        'url': url,
        'timestamp': datetime.now().isoformat()
    }
    
    # Start download in background thread
    if 'instagram.com' in url:
        thread = threading.Thread(target=download_instagram, args=(url, job_id))
        thread.daemon = True
        thread.start()
    elif 'twitter.com' in url or 'x.com' in url:
        thread = threading.Thread(target=download_twitter, args=(url, job_id))
        thread.daemon = True
        thread.start()
    else:
        return jsonify({"error": "URL must be from Instagram or Twitter"})
    
    return jsonify({"job_id": job_id, "status": "pending"})

@app.route('/job/<job_id>', methods=['GET'])
def check_job(job_id):
    if job_id not in background_jobs:
        return jsonify({"error": "Job not found"}), 404
    
    job_info = background_jobs[job_id]
    return jsonify(job_info)

@app.route('/get_file/<filename>')
def get_file(filename):
    file_path = os.path.join(DOWNLOAD_DIR, filename)
    if os.path.exists(file_path):
        return send_file(file_path, as_attachment=True)
    else:
        return jsonify({"error": "File not found"}), 404

@app.route('/clear_job/<job_id>', methods=['POST'])
def clear_job(job_id):
    if job_id in background_jobs:
        del background_jobs[job_id]
    return jsonify({"success": True})

if __name__ == '__main__':
    app.run(debug=True)