# Flask Jinja App

This is a simple Flask application that uses Jinja2 for templating. The application features a login page and a homepage with a navigation bar that includes links to two tabs: "Coach" and "Athlete".

## Project Structure

```
flask-jinja-app
├── app
│   ├── __init__.py
│   ├── routes.py
│   ├── forms.py
│   ├── models.py
│   ├── templates
│   │   ├── base.html
│   │   ├── login.html
│   │   ├── home.html
│   │   ├── coach.html
│   │   └── athlete.html
│   └── static
│       ├── css
│       │   └── styles.css
│       └── js
│           └── main.js
├── config.py
├── requirements.txt
├── run.py
├── .gitignore
└── README.md
```

## Installation

1. Clone the repository:
   ```
   git clone <repository-url>
   cd flask-jinja-app
   ```

2. Create a virtual environment:
   ```
   python -m venv venv
   ```

3. Activate the virtual environment:
   - On Windows:
     ```
     venv\Scripts\activate
     ```
   - On macOS/Linux:
     ```
     source venv/bin/activate
     ```

4. Install the required packages:
   ```
   pip install -r requirements.txt
   ```

## Usage

1. Run the application:
   ```
   python run.py
   ```

2. Open your web browser and go to `http://127.0.0.1:5000`.

## Features

- User authentication with a login page.
- Homepage with a navigation bar.
- Separate tabs for "Coach" and "Athlete" content.

## License

This project is licensed under the MIT License.