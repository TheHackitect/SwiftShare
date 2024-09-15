import os
import socket
import threading
from flask import Flask, send_from_directory, render_template_string, jsonify, request
import webbrowser
from PIL import Image
import cv2
import base64
import io
import logging
from concurrent.futures import ThreadPoolExecutor
import qrcode
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, QLabel,
    QWidget, QPushButton, QListWidget, QScrollArea, QGroupBox, 
    QFileDialog, QSplitter
)
from user_agents import parse

app = Flask(__name__)
shared_folder = None
connected_devices = []

# Executor for multithreading
executor = ThreadPoolExecutor(max_workers=10)

# Disable logging for Flask
log = logging.getLogger('werkzeug')
log.disabled = True
app.logger.disabled = True

def format_size(size):
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0:
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} TB"

def generate_thumbnail(path):
    ext = os.path.splitext(path)[1].lower()
    thumbnail = None
    if ext in ['.jpg', '.jpeg', '.png', '.gif']:
        image = Image.open(path)
        image.thumbnail((100, 100))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        thumbnail = base64.b64encode(buffer.getvalue()).decode()
    elif ext in ['.mp4', '.avi', '.mov']:
        cap = cv2.VideoCapture(path)
        ret, frame = cap.read()
        if ret:
            _, buffer = cv2.imencode('.png', frame)
            thumbnail = base64.b64encode(buffer).decode()
        cap.release()
    return thumbnail

@app.route('/connect', methods=['POST'])
def connect():
    ip = request.remote_addr
    user_agent = parse(request.headers.get('User-Agent'))
    device_info = {
        'ip': ip,
        'browser': f"{user_agent.browser.family} {user_agent.browser.version_string}",
        'os': f"{user_agent.os.family} {user_agent.os.version_string}"
    }
    
    if device_info not in connected_devices:
        connected_devices.append(device_info)
    return jsonify(success=True)

@app.route('/connected_devices')
def get_connected_devices():
    return jsonify(connected_devices=connected_devices)

@app.route('/', defaults={'subpath': ''})
@app.route('/<path:subpath>')
def index(subpath):
    search_query = request.args.get('search', '').lower()
    if shared_folder:
        folder_path = os.path.join(shared_folder, subpath)
        if not os.path.exists(folder_path):
            return "Folder not found", 404

        files = os.listdir(folder_path)
        file_data = []
        for file in files:
            if search_query and search_query not in file.lower():
                continue
            full_path = os.path.join(folder_path, file)
            file_ext = os.path.splitext(file)[1] if os.path.isfile(full_path) else "Folder"
            file_size = format_size(os.path.getsize(full_path)) if os.path.isfile(full_path) else "-"
            thumbnail = generate_thumbnail(full_path) if os.path.isfile(full_path) else None
            file_data.append({
                'name': file,
                'type': file_ext,
                'size': file_size,
                'path': os.path.join(subpath, file) if subpath else file,
                'thumbnail': thumbnail
            })

        return render_template_string("""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Shared Files</title>
    <style> 
        body {
            font-family: 'Courier New', monospace;
            background: linear-gradient(135deg, #71b7e6, #9b59b6);
            color: #ffffff;
            overflow-x: hidden;
            background-repeat: no-repeat;
            background-attachment: fixed;
            height: 100%;
            margin: 0;
            display: flex;
            flex-direction: column;
        }
        .container {
            display: flex;
            flex-wrap: wrap;
            gap: 20px;
        }
        .card {
            background-color: #2c2c2c69;
            border-radius: 8px;
            padding: 15px;
            width: calc(25% - 20px);
            box-sizing: border-box;
            box-shadow: 0 4px 8px 0 rgb(0 0 0);
            transition: 0.3s;
            overflow: hidden;
        }
        .card:hover {
            box-shadow: 0 8px 16px 0 rgba(0, 0, 0, 0.4);
        }
        .card img {
            width: 100%;
            border-radius: 8px;
            height: auto;
            max-height: 150px;
            object-fit: cover;
        }
        .card h3 {
            font-size: 16px;
            margin: 10px 0;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .card p {
            margin: 5px 0;
            font-size: 14px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .actions {
            margin-top: 10px;
        }
        .button {
            background-color: #4CAF50;
            color: white;
            padding: 8px 12px;
            margin: 5px 0;
            border: none;
            cursor: pointer;
            border-radius: 4px;
            text-align: center;
            text-decoration: none;
            display: inline-block;
            font-size: 14px;
        }
        .button.download {
            background-color: #008CBA;
        }
    </style>
</head>
<body>
    <h2>Shared Files in {{ subpath if subpath else 'Root Directory' }}</h2>
    <form method="GET" action="/" style="margin-bottom: 20px;">
        <input type="text" name="search" placeholder="Search files..." style="padding: 10px; width: 80%;" value="{{ request.args.get('search', '') }}">
        <button type="submit" class="button">Search</button>
    </form>
    <form method="POST" action="/upload" enctype="multipart/form-data" style="margin-bottom: 20px;">
        <input type="file" name="files" multiple style="padding: 10px; width: 80%;">
        <button type="submit" class="button upload">Upload Files</button>
    </form>
    <div class="container">
        {% for file in file_data %}
        <div class="card">
            {% if file['thumbnail'] %}
                <img src="data:image/png;base64,{{ file['thumbnail'] }}" alt="Thumbnail">
            {% endif %}
            <h3>{{ file['name'] }}</h3>
            <p><strong>Type:</strong> {{ file['type'] }}</p>
            <p><strong>Size:</strong> {{ file['size'] }}</p>
            <div class="actions">
                {% if file['type'] == 'Folder' %}
                    <a href="/{{ file['path'] }}" class="button">Open</a>
                {% else %}
                    <a href="/download/{{ file['path'] }}" class="button download">Download</a>
                {% endif %}
            </div>
        </div>
        {% endfor %}
    </div>

    <h3>Connected Devices:</h3>
    <ul id="device-list"></ul>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
    <script src="https://code.jquery.com/jquery-3.6.0.min.js"></script>
    <script>
        function fetchConnectedDevices() {
            fetch('/connected_devices')
                .then(response => response.json())
                .then(data => {
                    const deviceList = document.getElementById('device-list');
                    deviceList.innerHTML = '';
                    data.connected_devices.forEach(ip => {
                        const li = document.createElement('li');
                        li.textContent = ip;
                        deviceList.appendChild(li);
                    });
                });
        }

        fetch('/connect', { method: 'POST' });
        setInterval(fetchConnectedDevices, 5000);
    </script>
    <script>
        $(document).ready(function () {
            let angle = 0;
            function updateGradient() {
                angle = (angle + 1) % 360; // Increment angle and keep it within 0-359
                $('body').css({
                    'background': `linear-gradient(${angle}deg, #71b7e6, #9b59b6)`,
                    'background-repeat': 'no-repeat',
                    'background-attachment': 'fixed'
                });
            }
            setInterval(updateGradient, 10); // Update gradient every 10ms
        });
    </script>
</body>
</html>
        """, file_data=file_data, subpath=subpath)
    else:
        return "No folder selected for sharing."

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'files' not in request.files:
        return "No files part", 400
    files = request.files.getlist('files')
    for file in files:
        if file.filename == '':
            continue
        upload_path = shared_folder
        file.save(os.path.join(upload_path, file.filename))
    return render_template_string("""

<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Success - Redirecting to Home</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css">
    <style>
        body {
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            margin: 0;
            background: linear-gradient(135deg, #71b7e6, #9b59b6);
            font-family: 'Arial', sans-serif;
            color: #fff;
            text-align: center;
        }
        .container {
            padding: 20px;
            background: rgba(0, 0, 0, 0.5);
            border-radius: 10px;
            box-shadow: 0 0 10px rgba(0, 0, 0, 0.3);
        }
        .container h1 {
            font-size: 2.5em;
            margin-bottom: 20px;
        }
        .container p {
            font-size: 1.2em;
        }
        .container .button {
            display: inline-block;
            margin-top: 20px;
            padding: 10px 20px;
            background-color: #3498db;
            color: #fff;
            text-decoration: none;
            border-radius: 5px;
            transition: background-color 0.3s;
        }
        .container .button:hover {
            background-color: #2980b9;
        }
        .container .button i {
            margin-right: 10px;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>File Successfully Uploaded!</h1>
        <p>You are being redirected to the Base Directory</p>
        <a href="/" class="button">
            <i class="fab fa-telegram-plane"></i>Go Back
        </a>
    </div>
    <script>
        setTimeout(function() {
            window.location.href = "/";
        }, 10000);
    </script>
</body>
</html>
""")

@app.route('/download/<path:filename>')
def download(filename):
    return send_from_directory(shared_folder, filename)

def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(0)
    try:
        s.connect(('10.254.254.254', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP

def generate_qr_code(url):
    qr = qrcode.make(url)
    buffer = io.BytesIO()
    qr.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer.read()

class FileSharingApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("File Sharing App")
        self.setGeometry(100, 100, 900, 300)  # Reduced window height

        self.tabs = QWidget(self)
        self.setCentralWidget(self.tabs)
        self.qr_devices_layout = QVBoxLayout(self.tabs)

        self.qr_instructions_splitter = QSplitter(Qt.Orientation.Horizontal)

        self.qr_group = QGroupBox("QR Code for Local Access")
        self.qr_layout = QVBoxLayout()
        self.qr_image_label = QLabel()
        self.qr_image_label.setFixedSize(200, 200)
        self.qr_layout.addWidget(self.qr_image_label)

        self.devices_list = QListWidget()
        self.devices_list.setMaximumHeight(150)
        self.devices_list.setStyleSheet("font-size: 12px;")
        self.qr_layout.addWidget(QLabel("Connected Devices:"))
        self.qr_layout.addWidget(self.devices_list)
        self.qr_group.setLayout(self.qr_layout)

        self.main_splitter = QSplitter(Qt.Orientation.Vertical)

        self.instructions_group = QGroupBox("Instructions for Usage")
        self.instructions_layout = QVBoxLayout()
        self.instructions_text = QLabel(
            "1. Connect to the same Wi-Fi network as the host device.\n"
            "2. Start share and Scan the QR code or visit the displayed URL.\n"
            "3. Access and manage shared files seamlessly.\n\n"
            "Note: This app is open-source and welcomes contributions!"
        )
        self.instructions_text.setStyleSheet("font-size: 16px;")
        self.instructions_text.setWordWrap(True)
        self.instructions_layout.addWidget(self.instructions_text)
        self.instructions_group.setLayout(self.instructions_layout)

        self.about_group = QGroupBox("About TheHackitect")
        self.about_layout = QVBoxLayout()
        self.about_text = QLabel(
            "I am a dynamic and innovative programmer with a passion for creating "
            "groundbreaking tech solutions. I specialize in Full stack web development, Python programming, "
            "and automation, constantly pushing the boundaries of technology."
        )
        self.about_text.setStyleSheet("font-size: 16px;")
        self.about_text.setWordWrap(True)
        self.about_layout.addWidget(self.about_text)

        self.social_layout = QHBoxLayout()
        column_count = 3
        buttons = [
            ("GitHub", "https://github.com/TheHackitect"),
            ("Telegram", "https://t.me/thehackitect"),
            ("LinkedIn", "https://linkedin.com/in/thehackitect"),
            ("Instagram", "https://instagram.com/thehackitect.me"),
            ("Twitter", "https://twitter.com/thehackitect"),
            ("WhatsApp", "https://wa.me/+2348036331318"),
            ("Email", "mailto:thehackitect.bots@gmail.com")
        ]
        for index, (name, url) in enumerate(buttons):
            btn = QPushButton(name)
            btn.clicked.connect(lambda _, u=url: webbrowser.open(u))
            btn.setStyleSheet("font-size: 14px;")
            self.social_layout.addWidget(btn)
            if (index + 1) % column_count == 0:
                self.about_layout.addLayout(self.social_layout)
                self.social_layout = QHBoxLayout()

        self.about_group.setLayout(self.about_layout)
        self.main_splitter.addWidget(self.instructions_group)
        self.main_splitter.addWidget(self.about_group)

        self.qr_instructions_splitter.addWidget(self.qr_group)
        self.qr_instructions_splitter.addWidget(self.main_splitter)

        self.control_layout = QHBoxLayout()
        self.start_button = QPushButton("Start Sharing")
        self.start_button.clicked.connect(self.start_server)
        self.stop_button = QPushButton("Stop Sharing")
        self.stop_button.clicked.connect(self.stop_server)
        self.open_browser_button = QPushButton("Open Browser")
        self.open_browser_button.setEnabled(False)
        self.view_source_button = QPushButton("View Source")
        self.view_source_button.clicked.connect(lambda: webbrowser.open("https://github.com/TheHackitect/fileshare-app"))

        button_style = "font-size: 14px; height: 40px;"
        self.start_button.setStyleSheet(button_style)
        self.stop_button.setStyleSheet(button_style)
        self.open_browser_button.setStyleSheet(button_style)
        self.view_source_button.setStyleSheet(button_style)

        self.control_layout.addWidget(self.start_button)
        self.control_layout.addWidget(self.stop_button)
        self.control_layout.addWidget(self.open_browser_button)
        self.control_layout.addWidget(self.view_source_button)

        self.qr_devices_layout.addWidget(self.qr_instructions_splitter)
        self.qr_devices_layout.addLayout(self.control_layout)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_devices_list)
        self.timer.start(2000)

    def start_server(self):
        global shared_folder
        shared_folder = QFileDialog.getExistingDirectory(self, "Select Folder")
        if shared_folder:
            threading.Thread(target=app.run, kwargs={'host': '0.0.0.0', 'port': 5000, 'debug': False}).start()
            ip = get_local_ip()
            local_url = f"http://{ip}:5000"
            self.display_qr_code(local_url)
            self.open_browser_button.setEnabled(True)
            self.open_browser_button.clicked.connect(lambda: webbrowser.open(local_url))

    def stop_server(self):
        os._exit(0)

    def display_qr_code(self, url):
        qr_data = generate_qr_code(url)
        pixmap = QPixmap()
        pixmap.loadFromData(qr_data)
        self.qr_image_label.setPixmap(pixmap)
        self.qr_image_label.setScaledContents(True)

    def update_devices_list(self):
        self.devices_list.clear()
        for device in connected_devices:
            self.devices_list.addItem(
                f"IP: {device['ip']}, Browser: {device['browser']}, OS: {device['os']}"
            )

def start_gui():
    app = QApplication([])
    window = FileSharingApp()
    window.show()
    app.exec()

if __name__ == "__main__":
    start_gui()
