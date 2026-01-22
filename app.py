# app.py
from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for, after_this_request
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
# Only use static_ffmpeg if NOT on Vercel
if not os.environ.get('VERCEL'):
    try:
        import static_ffmpeg
        # Initialize static_ffmpeg to ensure binaries are in path
        static_ffmpeg.add_paths()
    except Exception as e:
        # Just log warning, don't crash app if local ffmpeg setup fails
        logging.getLogger(__name__).warning(f"Failed to initialize static_ffmpeg: {e}")

# Set up logging
logging.basicConfig(level=logging.DEBUG, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

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

import stat

# Configure FFmpeg Path
def get_ffmpeg_path():
    # 1. Check system path
    system_path = shutil.which('ffmpeg')
    if system_path:
        return system_path
    
    # 2. Check local 'bin' directory
    local_bin_dir = os.path.join(os.getcwd(), 'bin')
    
    # Potential candidates
    candidates = [
        os.path.join(local_bin_dir, 'ffmpeg'),      # Linux/Mac
        os.path.join(local_bin_dir, 'ffmpeg.exe')   # Windows
    ]
    
    for candidate in candidates:
        if os.path.exists(candidate):
            # If on Linux/Posix, ensure it's executable
            if os.name == 'posix':
                if os.access(candidate, os.X_OK):
                    return candidate
                else:
                    # It exists but isn't executable (likely Git/Windows permission issue)
                    # We cannot chmod in /var/task (Read-only), so copy to /tmp
                    try:
                        logger.info(f"Found ffmpeg at {candidate} but valid permissions missing. Copying to /tmp...")
                        tmp_ffmpeg = os.path.join(tempfile.gettempdir(), 'ffmpeg_exec')
                        
                        # Only copy if not already there or if we want to ensure freshness
                        if not os.path.exists(tmp_ffmpeg):
                            shutil.copy2(candidate, tmp_ffmpeg)
                            # Add execute permission
                            st = os.stat(tmp_ffmpeg)
                            os.chmod(tmp_ffmpeg, st.st_mode | stat.S_IEXEC)
                            logger.info(f"Copied ffmpeg to {tmp_ffmpeg} and made executable")
                        
                        return tmp_ffmpeg
                    except Exception as e:
                        logger.error(f"Failed to setup ffmpeg in /tmp: {e}")
                        # Fallback to original, might fail but worth a shot
                        return candidate
            else:
                return candidate

    return None

FFMPEG_PATH = get_ffmpeg_path()

# Startup Check for FFmpeg
if not FFMPEG_PATH:
    logger.warning("CRITICAL: 'ffmpeg' command not found. Cropping and some downloads may fail.")
else:
    logger.info(f"FFmpeg found at: {FFMPEG_PATH}")

def clean_filename(filename):
    """Clean filename to ensure it's valid for the filesystem"""
    # Replace invalid characters with underscores
    cleaned = re.sub(r'[\\/*?:\"<>|]', '_', filename)
    # Remove extra whitespace
    cleaned = ' '.join(cleaned.split())
    return cleaned

def track_file(filename):
    """Add filename to the tracking set"""
    generated_files.add(filename)

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
            track_file(new_filename)
        
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
    """Download media from Twitter using yt-dlp library"""
    try:
        # Check if the URL is None or invalid
        if not url:
            logger.error("Invalid or None URL provided.")
            raise ValueError("Invalid URL")

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
        
        # yt-dlp options for downloading
        ydl_opts = {
            'outtmpl': output_template,
            'quiet': True,
            'no_warnings': True,
            'noplaylist': True,
        }
        
        if FFMPEG_PATH:
            ydl_opts['ffmpeg_location'] = FFMPEG_PATH

        # Create a yt-dlp object
        with ytdlp.YoutubeDL(ydl_opts) as ydl:
            logger.debug(f"Downloading media from URL: {url}")
            try:
                info_dict = ydl.extract_info(url, download=True)
            except Exception as e:
                logger.error(f"Error extracting info from URL: {str(e)}")
                raise e

        # Check if info_dict is None or doesn't contain the necessary data
        if not info_dict:
            logger.error("Failed to extract information from the URL.")
            job_info['status'] = 'failed'
            job_info['error'] = "Failed to extract media info from the URL."
            return
        
        # Find all files in the temp directory
        downloaded_files = []
        for root, _, files in os.walk(temp_dir):
            for file in files:
                if file.endswith(('.jpg', '.mp4', '.webp', '.png', '.webm', '.gif')):
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
            track_file(new_filename)
        
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
    
    # Run download SYNCHRONOUSLY (blocking) to prevent Vercel freezing background threads
    try:
        if 'instagram.com' in url:
            download_instagram(url, job_id)
        elif 'twitter.com' in url or 'x.com' in url:
            download_twitter(url, job_id)
        else:
            return jsonify({"error": "URL must be from Instagram or Twitter"})
    except Exception as e:
        logger.error(f"Download failed with exception: {e}")
        background_jobs[job_id]['status'] = 'failed'
        background_jobs[job_id]['error'] = str(e)

    # Return the current status (should be 'completed' or 'failed' by now)
    job_info = background_jobs[job_id]
    
    # Return 200 even if failed, frontend handles the status
    return jsonify(job_info)

@app.route('/job/<job_id>', methods=['GET'])
def check_job(job_id):
    if job_id not in background_jobs:
        return jsonify({"error": "Job not found"}), 404
    
    job_info = background_jobs[job_id]
    return jsonify(job_info)

@app.route('/get_file/<filename>')
def get_file(filename):
    file_path = os.path.join(DOWNLOAD_DIR, filename)  # use /tmp
    if os.path.exists(file_path):
        return send_file(file_path)  # no "as_attachment", allow inline preview
    else:
        return jsonify({"error": "File not found"}), 404


import io

@app.route('/download_and_delete/<filename>')
def download_and_delete(filename):
    file_path = os.path.join(DOWNLOAD_DIR, filename)
    if not os.path.exists(file_path):
        return jsonify({"error": "File not found"}), 404

    try:
        # Read file into memory
        with open(file_path, 'rb') as f:
            file_data = io.BytesIO(f.read())
        
        # Delete file from disk immediately
        os.remove(file_path)
        logger.info(f"Deleted file (loaded to memory): {filename}")
        
        # Remove from tracking set
        if filename in generated_files:
            generated_files.remove(filename)

        # Serve from memory
        return send_file(
            file_data,
            as_attachment=True,
            download_name=filename,
            mimetype='application/octet-stream'
        )

    except Exception as e:
        logger.error(f"Error in download_and_delete: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/clear_job/<job_id>', methods=['POST'])
def clear_job(job_id):
    if job_id in background_jobs:
        del background_jobs[job_id]
    return jsonify({"success": True})

@app.route('/cleanup_session', methods=['POST'])
def cleanup_session():
    """Delete all files generated in this session"""
    count = 0
    # Create a copy to iterate while modifying
    for filename in list(generated_files):
        file_path = os.path.join(DOWNLOAD_DIR, filename)
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
                logger.info(f"Cleaned up file: {filename}")
                generated_files.remove(filename)
                count += 1
            except OSError as e:
                logger.error(f"Failed to cleanup {filename}: {e}")
        else:
            # File might have been downloaded and deleted already
            generated_files.remove(filename)
            
    return jsonify({"success": True, "count": count})

@app.route('/crop', methods=['POST'])
def crop_video():
    data = request.get_json()
    filename = data.get('filename')
    x = int(data.get('x'))
    y = int(data.get('y'))
    w = int(data.get('width'))
    h = int(data.get('height'))
    
    if not filename:
        return jsonify({"error": "No filename provided"}), 400
        
    if not FFMPEG_PATH:
        return jsonify({"error": "FFmpeg is not available on the server."}), 501

    input_path = os.path.join(DOWNLOAD_DIR, filename)
    if not os.path.exists(input_path):
        return jsonify({"error": "File not found"}), 404
        
    # Generate output filename
    name, ext = os.path.splitext(filename)
    output_filename = f"{name}_cropped_{int(time.time())}{ext}"
    output_path = os.path.join(DOWNLOAD_DIR, output_filename)
    
    # Construct ffmpeg command
    # crop=w:h:x:y
    filter_str = f"crop={w}:{h}:{x}:{y}"
    
    command = [
        FFMPEG_PATH,
        '-y', # Overwrite output files without asking
        '-i', input_path,
        '-vf', filter_str,
        '-c:a', 'copy', # Copy audio stream without re-encoding
        output_path
    ]
    
    try:
        logger.info(f"Running crop command: {' '.join(command)}")
        result = subprocess.run(command, capture_output=True, text=True)
        
        if result.returncode != 0:
            logger.error(f"FFmpeg failed: {result.stderr}")
            return jsonify({"error": f"FFmpeg failed: {result.stderr}"}), 500
            
        # Track the new file
        track_file(output_filename)
        return jsonify({"success": True, "filename": output_filename})
        
    except Exception as e:
        logger.error(f"Error executing crop: {str(e)}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)
