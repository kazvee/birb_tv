import cv2
import time
import glob
import uuid
import zipfile
from io import BytesIO
from datetime import datetime
from flask import Flask, render_template, Response, send_from_directory, request, redirect, url_for, session, send_file
from dotenv import load_dotenv
import os

load_dotenv()

app = Flask(__name__)

app.secret_key = os.getenv('SECRET_KEY') or 'dev-only'

W_PASSWORD = os.getenv('W_PASSWORD')
K_PASSWORD = os.getenv('K_PASSWORD')

camera_ok = True

# ------------------------
# CONFIG
# ------------------------

W_DIR = 'w_captures'
K_DIR = 'k_captures'

os.makedirs(W_DIR, exist_ok=True)
os.makedirs(K_DIR, exist_ok=True)

CAMERA_INDEX = 0

# ------------------------
# CAMERA
# ------------------------

def init_camera():
    cam = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_V4L2)

    cam.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cam.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

    # warmup
    for _ in range(5):
        cam.read()
        time.sleep(0.1)

    return cam


camera = init_camera()

# ------------------------
# CAMERA RECOVERY
# ------------------------

def recover_camera():
    global camera

    try:
        camera.release()
    except:
        pass

    time.sleep(1)
    camera = init_camera()
    print('🔄 Camera reset')

# ------------------------
# SAFE FRAME READ
# ------------------------

def get_frame():
    global camera, camera_ok

    for _ in range(3):
        ret, frame = camera.read()

        if ret and frame is not None:
            camera_ok = True
            return True, frame

        time.sleep(0.05)

    print('❌ Camera read failed')

    camera_ok = False
    recover_camera()
    return False, None

# ------------------------
# STREAM
# ------------------------

def generate_frames():
    while True:
        ret, frame = get_frame()

        if not ret or frame is None:
            time.sleep(0.1)
            continue

        ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])

        if not ret:
            continue

        yield (
            b'--frame\r\n'
            b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n'
        )

# ------------------------
# CAPTURE
# ------------------------

def capture_image(folder, prefix):
    ret, frame = get_frame()

    if not ret or frame is None:
        print('❌ Capture failed')
        return

    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S-%f')

    filename = f'{prefix}_{timestamp}_{uuid.uuid4().hex}.jpg'
    filepath = os.path.join(folder, filename)

    cv2.imwrite(filepath, frame)

    print(f'📸 Saved {filepath}')

# ------------------------
# ROUTES
# ------------------------

@app.route('/')
def index():
    images_w = sorted(
        glob.glob(f'{W_DIR}/*.jpg'),
        key=os.path.getmtime,
        reverse=True
    )[:5]

    images_w = [f'/{img}' for img in images_w]

    images_k = sorted(
        glob.glob(f'{K_DIR}/*.jpg'),
        key=os.path.getmtime,
        reverse=True
    )[:5]

    images_k = [f'/{img}' for img in images_k]

    return render_template(
        'index.html',
        images_w=images_w,
        images_k=images_k,
        user=session.get('user'),
        theme=session.get('theme', 'dark'),
        camera_on=camera_ok
    )

# ------------------------
# LOGIN
# ------------------------

@app.route('/login/<user>', methods=['POST'])
def login(user):
    print(f'LOGIN HIT: {user}')
    if user not in ['w', 'k']:
        return ('Invalid user', 400)

    session['user'] = user
    return redirect(url_for('index'))

# ------------------------
# LOGOUT
# ------------------------

@app.route('/logout', methods=['POST'])
def logout():
    session.pop('user', None)
    return redirect(url_for('index'))

# ------------------------
# THEME
# ------------------------

@app.route('/theme/<name>', methods=['POST'])
def set_theme(name):
    if name not in ['spring', 'summer', 'fall', 'winter', 'dark']:
        return ('Invalid theme', 400)

    session['theme'] = name
    return redirect(url_for('index'))

# ------------------------
# CAPTURE BUTTONS
# ------------------------

@app.route('/w_capture', methods=['POST'])
def w_capture():
    if session.get('user') != 'w':
        return ('Unauthorized', 403)

    capture_image(W_DIR, 'w')
    return redirect(url_for('index'))


@app.route('/k_capture', methods=['POST'])
def k_capture():
    if session.get('user') != 'k':
        return ('Unauthorized', 403)

    capture_image(K_DIR, 'k')
    return redirect(url_for('index'))

# ------------------------
# GALLERIES
# ------------------------

@app.route('/gallery')
def gallery():
    user = session.get('user')

    if user == 'w':
        folder = W_DIR
    elif user == 'k':
        folder = K_DIR
    else:
        return redirect(url_for('index'))

    images = sorted(
        glob.glob(f'{folder}/*.jpg'),
        key=os.path.getmtime,
        reverse=True
    )

    images = [f'/{img}' for img in images]

    return render_template(
        'gallery.html',
        images=images,
        user=user,
        theme=session.get('theme', 'dark'),
        camera_on=False
    )

# ------------------------
# SERVE FILES
# ------------------------

@app.route('/w_captures/<filename>')
def w_files(filename):
    return send_from_directory(W_DIR, filename)


@app.route('/k_captures/<filename>')
def k_files(filename):
    return send_from_directory(K_DIR, filename)

# ------------------------
# PURGE
# ------------------------

@app.route('/w_purge', methods=['POST'])
def w_purge():
    if request.form.get('password') != W_PASSWORD:
        return ('Unauthorized', 403)

    for f in glob.glob(f'{W_DIR}/*.jpg'):
        try:
            os.remove(f)
        except OSError:
            pass

    return redirect(url_for('index'))


@app.route('/k_purge', methods=['POST'])
def k_purge():
    if request.form.get('password') != K_PASSWORD:
        return ('Unauthorized', 403)

    for f in glob.glob(f'{K_DIR}/*.jpg'):
        try:
            os.remove(f)
        except OSError:
            pass

    return redirect(url_for('index'))

# ------------------------
# DOWNLOAD PHOTOS
# ------------------------

@app.route('/download_selected', methods=['POST'])
def download_selected():
    files = request.form.getlist('selected')

    if not files:
        return redirect(url_for('gallery'))

    memory_file = BytesIO()

    with zipfile.ZipFile(memory_file, 'w') as zf:
        for file_path in files:
            full_path = file_path.lstrip('/')
            abs_path = os.path.abspath(full_path)

            if not (
                abs_path.startswith(os.path.abspath(W_DIR)) or
                abs_path.startswith(os.path.abspath(K_DIR))
            ):
                continue

            if os.path.exists(abs_path):
                zf.write(abs_path, arcname=os.path.basename(abs_path))

    memory_file.seek(0)

    user = session.get('user', 'anon')
    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')

    filename = f'birb_{user}_{timestamp}.zip'

    return send_file(
        memory_file,
        as_attachment=True,
        download_name=filename,
        mimetype='application/zip'
    )

# ------------------------
# VIDEO STREAM
# ------------------------

@app.route('/video')
def video():
    return Response(
        generate_frames(),
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )

# ------------------------
# RUN
# ------------------------

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
