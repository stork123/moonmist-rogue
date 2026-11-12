#!/usr/bin/env python3
"""
Moonmist Visual Mapper — multi-session web server for Docker deployment.
Each player gets their own dfrotz process via a session ID.
"""

import os
import re
import sys
import json
import time
import uuid
import subprocess
import threading
from collections import defaultdict
from flask import Flask, request, jsonify, send_from_directory

app = Flask(__name__, static_folder=None)

# --- Configuration ---
STORY_PATH = os.path.join(os.path.dirname(__file__), "MOONMIST.DAT")
DATA_PATH = os.path.join(os.path.dirname(__file__), "moonmist_data.json")
DFROTZ_CMD = os.environ.get("DFROTZ_CMD", "dfrotz")

SESSION_TIMEOUT = 30 * 60
MAX_SESSIONS = 20
MAX_CMD_LEN = 200
ALLOWED_CMD_RE = re.compile(r'^[a-zA-Z0-9\s\'.,!?/]+$')
BLOCKED_PATTERNS = re.compile(r'\b(rm|cat|ls|cd|cp|mv|wget|curl|bash|sh|python|perl|nc|netcat|kill|sudo)\b', re.IGNORECASE)

SAVE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'saves')


class DfrotzSession:
    def __init__(self, story_path, session_id=''):
        self.story_path = story_path
        self.session_id = session_id or str(uuid.uuid4())
        self.save_dir = os.path.join(SAVE_DIR, self.session_id)
        os.makedirs(self.save_dir, exist_ok=True)
        self.proc = None
        self.lock = threading.Lock()
        self.last_activity = time.time()
        self._start()

    def _start(self):
        self.proc = subprocess.Popen(
            [DFROTZ_CMD, self.story_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        # Consume startup output — read lines until we see the first prompt
        # Moonmist prints intro text then "What would you like to do?"
        try:
            for _ in range(50):
                line = self.proc.stdout.readline()
                if not line:
                    break
                if 'What would you like to do?' in line:
                    break
                if 'What next?' in line:
                    break
        except Exception:
            pass

    def send(self, command):
        self.last_activity = time.time()
        with self.lock:
            parts = command.strip().split(None, 1)
            verb = parts[0].lower() if parts else ''
            full_input = command

            if verb in ('save', 'restore', 'load'):
                if len(parts) > 1:
                    user_fn = os.path.basename(parts[1].strip())
                    if not user_fn:
                        user_fn = 'save.qzl'
                else:
                    user_fn = 'save.qzl'
                save_path = os.path.join(self.save_dir, user_fn)
                full_input = verb + '\n' + save_path

            try:
                self.proc.stdin.write(full_input + '\n')
                self.proc.stdin.flush()
            except (BrokenPipeError, OSError):
                self._start()
                self.proc.stdin.write(full_input + '\n')
                self.proc.stdin.flush()

            # Read response lines until quiet period
            response_lines = []
            start_time = time.time()
            quiet_timer = time.time()
            while time.time() - start_time < 15:
                line = self.proc.stdout.readline()
                if line:
                    response_lines.append(line)
                    quiet_timer = time.time()
                    # If we see a prompt-like ending, we can stop early
                    if 'What next?' in line or 'What would you like to do?' in line:
                        # Read one more line in case there's trailing output
                        time.sleep(0.05)
                        break
                else:
                    # No more data — check if we've been quiet for 400ms
                    if time.time() - quiet_timer > 0.4:
                        break
                    time.sleep(0.05)

            raw = ''.join(response_lines)
        return self._parse(raw, command)

    def _parse(self, raw, command):
        lines = raw.split('\n')
        lines = [l.replace('\r', '') for l in lines]
        room_name = ''
        score = 0
        moves = 0
        status_idx = -1

        for i, line in enumerate(lines):
            if 'Score:' in line and 'Moves:' in line:
                status_idx = i
                m1 = re.search(r'Score:\s*(\d+)', line)
                m2 = re.search(r'Moves:\s*(\d+)', line)
                if m1: score = int(m1.group(1))
                if m2: moves = int(m2.group(1))
                clean = re.sub(r'^>\s*', '', line)
                clean = re.sub(r'\s*Score:.*$', '', clean).strip()
                if clean: room_name = clean
                break
            # Moonmist uses "Time: H:MM am/pm" instead of Score/Moves
            if 'Time:' in line and ('am' in line or 'pm' in line):
                status_idx = i
                tm = re.search(r'Time:\s*(\d+):(\d+)\s*(am|pm)', line, re.IGNORECASE)
                if tm:
                    h = int(tm.group(1))
                    m = int(tm.group(2))
                    ampm = tm.group(3).lower()
                    if ampm == 'pm' and h != 12:
                        h += 12
                    elif ampm == 'am' and h == 12:
                        h = 0
                    score = h
                    moves = m
                clean = re.sub(r'^>\s*', '', line)
                clean = re.sub(r'\s*Time:.*$', '', clean).strip()
                if clean: room_name = clean
                break

        body_lines = []
        in_body = False
        for i in range(status_idx + 1, len(lines)):
            stripped = lines[i].strip()
            if stripped == '>' or stripped == '> ':
                break
            if not in_body and stripped == '':
                continue
            in_body = True
            body_lines.append(lines[i])

        while body_lines and body_lines[-1].strip() == '':
            body_lines.pop()

        # Strip Moonmist's "What next?" / "What would you like to do?" prompt
        while body_lines:
            last = body_lines[-1].strip()
            if last in ('What next?', 'What would you like to do?'):
                body_lines.pop()
            else:
                break

        return {
            'command': command,
            'room': room_name,
            'score': score,
            'moves': moves,
            'text': '\n'.join(body_lines).strip(),
        }

    def is_alive(self):
        return self.proc and self.proc.poll() is None

    def kill(self):
        try:
            if self.proc:
                self.proc.stdin.close()
                self.proc.terminate()
                self.proc.wait(timeout=3)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass


sessions = {}
sessions_lock = threading.Lock()

def get_session(session_id):
    with sessions_lock:
        s = sessions.get(session_id)
        if s and s.is_alive():
            return s
        return None

def create_session():
    with sessions_lock:
        now = time.time()
        expired = [sid for sid, s in sessions.items() if now - s.last_activity > SESSION_TIMEOUT]
        for sid in expired:
            sessions[sid].kill()
            del sessions[sid]

        if len(sessions) >= MAX_SESSIONS:
            oldest = min(sessions, key=lambda sid: sessions[sid].last_activity)
            sessions[oldest].kill()
            del sessions[oldest]

        session_id = str(uuid.uuid4())
        session = DfrotzSession(STORY_PATH, session_id)
        sessions[session_id] = session
        return session_id

def sanitize_command(cmd):
    if len(cmd) > MAX_CMD_LEN:
        return None
    if not ALLOWED_CMD_RE.match(cmd):
        return None
    if BLOCKED_PATTERNS.search(cmd):
        return None
    return cmd

_map_data = None
_desc_to_zil = {}
def get_map_data():
    global _map_data, _desc_to_zil
    if _map_data is None:
        with open(DATA_PATH, 'r') as f:
            _map_data = json.load(f)
        for name, info in _map_data.get('rooms', {}).items():
            _desc_to_zil[info['desc'].lower()] = name
    return _map_data

@app.route('/')
def index():
    return send_from_directory(os.path.dirname(__file__), 'index.html')

@app.route('/api/map')
def api_map():
    return jsonify(get_map_data())

@app.route('/api/session', methods=['POST'])
def api_create_session():
    session_id = create_session()
    return jsonify({'session_id': session_id})

@app.route('/api/command', methods=['POST'])
def api_command():
    data = request.get_json()
    command = data.get('command', '').strip()
    session_id = data.get('session_id', '')

    if not command:
        return jsonify({'error': 'No command'}), 400

    cmd = sanitize_command(command)
    if cmd is None:
        return jsonify({'error': 'Invalid command'}), 400

    session = get_session(session_id)
    if not session:
        session_id = create_session()
        session = get_session(session_id)
        if not session:
            return jsonify({'error': 'Server full'}), 503

    result = session.send(cmd)
    result['session_id'] = session_id
    if result.get('room'):
        result['room_zil'] = _desc_to_zil.get(result['room'].lower())
    return jsonify(result)

@app.route('/api/restart', methods=['POST'])
def api_restart():
    data = request.get_json() or {}
    session_id = data.get('session_id', '')
    session = get_session(session_id)
    if session:
        session.kill()
    with sessions_lock:
        if session_id in sessions:
            del sessions[session_id]
    session_id = create_session()
    return jsonify({'session_id': session_id, 'status': 'restarted'})

if __name__ == '__main__':
    if not os.path.isfile(STORY_PATH):
        print(f"ERROR: MOONMIST.DAT not found at {STORY_PATH}")
        sys.exit(1)

    get_map_data()
    print(f"Loaded {len(_desc_to_zil)} room name mappings")
    print(f"Moonmist Visual Mapper starting on port 5000")
    print(f"  dfrotz: {DFROTZ_CMD}")
    print(f"  story:  {STORY_PATH}")
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)