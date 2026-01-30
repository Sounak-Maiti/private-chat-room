import os
import mimetypes
import io
from flask import Flask, render_template, request, session, redirect, url_for, jsonify, send_file
from flask_socketio import join_room, leave_room, send, SocketIO
from werkzeug.utils import secure_filename
import random
from string import ascii_uppercase
import time

app = Flask(__name__)
app.config["SECRET_KEY"] = "hjhjsdahhds"

app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10MB
app.config["ALLOWED_EXTENSIONS"] = {'txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif', 'webp'}
socketio = SocketIO(app)

rooms = {}

# FIXED DESIGN: Shared RAM file registry
shared_files = {}

def generate_unique_code(length):
    while True:
        code = ""
        for _ in range(length):
            code += random.choice(ascii_uppercase)
        
        if code not in rooms:
            break
    
    return code

@app.route("/", methods=["POST", "GET"])
def home():
    session.clear()
    if request.method == "POST":
        name = request.form.get("name")
        code = request.form.get("code")
        join = request.form.get("join", False)
        create = request.form.get("create", False)

        if not name:
            return render_template("home.html", error="Please enter a name.", code=code, name=name)

        if join != False and not code:
            return render_template("home.html", error="Please enter a room code.", code=code, name=name)
        
        room = code
        if create != False:
            room = generate_unique_code(4)
            rooms[room] = {"members": 0, "messages": []}
        elif code not in rooms:
            return render_template("home.html", error="Room does not exist.", code=code, name=name)
        
        session["room"] = room
        session["name"] = name
        return redirect(url_for("room"))

    return render_template("home.html")

@app.route("/room")
def room():
    room = session.get("room")
    if room is None or session.get("name") is None or room not in rooms:
        return redirect(url_for("home"))

    return render_template("room.html", code=room, messages=rooms[room]["messages"], name=session.get("name"))

@socketio.on("message")
def message(data):
    room = session.get("room")
    if room not in rooms:
        return 
    
    content = {
        "name": session.get("name"),
        "message": data["data"]
    }
    send(content, to=room)
    rooms[room]["messages"].append(content)
    print(f"{session.get('name')} said: {data['data']}")

@socketio.on("connect")
def connect(auth):
    room = session.get("room")
    name = session.get("name")
    if not room or not name:
        return
    if room not in rooms:
        leave_room(room)
        return
    
    join_room(room)
    send({"name": name, "message": "has entered the room"}, to=room)
    rooms[room]["members"] += 1
    print(f"{name} joined room {room}")

@socketio.on("disconnect")
def disconnect():
    room = session.get("room")
    name = session.get("name")
    leave_room(room)

    if room in rooms:
        rooms[room]["members"] -= 1
        if rooms[room]["members"] <= 0:
            del rooms[room]
    
    send({"name": name, "message": "has left the room"}, to=room)
    print(f"{name} has left the room {room}")



# FIXED DESIGN: File sharing routes using shared RAM store
@app.route('/upload/<room_code>', methods=['POST'])
def upload_file_to_room(room_code):
    if not session.get("room") or session.get("room") != room_code:
        return jsonify({'error': 'Unauthorized'}), 403
    
    if room_code not in rooms:
        return jsonify({'error': 'Room not found'}), 404
    
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    
    filename = secure_filename(file.filename)
    if '.' not in filename or filename.rsplit('.', 1)[1].lower() not in app.config['ALLOWED_EXTENSIONS']:
        return jsonify({'error': 'File type not allowed'}), 400
    
    # FIXED DESIGN: Store in shared RAM registry
    if room_code not in shared_files:
        shared_files[room_code] = {}
    
    if filename in shared_files[room_code]:
        return jsonify({'error': 'File already exists'}), 409
    
    file_content = file.read()
    shared_files[room_code][filename] = {
        'content': file_content,
        'size': len(file_content),
        'type': mimetypes.guess_type(filename)[0] or 'application/octet-stream',
        'uploaded_at': time.time()
    }
    # FIXED DESIGN: Emit real-time update to all users in room
    socketio.emit('file_uploaded', {'filename': filename, 'size': len(file_content)}, to=room_code)
    print(f"File uploaded to room {room_code}: {filename}")
    return jsonify({'success': True})

@app.route('/files/<room_code>')
def list_files(room_code):
    if not session.get("room") or session.get("room") != room_code:
        return jsonify({'error': 'Unauthorized'}), 403
    
    if room_code not in rooms:
        return jsonify({'error': 'Room not found'}), 404
    
    # FIXED DESIGN: List from shared RAM registry
    if room_code not in shared_files:
        return jsonify([])
    
    files = []
    for filename, file_data in shared_files[room_code].items():
        files.append({
            'name': filename,
            'size': file_data['size'],
            'modified': file_data['uploaded_at']
        })
    return jsonify(files)

@app.route('/files/<room_code>/<filename>')
def download_file(room_code, filename):
    if not session.get("room") or session.get("room") != room_code:
        return jsonify({'error': 'Unauthorized'}), 403
    
    if room_code not in rooms:
        return jsonify({'error': 'Room not found'}), 404
    
    # FIXED DESIGN: Serve from shared RAM registry
    if room_code not in shared_files or filename not in shared_files[room_code]:
        return jsonify({'error': 'File not found'}), 404
    
    file_data = shared_files[room_code][filename]
    return send_file(
        io.BytesIO(file_data['content']),
        mimetype=file_data['type'],
        as_attachment=True,
        download_name=filename
    )

@app.route('/preview/<room_code>/<filename>')
def preview_file(room_code, filename):
    if not session.get("room") or session.get("room") != room_code:
        return jsonify({'error': 'Unauthorized'}), 403
    
    if room_code not in rooms:
        return jsonify({'error': 'Room not found'}), 404
    
    # FIXED DESIGN: Serve from shared RAM registry
    if room_code not in shared_files or filename not in shared_files[room_code]:
        return jsonify({'error': 'File not found'}), 404
    
    file_data = shared_files[room_code][filename]
    mime_type = file_data['type']
    if mime_type and (mime_type.startswith('image/') or mime_type == 'application/pdf' or mime_type == 'text/plain'):
        return send_file(
            io.BytesIO(file_data['content']),
            mimetype=mime_type
        )
    else:
        return jsonify({'error': 'Preview not supported'}), 400

@app.route('/delete/<room_code>/<filename>', methods=['DELETE'])
def delete_file(room_code, filename):
    if not session.get("room") or session.get("room") != room_code:
        return jsonify({'error': 'Unauthorized'}), 403
    
    if room_code not in rooms:
        return jsonify({'error': 'Room not found'}), 404
    
    # FIXED DESIGN: Delete from shared RAM registry
    if room_code in shared_files and filename in shared_files[room_code]:
        del shared_files[room_code][filename]
        # Emit real-time update
        socketio.emit('file_deleted', {'filename': filename}, to=room_code)
        return jsonify({'success': True})
    else:
        return jsonify({'error': 'File not found'}), 404

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    socketio.run(
        app,
        host="0.0.0.0",
        port=port,
        debug=False
    )
