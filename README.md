# Workstation Dashboard with Authentication

This is a Flask-based web application for managing workstation usage requests. It includes user registration, login, and a dashboard to submit and view requests.

## Features

- User authentication (register/login/logout)
- Submit workstation usage requests
- View pending requests in a table
- REST API for submitting requests
- SQLite database

## Setup

1. Clone the repository
2. Install dependencies: `pip install -r requirements.txt`
3. Run the app: `python app.py`
4. Access the app at `http://localhost:5000`

## Deployment

To deploy on Render:
- Connect your GitHub repo
- Set build command: `pip install -r requirements.txt`
- Set start command: `gunicorn app:app`