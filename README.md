Insta-X Downloader

A simple yet powerful web application built with Flask that allows you to download videos and images from Instagram and X (formerly Twitter) posts directly from your browser.
✨ Key Features

    Dual Platform Support: Seamlessly download media from both Instagram and X (Twitter).

    User-Friendly Web UI: A clean, minimalistic interface for pasting URLs and managing downloads.

    Asynchronous Operations: Downloads are handled in background threads, ensuring the UI remains responsive and non-blocking.

    Real-Time Progress Tracking: The frontend polls the server to provide live status updates for each download job (e.g., pending, downloading, completed, failed).

    Instant Media Previews: Once a download is complete, you can preview images and videos directly on the page.

    Direct Download Links: Get direct links to download the saved media files.

    Vercel Ready: Comes pre-configured with a vercel.json file for effortless, one-command deployment.

⚙️ How It Works

The application's logic is straightforward:

    URL Submission: A user pastes a valid Instagram or X/Twitter post URL into the input field on the homepage.

    Backend Job Creation: The frontend sends an asynchronous request to the /download endpoint. The Flask backend receives the URL, creates a unique job_id for the request, and spins up a new background thread to handle the download. This immediately frees up the main thread and returns the job_id to the user.

    Media Scraping:

        For Instagram URLs, the powerful instaloader library is used to log in (if required for private accounts) and fetch the media.

        For X/Twitter URLs, the versatile yt-dlp library is used to extract and download the video or images.

    Status Polling: The frontend uses the received job_id to periodically make requests to the /job/<job_id> endpoint to check the current status of the download.

    Displaying Results: Once the job status changes to completed, the frontend receives the paths to the downloaded files. It then dynamically renders these files as previews (using <img> or <video> tags) along with direct download links.

🚀 Getting Started Locally

Follow these steps to set up and run the project on your local machine.
Prerequisites

    Python 3.9 or newer

    pip (Python package installer)

Installation

    Clone the repository:

    git clone https://github.com/your-username/insta-x-flask-downloader.git
    cd insta-x-flask-downloader

    Create and activate a virtual environment:

    # For macOS/Linux
    python3 -m venv venv
    source venv/bin/activate

    # For Windows
    python -m venv venv
    venv\Scripts\activate

    Install the required dependencies:
    The project's dependencies are listed in the requirements.txt file.

    pip install -r requirements.txt

    Run the Flask application:

    flask run

    The application will now be running and accessible at http://127.0.0.1:5000.

☁️ Deployment

This project is configured for easy deployment on Vercel.

The vercel.json file in the root directory tells Vercel how to build and serve the Flask application.

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

To deploy your application, install the Vercel CLI and run the vercel command from the project's root directory.

npm install -g vercel
vercel

Follow the on-screen prompts, and your application will be live in minutes!
🔧 Project Structure

.
├── app.py              # Main Flask application file with all backend logic.
├── requirements.txt    # List of Python dependencies for pip.
├── vercel.json         # Configuration file for Vercel deployment.
├── templates/
│   └── index.html      # The single HTML file for the user interface.
└── static/             # Directory where downloaded media is saved.

🤝 Contributing

Contributions are welcome! If you have ideas for new features or improvements, feel free to fork the repository, make your changes, and submit a pull request.

    Fork the repository.

    Create a new branch (git checkout -b feature/AmazingFeature).

    Commit your changes (git commit -m 'Add some AmazingFeature').

    Push to the branch (git push origin feature/AmazingFeature).

    Open a Pull Request.

📝 License

This project is licensed under the MIT License. See the LICENSE file for details.
