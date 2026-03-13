import os
import sqlite3
import base64
import datetime
import cv2
import numpy as np
import mediapipe as mp
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash

# Initialize MediaPipe Face Mesh
try:
    import mediapipe as mp
    mp_face_mesh = mp.solutions.face_mesh
    face_mesh = mp_face_mesh.FaceMesh(
        max_num_faces=10,
        refine_landmarks=True,
        min_detection_confidence=0.5,
        min_tracking_confidence=0.5
    )
except Exception as e:
    print(f"Warning: MediaPipe failed to load. Gaze tracking disabled. Error: {e}")
    mp = None
    face_mesh = None

# Store consecutive frames looking away for each student
gaze_tracking_sessions = {}
LOOK_AWAY_FRAMES_THRESHOLD = 3 # Triggers alert after several consecutive frames looking away

app = Flask(__name__)
app.secret_key = 'super_secret_key_for_exam_system_change_in_production'
DATABASE = 'database.db'

def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initialize the database and table structure."""
    
    # In development, it's easier to drop the table to apply the new schema
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('DROP TABLE IF EXISTS users')
    c.execute('DROP TABLE IF EXISTS exams')
    c.execute('DROP TABLE IF EXISTS questions')
    c.execute('DROP TABLE IF EXISTS answers')
    c.execute('DROP TABLE IF EXISTS results')
    c.execute('DROP TABLE IF EXISTS cheating_alerts')
    
    c.execute('''
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL,
            register_number TEXT,
            course TEXT,
            photo TEXT
        )
    ''')
    
    c.execute('''
        CREATE TABLE exams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exam_name TEXT NOT NULL,
            duration INTEGER NOT NULL,
            created_date DATETIME DEFAULT CURRENT_TIMESTAMP,
            created_by INTEGER NOT NULL,
            FOREIGN KEY (created_by) REFERENCES users (id)
        )
    ''')
    
    c.execute('''
        CREATE TABLE questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exam_id INTEGER NOT NULL,
            question_text TEXT NOT NULL,
            option1 TEXT NOT NULL,
            option2 TEXT NOT NULL,
            option3 TEXT NOT NULL,
            option4 TEXT NOT NULL,
            correct_answer TEXT NOT NULL,
            question_type TEXT NOT NULL DEFAULT 'multiple_choice',
            FOREIGN KEY (exam_id) REFERENCES exams (id)
        )
    ''')
    
    c.execute('''
        CREATE TABLE answers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            exam_id INTEGER NOT NULL,
            question_id INTEGER NOT NULL,
            selected_answer TEXT NOT NULL,
            FOREIGN KEY (student_id) REFERENCES users (id),
            FOREIGN KEY (exam_id) REFERENCES exams (id),
            FOREIGN KEY (question_id) REFERENCES questions (id)
        )
    ''')
    
    c.execute('''
        CREATE TABLE results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_name TEXT NOT NULL,
            register_number TEXT NOT NULL,
            exam_name TEXT NOT NULL,
            marks INTEGER NOT NULL,
            status TEXT NOT NULL,
            cheating_alerts INTEGER DEFAULT 0
        )
    ''')

    c.execute('''
        CREATE TABLE cheating_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exam_id INTEGER,
            student_id INTEGER NOT NULL,
            alert_type TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            screenshot_path TEXT,
            status TEXT DEFAULT 'Pending',
            FOREIGN KEY (student_id) REFERENCES users (id)
        )
    ''')
    
    # Check if we need to seed initial users
    c.execute('SELECT * FROM users WHERE email = ?', ('admin@exam.com',))
    if not c.fetchone():
        users = [
            ('Admin User', 'admin@exam.com', generate_password_hash('admin123'), 'admin', None, None, None),
            ('Teacher User', 'teacher@exam.com', generate_password_hash('teacher123'), 'teacher', 'EMP001', 'Computer Science', None),
            ('Student User', 'student@exam.com', generate_password_hash('student123'), 'student', 'REG2023001', 'B.Tech Computer Science', 'default_student_photo.jpg')
        ]
        c.executemany('INSERT INTO users (name, email, password, role, register_number, course, photo) VALUES (?, ?, ?, ?, ?, ?, ?)', users)
        
    conn.commit()
    conn.close()

# Initialize database
init_db()

@app.route('/')
def index():
    if 'user_id' in session:
        role = session.get('role')
        if role == 'admin':
            return redirect(url_for('admin_dashboard'))
        elif role == 'teacher':
            return redirect(url_for('teacher_dashboard'))
        elif role == 'student':
            return redirect(url_for('student_dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
        conn.close()
        
        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['email'] = user['email']
            session['name'] = user['name']
            session['role'] = user['role']
            
            if user['role'] == 'admin':
                return redirect(url_for('admin_dashboard'))
            elif user['role'] == 'teacher':
                return redirect(url_for('teacher_dashboard'))
            elif user['role'] == 'student':
                return redirect(url_for('student_dashboard'))
        else:
            flash('Invalid username or password')
            
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/admin/dashboard')
def admin_dashboard():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))
    return render_template('admin_dashboard.html')

@app.route('/teacher/dashboard')
def teacher_dashboard():
    if session.get('role') != 'teacher':
        return redirect(url_for('login'))
        
    conn = get_db_connection()
    # Fetch all custom exams created by teachers (ignoring the hardcoded 'Introduction to Python' for now unless we seed it)
    exams = conn.execute('''
        SELECT e.*, 
               (SELECT COUNT(*) FROM questions q WHERE q.exam_id = e.id) as question_count
        FROM exams e
        WHERE e.created_by = ?
    ''', (session['user_id'],)).fetchall()
    
    # Fetch recent cheating alerts
    # Join with users to get student names (in case of legacy alerts just using name)
    alerts = conn.execute('''
        SELECT c.*, u.name as student_name 
        FROM cheating_alerts c
        LEFT JOIN users u ON c.student_id = u.id
        ORDER BY timestamp DESC 
        LIMIT 20
    ''').fetchall()
    
    # Fetch recent results
    results = conn.execute('SELECT * FROM results ORDER BY id DESC LIMIT 20').fetchall()
    
    conn.close()
    
    return render_template('teacher_dashboard.html', alerts=alerts, exams=exams, results=results)

@app.route('/teacher/alerts')
def teacher_alerts():
    if session.get('role') != 'teacher':
        return redirect(url_for('login'))
        
    conn = get_db_connection()
    alerts = conn.execute('''
        SELECT c.*, u.name as student_name 
        FROM cheating_alerts c
        LEFT JOIN users u ON c.student_id = u.id
        ORDER BY timestamp DESC
    ''').fetchall()
    conn.close()
    
    return render_template('alert_dashboard.html', alerts=alerts)

@app.route('/teacher/update_alert/<int:alert_id>', methods=['POST'])
def update_alert(alert_id):
    if session.get('role') != 'teacher':
        return redirect(url_for('login'))
        
    status = request.form.get('status')
    if status in ['Confirmed Cheating', 'False Alert', 'Pending']:
        conn = get_db_connection()
        conn.execute('UPDATE cheating_alerts SET status = ? WHERE id = ?', (status, alert_id))
        conn.commit()
        conn.close()
        flash('Alert status updated successfully.')
        
    return redirect(url_for('teacher_alerts'))

@app.route('/teacher/exam_hub')
def exam_hub():
    if session.get('role') != 'teacher':
        return redirect(url_for('login'))
    return render_template('exam_hub.html')

@app.route('/teacher/create_exam', methods=['GET', 'POST'])
def create_exam():
    if session.get('role') != 'teacher':
        return redirect(url_for('login'))
        
    if request.method == 'POST':
        exam_name = request.form.get('exam_name')
        duration = int(request.form.get('duration'))
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO exams (exam_name, duration, created_by) 
            VALUES (?, ?, ?)
        ''', (exam_name, duration, session['user_id']))
        
        conn.commit()
        conn.close()
        
        flash('Exam created successfully! Now you can add questions to it.')
        return redirect(url_for('manage_exams'))
        
    return render_template('create_exam.html')

@app.route('/teacher/manage_exams')
def manage_exams():
    if session.get('role') != 'teacher':
        return redirect(url_for('login'))
        
    conn = get_db_connection()
    exams = conn.execute('''
        SELECT e.*, 
               (SELECT COUNT(*) FROM questions q WHERE q.exam_id = e.id) as question_count
        FROM exams e
        WHERE e.created_by = ?
    ''', (session['user_id'],)).fetchall()
    conn.close()
    
    return render_template('manage_exams.html', exams=exams)

@app.route('/teacher/edit_exam/<int:exam_id>', methods=['GET', 'POST'])
def edit_exam(exam_id):
    if session.get('role') != 'teacher':
        return redirect(url_for('login'))
        
    conn = get_db_connection()
    exam = conn.execute('SELECT * FROM exams WHERE id = ? AND created_by = ?', (exam_id, session['user_id'])).fetchone()
    
    if not exam:
        conn.close()
        flash('Exam not found or access denied.')
        return redirect(url_for('manage_exams'))
        
    if request.method == 'POST':
        exam_name = request.form.get('exam_name')
        duration = int(request.form.get('duration'))
        
        conn.execute('''
            UPDATE exams 
            SET exam_name = ?, duration = ?
            WHERE id = ?
        ''', (exam_name, duration, exam_id))
        conn.commit()
        conn.close()
        
        flash('Exam updated successfully!')
        return redirect(url_for('manage_exams'))
        
    conn.close()
    return render_template('edit_exam.html', exam=exam)

@app.route('/teacher/delete_exam/<int:exam_id>', methods=['POST'])
def delete_exam(exam_id):
    if session.get('role') != 'teacher':
        return redirect(url_for('login'))
        
    conn = get_db_connection()
    exam = conn.execute('SELECT * FROM exams WHERE id = ? AND created_by = ?', (exam_id, session['user_id'])).fetchone()
    
    if not exam:
        conn.close()
        flash('Exam not found or access denied.')
        return redirect(url_for('manage_exams'))
        
    # Delete associated answers to avoid foreign key violations, then associated questions, then the exam
    conn.execute('DELETE FROM answers WHERE exam_id = ?', (exam_id,))
    conn.execute('DELETE FROM questions WHERE exam_id = ?', (exam_id,))
    conn.execute('DELETE FROM exams WHERE id = ?', (exam_id,))
    conn.commit()
    conn.close()
    
    flash('Exam deleted successfully.')
    return redirect(url_for('manage_exams'))

@app.route('/teacher/add_question/<int:exam_id>', methods=['GET', 'POST'])
def add_question(exam_id):
    if session.get('role') != 'teacher':
        return redirect(url_for('login'))
        
    conn = get_db_connection()
    exam = conn.execute('SELECT * FROM exams WHERE id = ? AND created_by = ?', (exam_id, session['user_id'])).fetchone()
    
    if not exam:
        conn.close()
        flash('Exam not found or access denied.')
        return redirect(url_for('manage_exams'))
        
    if request.method == 'POST':
        q_text = request.form.get('question_text')
        o1 = request.form.get('option1')
        o2 = request.form.get('option2')
        o3 = request.form.get('option3')
        o4 = request.form.get('option4')
        correct = request.form.get('correct_answer')
        
        conn.execute('''
            INSERT INTO questions (exam_id, question_text, option1, option2, option3, option4, correct_answer)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (exam_id, q_text, o1, o2, o3, o4, correct))
        
        conn.commit()
        conn.close()
        
        flash('Question added successfully!')
        return redirect(url_for('manage_exams'))
        
    conn.close()
    return render_template('add_question.html', exam=exam)

@app.route('/teacher/manage_questions/<int:exam_id>')
def manage_questions(exam_id):
    if session.get('role') != 'teacher':
        return redirect(url_for('login'))
        
    conn = get_db_connection()
    exam = conn.execute('SELECT * FROM exams WHERE id = ? AND created_by = ?', (exam_id, session['user_id'])).fetchone()
    if not exam:
        conn.close()
        flash('Exam not found or access denied.')
        return redirect(url_for('manage_exams'))
        
    questions = conn.execute('SELECT * FROM questions WHERE exam_id = ?', (exam_id,)).fetchall()
    conn.close()
    
    return render_template('manage_questions.html', exam=exam, questions=questions)

@app.route('/teacher/edit_question/<int:question_id>', methods=['GET', 'POST'])
def edit_question(question_id):
    if session.get('role') != 'teacher':
        return redirect(url_for('login'))
        
    conn = get_db_connection()
    question = conn.execute('SELECT * FROM questions WHERE id = ?', (question_id,)).fetchone()
    
    if not question:
        conn.close()
        flash('Question not found.')
        return redirect(url_for('manage_exams'))
        
    exam = conn.execute('SELECT * FROM exams WHERE id = ? AND created_by = ?', (question['exam_id'], session['user_id'])).fetchone()
    if not exam:
        conn.close()
        flash('Access denied.')
        return redirect(url_for('manage_exams'))
        
    if request.method == 'POST':
        q_text = request.form['question_text']
        o1 = request.form['option1']
        o2 = request.form['option2']
        o3 = request.form['option3']
        o4 = request.form['option4']
        correct = request.form['correct_answer']
        
        conn.execute('''
            UPDATE questions 
            SET question_text = ?, option1 = ?, option2 = ?, option3 = ?, option4 = ?, correct_answer = ?
            WHERE id = ?
        ''', (q_text, o1, o2, o3, o4, correct, question_id))
        conn.commit()
        conn.close()
        
        flash('Question updated successfully!')
        return redirect(url_for('manage_questions', exam_id=question['exam_id']))
        
    conn.close()
    return render_template('edit_question.html', question=question)

@app.route('/teacher/delete_question/<int:question_id>', methods=['POST'])
def delete_question(question_id):
    if session.get('role') != 'teacher':
        return redirect(url_for('login'))
        
    conn = get_db_connection()
    question = conn.execute('SELECT * FROM questions WHERE id = ?', (question_id,)).fetchone()
    
    if not question:
        conn.close()
        flash('Question not found.')
        return redirect(url_for('manage_exams'))
        
    exam_id = question['exam_id']
    exam = conn.execute('SELECT * FROM exams WHERE id = ? AND created_by = ?', (exam_id, session['user_id'])).fetchone()
    
    if not exam:
        conn.close()
        flash('Access denied.')
        return redirect(url_for('manage_exams'))
        
    conn.execute('DELETE FROM answers WHERE question_id = ?', (question_id,))
    conn.execute('DELETE FROM questions WHERE id = ?', (question_id,))
    conn.commit()
    conn.close()
    
    flash('Question deleted successfully.')
    return redirect(url_for('manage_questions', exam_id=exam_id))

import pandas as pd
from flask import send_file
import io

@app.route('/teacher/download_results')
def download_results():
    if session.get('role') != 'teacher':
        return redirect(url_for('login'))
        
    conn = get_db_connection()
    df = pd.read_sql_query("SELECT student_name, register_number, exam_name, marks, status, cheating_alerts FROM results", conn)
    conn.close()
    
    output = io.BytesIO()
    # Write to memory buffer
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Results')
        
    output.seek(0)
    
    return send_file(
        output,
        as_attachment=True,
        download_name='exam_results.xlsx',
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )

@app.route('/student/dashboard')
def student_dashboard():
    if session.get('role') != 'student':
        return redirect(url_for('login'))
        
    # Fetch full student profile data
    conn = get_db_connection()
    student = conn.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    
    # Fetch all available exams
    exams = conn.execute('''
        SELECT e.*, 
               (SELECT COUNT(*) FROM questions q WHERE q.exam_id = e.id) as question_count
        FROM exams e
    ''').fetchall()
    
    # Fetch student's past results
    results = conn.execute('SELECT * FROM results WHERE register_number = ?', (student['register_number'],)).fetchall()
    
    conn.close()
    
    return render_template('student_dashboard.html', student=student, exams=exams, results=results)

@app.route('/exam/<int:exam_id>')
def exam_page(exam_id):
    if session.get('role') != 'student':
        return redirect(url_for('login'))
        
    # Verify exam exists
    conn = get_db_connection()
    exam = conn.execute('SELECT * FROM exams WHERE id = ?', (exam_id,)).fetchone()
    if not exam:
        conn.close()
        flash('Exam not found.')
        return redirect(url_for('student_dashboard'))
        
    questions = conn.execute('SELECT * FROM questions WHERE exam_id = ?', (exam_id,)).fetchall()
    conn.close()
        
    # Reset gaze tracking when exam starts
    user_id = session.get('user_id')
    if user_id:
        gaze_tracking_sessions[user_id] = 0
        
    return render_template('exam_page.html', exam=exam, questions=questions)

@app.route('/submit_exam/<int:exam_id>', methods=['POST'])
def submit_exam(exam_id):
    if session.get('role') != 'student':
        return redirect(url_for('login'))
        
    student_id = session['user_id']
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Needs exam metadata
    exam = cursor.execute('SELECT * FROM exams WHERE id = ?', (exam_id,)).fetchone()
    if not exam:
        return "Exam not found", 404
        
    questions = cursor.execute('SELECT * FROM questions WHERE exam_id = ?', (exam_id,)).fetchall()
    
    correct_count = 0
    total_questions = len(questions)
    
    # Process answers
    for q in questions:
        q_id = str(q['id'])
        submitted_ans = request.form.get(f'q{q_id}')
        
        if submitted_ans:
            # Save student answer
            cursor.execute('''
                INSERT INTO answers (student_id, exam_id, question_id, selected_answer)
                VALUES (?, ?, ?, ?)
            ''', (student_id, exam_id, q['id'], submitted_ans))
            
            # Auto Grade
            if submitted_ans == q['correct_answer']:
                correct_count += 1
                
    # Calculate grade
    marks_percentage = int((correct_count / total_questions) * 100) if total_questions > 0 else 0
    status = 'Pass' if marks_percentage >= 50 else 'Fail'
    
    # Fetch student info directly for results table formatting
    student = cursor.execute('SELECT * FROM users WHERE id = ?', (student_id,)).fetchone()
    
    # Check for number of cheating alerts to save in results
    alerts_val = cursor.execute('SELECT COUNT(*) as c FROM cheating_alerts WHERE student_id = ? AND exam_id = ?', (student_id, exam_id)).fetchone()
    alerts_total = alerts_val['c'] if alerts_val else 0

    cursor.execute('''
        INSERT INTO results (student_name, register_number, exam_name, marks, status, cheating_alerts)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (student['name'], student['register_number'], exam['exam_name'], marks_percentage, status, alerts_total))
    
    conn.commit()
    conn.close()
    
    flash(f"Exam submitted successfully! Your grade: {marks_percentage}% ({status})")
    return redirect(url_for('student_dashboard'))

@app.route('/upload_frame', methods=['POST'])
def upload_frame():
    if session.get('role') != 'student':
        return jsonify({'error': 'Unauthorized'}), 403
        
    data = request.json
    if not data:
        return jsonify({'error': 'No data provided'}), 400
        
    user_id = session.get('user_id')
    
    # Detect audio logic mapping
    if 'audio_level' in data:
        # High audio anomaly recorded from JS
        conn = get_db_connection()
        conn.execute('INSERT INTO cheating_alerts (student_id, alert_type) VALUES (?, ?)',
                    (user_id, "High Audio Level Detected"))
        conn.commit()
        conn.close()
        return jsonify({'status': 'alert_recorded', 'type': "High Audio Level Detected"})
        
    if 'tab_switch' in data:
        conn = get_db_connection()
        conn.execute('INSERT INTO cheating_alerts (student_id, alert_type) VALUES (?, ?)',
                    (user_id, "Tab Switch / Visibility Change"))
        conn.commit()
        conn.close()
        return jsonify({'status': 'alert_recorded', 'type': "Tab Switched"})
        
    if 'image' not in data:
        return jsonify({'error': 'No image provided'}), 400
        
    image_data = data['image']
    # Format of image data: "data:image/jpeg;base64,/9j/4AAQSkZJRg..."
    try:
        header, encoded = image_data.split(",", 1)
        image_bytes = base64.b64decode(encoded)
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    except Exception as e:
        return jsonify({'error': 'Invalid image format'}), 400
        
    if img is None:
        return jsonify({'error': 'Failed to decode image'}), 400
        
    # Ensure upload directory exists
    upload_dir = os.path.join('static', 'uploads')
    os.makedirs(upload_dir, exist_ok=True)
    
    file_name = f"alert_{session['user_id']}_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}.jpg"
    file_path = os.path.join(upload_dir, file_name)
    relative_path = f"uploads/{file_name}"

    # Process with MediaPipe
    if face_mesh is not None:
        rgb_img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        results = face_mesh.process(rgb_img)
    else:
        results = None
    
    user_id = session.get('user_id')
    student_name = session.get('name')
    
    alert_type = None
    
    if results is None:
        pass # CV disabled
    elif not results.multi_face_landmarks:
        alert_type = "No Face Detected"
    elif len(results.multi_face_landmarks) > 1:
        alert_type = f"Multiple Faces Detected ({len(results.multi_face_landmarks)})"
    else:
        # One face detected. Check gaze/head pose.
        face_landmarks = results.multi_face_landmarks[0]
        h, w, _ = img.shape
        
        # 3D model points (simplified for head pose estimation)
        # Nose tip, Chin, Left eye left corner, Right eye right corner, Left mouth corner, Right mouth corner
        model_points = np.array([
            (0.0, 0.0, 0.0),             # Nose tip
            (0.0, -330.0, -65.0),        # Chin
            (-225.0, 170.0, -135.0),     # Left eye left corner
            (225.0, 170.0, -135.0),      # Right eye right corner
            (-150.0, -150.0, -125.0),    # Left Mouth corner
            (150.0, -150.0, -125.0)      # Right mouth corner
        ])
        
        # Corresponding 2D landmark points from MediaPipe
        # MediaPipe uses index 1 for nose tip, 152 for chin, 33 for left eye corner, 263 for right eye corner, 61 for left mouth, 291 right mouth
        image_points = np.array([
            (face_landmarks.landmark[1].x * w, face_landmarks.landmark[1].y * h),
            (face_landmarks.landmark[152].x * w, face_landmarks.landmark[152].y * h),
            (face_landmarks.landmark[33].x * w, face_landmarks.landmark[33].y * h),
            (face_landmarks.landmark[263].x * w, face_landmarks.landmark[263].y * h),
            (face_landmarks.landmark[61].x * w, face_landmarks.landmark[61].y * h),
            (face_landmarks.landmark[291].x * w, face_landmarks.landmark[291].y * h)
        ], dtype="double")
        
        focal_length = w
        center = (w / 2, h / 2)
        camera_matrix = np.array([
            [focal_length, 0, center[0]],
            [0, focal_length, center[1]],
            [0, 0, 1]
        ], dtype="double")
        
        dist_coeffs = np.zeros((4, 1)) # Assuming no lens distortion
        
        # Solve PnP
        success, rotation_vector, translation_vector = cv2.solvePnP(model_points, image_points, camera_matrix, dist_coeffs)
        
        if success:
            rmat, _ = cv2.Rodrigues(rotation_vector)
            angles, _, _, _, _, _ = cv2.RQDecomp3x3(rmat)
            
            x_angle = angles[0] * 360  # Pitch (up/down)
            y_angle = angles[1] * 360  # Yaw (left/right)
            
            # Thresholds for looking away
            # These values might need tuning depending on camera angle
            if abs(y_angle) > 20 or abs(x_angle) > 20: 
                # Looking away
                if user_id not in gaze_tracking_sessions:
                    gaze_tracking_sessions[user_id] = 0
                gaze_tracking_sessions[user_id] += 1
                
                if gaze_tracking_sessions[user_id] >= LOOK_AWAY_FRAMES_THRESHOLD:
                    alert_type = "Looking Away"
                    # Reset counter after triggering alert to prevent spamming
                    gaze_tracking_sessions[user_id] = 0
            else:
                # Looking at screen, reset counter
                gaze_tracking_sessions[user_id] = 0
    
    if alert_type:
        # Save image and record alert
        cv2.imwrite(file_path, img)
        conn = get_db_connection()
        # Defaulting exam_id to Null if not passed via the payload for simplicity on global scope
        exam_id = data.get('exam_id', None) 
        
        conn.execute('INSERT INTO cheating_alerts (exam_id, student_id, alert_type, screenshot_path) VALUES (?, ?, ?, ?)',
                     (exam_id, user_id, alert_type, relative_path))
        conn.commit()
        conn.close()
        return jsonify({'status': 'alert_recorded', 'type': alert_type})
        
    return jsonify({'status': 'ok'})

if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)
