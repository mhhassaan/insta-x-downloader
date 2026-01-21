# Insta-X Downloader

[![Python Version](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![Flask](https://img.shields.io/badge/flask-2.x-green.svg)](https://flask.palletsprojects.com/)

A simple yet powerful web application built with Flask that allows you to download videos and images from Instagram and X (formerly Twitter) posts directly from your browser.

---

## ✨ Key Features

- **Dual Platform Support**: Seamlessly download media from both **Instagram** and **X (Twitter)**.
- **User-Friendly Web UI**: A clean, minimalistic interface for pasting URLs and managing downloads.
- **Asynchronous Operations**: Downloads are handled in background threads, ensuring the UI remains responsive and non-blocking.
- **Real-Time Progress Tracking**: The frontend polls the server to provide live status updates for each download job (e.g., `pending`, `downloading`, `completed`, `failed`).
- **Instant Media Previews**: Once a download is complete, you can preview images and videos directly on the page.
- **Organized File Naming**: Files are saved in a clean and organized format: `username_date_number.extension`.
- **Direct Download Links**: Get direct links to download the saved media files.
- **Vercel Ready**: Comes pre-configured with a `vercel.json` file for effortless, one-command deployment.

## ⚙️ How It Works

The application's logic is straightforward:

1.  **URL Submission**: A user pastes a valid Instagram or X/Twitter post URL into the input field on the homepage.
2.  **Backend Job Creation**: The frontend sends an asynchronous request to the `/download` endpoint. The Flask backend receives the URL, creates a unique `job_id` for the request, and spins up a new background thread to handle the download. This immediately frees up the main thread and returns the `job_id` to the user.
3.  **Media Scraping**:
    -   For **Instagram** URLs, the powerful `instaloader` library is used to log in (if required for private accounts) and fetch the media.
    -   For **X/Twitter** URLs, the versatile `yt-dlp` library is used to extract and download the video or images.
4.  **Status Polling**: The frontend uses the received `job_id` to periodically make requests to the `/job/<job_id>` endpoint to check the current status of the download.
5.  **Displaying Results**: Once the job status changes to `completed`, the frontend receives the paths to the downloaded files. It then dynamically renders these files as previews (using `<img>` or `<video>` tags) along with direct download links.

## 🚀 Getting Started Locally

Follow these steps to set up and run the project on your local machine.

### Prerequisites

-   Python 3.9 or newer
-   `pip` (Python package installer)

### Installation

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/your-username/insta-x-flask-downloader.git
    cd insta-x-flask-downloader
    ```

2.  **Create and activate a virtual environment:**
    ```bash
    # For macOS/Linux
    python3 -m venv venv
    source venv/bin/activate

    # For Windows
    python -m venv venv
    venv\Scripts\activate
    ```

3.  **Install the required dependencies:**
    The project's dependencies are listed in the `requirements.txt` file.
    ```bash
    pip install -r requirements.txt
    ```

4.  **Run the Flask application:**
    ```bash
    flask run
    ```
    The application will now be running and accessible at `http://127.0.0.1:5000`.

## ☁️ Deployment

This project is configured for easy deployment on **Vercel**.

The `vercel.json` file in the root directory tells Vercel how to build and serve the Flask application.

```json
{
    "version": 2,
    "builds": [
      { 
        "src": "app.py", 
        "use": "@vercel/python" 
      }
    ],
    "routes": [
      { 
        "src": "/(.*)", 
        "dest": "app.py" 
      }
    ]
}
