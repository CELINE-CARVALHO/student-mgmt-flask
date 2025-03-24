from flask import Flask, render_template, request, url_for, redirect, jsonify, Response, send_from_directory
from pymongo import MongoClient
from config import DB_URL
from bson import ObjectId
import csv
import os
import io
from datetime import datetime

client = MongoClient(DB_URL)
db = client['students']

app = Flask(__name__)
MEDIA_FOLDER = 'media/ProfilePicture'
app.config['MEDIA_FOLDER'] = 'media/ProfilePicture'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

if not os.path.exists(app.config['MEDIA_FOLDER']):
    os.makedirs(app.config['MEDIA_FOLDER'])

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/media/<path:filename>')
def media(filename):
    return send_from_directory(app.config['MEDIA_FOLDER'], filename)

@app.route('/')
def index():
    student_list = db.students.find({}).sort("regNo", 1)
    students = []

    for student in student_list:
        attendance = student.get('attendance', {})  
        if not isinstance(attendance, dict):
            attendance = {}  

        total_present = sum(subject.get('attended', 0) for subject in attendance.values() if isinstance(subject, dict))
        total_completed = sum(subject.get('total', 0) for subject in attendance.values() if isinstance(subject, dict))
        percentage = (total_present / total_completed) * 100 if total_completed > 0 else 0
        student['attendance_percentage'] = round(percentage, 2)
        students.append(student)

    return render_template('index.html', student_list=students)


# Complaint Portal
@app.route('/complaint-portal/', methods=['GET', 'POST'])
def complaint_portal():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        category = request.form['category']
        message = request.form['message']
        
        db.complaints.insert_one({
            'name': name,
            'email': email,
            'category': category,
            'message': message,
            'timestamp': datetime.now()
        })
        
        return redirect(url_for('complaint_portal'))

    complaints = list(db.complaints.find().sort("timestamp", -1))
    return render_template('complaint_portal.html', complaints=complaints)


@app.route('/add-student/', methods=['POST'])
def add_student():
    data = request.form
    db.students.insert_one({
        'name': data['name'],
        'regNo': data['registerNumber'],
        'class': data['class'],
        'email': data['email'],
        'phone': data['phone'],
        'club': data.get('club', "No Club"),
        'role': data.get('role', "Member"),
        'attendance': {}
    })
    return redirect(url_for('index'))


@app.route('/delete-student/<student_id>/')
def delete_student(student_id):
    db.students.delete_one({'_id': ObjectId(student_id)})
    return redirect(url_for('index'))


@app.route('/clubs/')
def clubs_page():
    return render_template('clubs.html')

@app.route('/get-club-member/<reg_no>', methods=['GET'])
def get_club_member(reg_no):
    student = db.students.find_one({"regNo": reg_no})
    if not student:
        return jsonify({"error": "Student not found"}), 404
    
    meeting_records = list(db.club_attendance.find({"student_id": student["_id"]}))
    return jsonify({
        "name": student.get("name", "Unknown"),
        "club": student.get("club", "No Club"),
        "role": student.get("role", "Member"),
        "meeting_records": [{
            "date": rec.get("date", "Unknown"),
            "status": rec.get("status", "Unknown")
        } for rec in meeting_records]
    })

@app.route('/mark-meeting-attendance/', methods=['POST'])
def mark_meeting_attendance():
    data = request.json
    reg_no = data.get('regNo')
    status = data.get('status')
    student = db.students.find_one({"regNo": reg_no})
    
    if not student:
        return jsonify({"error": "Student not found"}), 404

    db.club_attendance.insert_one({
        "student_id": student["_id"],
        "date": datetime.now().strftime("%Y-%m-%d"),
        "status": status
    })
    return jsonify({"message": "Attendance recorded successfully!"}), 200


# Update Student
@app.route('/update-student/<student_id>/', methods=['GET', 'POST'])
def update_student(student_id):
    if request.method == 'GET':
        student = db.students.find_one({'_id': ObjectId(student_id)})
        students = db.students.find({}).sort("regNo", 1)
        return render_template('index.html', student=student, student_list=students)
    else:
        name = request.form['name']
        regNo = request.form['registerNumber']
        st_class = request.form['class']
        email = request.form['email']
        phone = request.form['phone']

        db.students.update_one({'_id': ObjectId(student_id)}, {
            '$set': {
                'name': name,
                'regNo': regNo,
                'class': st_class,
                'email': email,
                'phone': phone
            }
        })
        db.students.update_one({'_id': ObjectId(id)}, {'$set': request.form})
        return redirect(url_for('index'))


# Timetable Page
@app.route('/timetable')
def timetable_page():
    return render_template('timetable.html')

# Add Course
@app.route('/add-course', methods=['POST'])
def add_course():
    data = request.json
    course_name = data.get('course_name')

    if not course_name:
        return jsonify({"error": "Course name is required"}), 400

    if db.courses.find_one({"name": course_name}):
        return jsonify({"error": "Course already exists!"}), 400

    db.courses.insert_one({"name": course_name})
    return jsonify({"message": "Course added successfully!"}), 200

# Fetch Courses
@app.route('/get-courses')
def get_courses():
    courses = list(db.courses.find({}, {"name": 1, "_id": 0}))
    return jsonify(courses)

# Add Subject with Duplicate Slot Prevention
@app.route('/add-subject', methods=['POST'])
def add_subject():
    data = request.json
    course_name = data.get('course_name')
    subject_name = data.get('subject_name')
    lecture_slot = data.get('lecture_slot')
    day = data.get('day')

    if not course_name or not subject_name or not lecture_slot or not day:
        return jsonify({"error": "All fields are required"}), 400

    existing_entry = db.timetable.find_one({"day": day, "lecture_slot": lecture_slot, "course": course_name})
    if existing_entry:
        return jsonify({"error": "A subject is already assigned to this slot for the selected course!"}), 400

    db.timetable.insert_one({
        "day": day,
        "course": course_name,
        "subject": subject_name,
        "lecture_slot": lecture_slot
    })
    return jsonify({"message": "Subject added successfully!"}), 200

# Fetch Weekly Timetable for Selected Course
@app.route('/get-weekly-timetable/<course_name>')
def get_weekly_timetable(course_name):
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
    slots = ["9:00-9:50", "10:00-10:50", "11:00-11:50", "12:00-12:50", "2:00-2:50", "3:00-3:50", "4:00-4:50"]

    weekly_timetable = []
    for day in days:
        row = {"day": day}
        for slot in slots:
            entry = db.timetable.find_one({"day": day, "lecture_slot": slot, "course": course_name}, {"_id": 0, "subject": 1})
            row[slot] = entry["subject"] if entry else ""
        weekly_timetable.append(row)

    return jsonify(weekly_timetable)

# Edit Timetable Entry
@app.route('/edit-subject', methods=['POST'])
def edit_subject():
    data = request.json
    day = data.get('day')
    lecture_slot = data.get('lecture_slot')
    new_subject = data.get('subject_name')
    course_name = data.get('course_name')

    if not day or not lecture_slot or not new_subject or not course_name:
        return jsonify({"error": "All fields are required"}), 400

    db.timetable.update_one(
        {"day": day, "lecture_slot": lecture_slot, "course": course_name},
        {"$set": {"subject": new_subject}}
    )
    return jsonify({"message": "Subject updated successfully!"}), 200

# Download Timetable as CSV for Selected Course
@app.route('/download-timetable/<course_name>')
def download_timetable(course_name):
    timetable = db.timetable.find({"course": course_name})
    output = io.StringIO()
    writer = csv.writer(output)

    # CSV Header
    writer.writerow(['Day', 'Course', 'Subject', 'Lecture Slot'])


    for entry in timetable:
        writer.writerow([
            entry.get('day', 'Unknown'), 
            entry.get('course', 'Unknown'), 
            entry.get('subject', 'Unknown'), 
            entry.get('lecture_slot', 'Unknown')
        ])

    output.seek(0)
    return Response(output, mimetype='text/csv', headers={"Content-Disposition": f"attachment; filename={course_name}_timetable.csv"})

@app.route('/register/', methods=['GET', 'POST'])
def user_register():
    if request.method == 'POST':
        db.users.insert_one(request.form)
        return redirect(url_for('user_login'))
    return render_template('user_register.html')


@app.route('/attendance/', methods=['GET','POST'])
def mark_attendance():
    if request.method == 'GET':    
        student_list = list(db.students.find({}).sort("regNo", 1))
        return render_template('attendance.html', student_list=student_list)
    elif request.method == 'POST':
        data = request.json
        for record in data:
            student_id = record.get('student_id')
            subject = record.get('subject')
            status = record.get('status')
            student = db.students.find_one({"_id": ObjectId(student_id)})
            if student:
                attendance = student.get('attendance', {})
                subject_data = attendance.get(subject, {'total': 0, 'attended': 0})
                subject_data['total'] += 1
                if status == "Present":
                    subject_data['attended'] += 1
                attendance[subject] = subject_data
                db.students.update_one({"_id": ObjectId(student_id)}, {"$set": {"attendance": attendance}})
        return jsonify({"message": "Attendance recorded successfully!"}), 200

@app.route('/students/', methods=['GET', 'POST'])
def students_page():
    student = None
    if request.method == 'POST':
        reg_no = request.form.get('regNo')
        student = db.students.find_one({"regNo": reg_no})
    return render_template('students.html', student=student)

@app.route('/export/')
def export_data():
    students = db.students.find({})
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Name', 'Register Number', 'Class', 'Email', 'Phone', 'Attendance %'])

    for student in students:
        attendance = student.get('attendance', {})
        total_present = sum(subject.get('attended', 0) for subject in attendance.values() if isinstance(subject, dict))
        total_completed = sum(subject.get('total', 0) for subject in attendance.values() if isinstance(subject, dict))
        percentage = (total_present / total_completed) * 100 if total_completed > 0 else 0
        writer.writerow([student['name'], student['regNo'], student['class'], student['email'], student['phone'], round(percentage, 2)])

    output.seek(0)
    return Response(output, mimetype='text/csv', headers={"Content-Disposition": "attachment;filename=students.csv"})

@app.route('/view_complaints')
def view_complaints():
    complaints = list(db.complaints.find().sort("timestamp", -1))  # Fetch complaints from MongoDB
    return render_template('view_complaints.html', complaints=complaints)


@app.route('/search-marks/', methods=['GET', 'POST'])
def search_marks():
    if request.method == 'POST':
        reg_no = request.form.get('regNo')
        student = db.students.find_one({'regNo': reg_no})

        if student:
            return redirect(url_for('marks', st_class=student['class'], regNo=student['regNo']))
        else:
            return render_template('search_marks.html', error="No student found.")
    return render_template('search_marks.html')


@app.route('/marks/<st_class>/<regNo>/', methods=['GET', 'POST'])
def marks(st_class, regNo):

    student = db.students.find_one({'regNo': regNo, 'class': st_class})

    error = None
    success = None

    if request.method == 'POST':
        subject = request.form.get('subject', '').strip()
        marks = request.form.get('marks', '').strip()

        if not subject or not marks:
            error = "All fields are required."
        elif not marks.isdigit() or not (0 <= int(marks) <= 100):
            error = "Marks must be between 0 and 100."
        else:
            existing_subjects = [mark['subject'].lower()
                                 for mark in student.get('marks', [])]
            if subject.lower() in existing_subjects:
                error = f"Marks for '{subject}' already exist."
            else:
                db.students.update_one(
                    {'regNo': regNo, 'class': st_class},
                    {'$push': {
                        'marks': {'subject': subject, 'marks': int(marks)}}}
                )

                student = db.students.find_one(
                    {'regNo': regNo, 'class': st_class})

                success = f"Marks for '{subject}' added successfully!"

    return render_template('marks.html', student=student, error=error, success=success)

  
## ryan (external activities)
UPLOAD_FOLDER = "media/certificates"
ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'gif'}

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/achievements/', methods=['GET', 'POST'])
def achievements():
    if request.method == 'GET':
        return render_template('achievements.html', student=None)  # Handle GET request gracefully
    
    reg_no = request.form['regNo']
    title = request.form['title']
    description = request.form['description']
    file = request.files['file']

    if file and allowed_file(file.filename):
        filename = file.filename
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

        achievements = {
            'title': title,
            'description': description,
            'file': filename
        }

        db.students.update_one(
            {'regNo': reg_no},
            {'$push': {'achievements': achievements}}
        )

        return redirect(url_for('view_student_by_reg_no', reg_no=reg_no))


@app.route('/student/<reg_no>')
def view_student_by_reg_no(reg_no):
    student = db.students.find_one({'regNo': reg_no})
    if not student:
        return "Student not found", 404
    return render_template('achievements.html', student=student)


@app.route('/remark')
def remark():
    student_list = list(db.students.find())

    for student in student_list:
        student["_id"] = str(student["_id"])  # Convert ObjectId to string for rendering
        if "remark" in student:
            for remark in student["remark"]:
                remark["date"] = remark["date"].strftime('%Y-%m-%d')  # Format date

    return render_template('remark.html', student_list=student_list)

@app.route('/add-Remark', methods=['POST'])
def add_remark():
    data = request.json  # Get data from frontend

    regNo = data.get("regNo")
    title = data.get("title")
    description = data.get("description")
    date = data.get("date")
    category = data.get("category")

    # Validate required fields
    if not all([regNo, title, description, date, category]):
        return jsonify({"error": "All fields are required!"}), 400

    # Find the student by regNo
    student = db.students.find_one({"regNo": regNo})
    if not student:
        return jsonify({"error": "Student not found!"}), 404

    # Create remark entry
    new_remark = {
        "title": title,
        "description": description,
        "date": datetime.strptime(date, "%Y-%m-%d"),  # Convert string to date
        "category": category
    }

    # Add the remark to the student's remark list
    db.students.update_one(
        {"_id": student["_id"]},
        {"$push": {"remark": new_remark}}
    )

    return jsonify({"message": "Remark added successfully!"}), 200

@app.route('/delete-remark', methods=['DELETE'])
def delete_remark():
    data = request.json  # Get JSON data from frontend

    regNo = data.get("regNo")  # Get the student's register number
    title = data.get("title")  # Get the remark title

    # Find the student
    student = students_collection.find_one({"regNo": regNo})

    if not student:
        return jsonify({"error": "Student not found!"}), 404

    # Remove the specific remark
    students_collection.update_one(
        {"_id": student["_id"]},
        {"$pull": {"remark": {"title": title}}}  # Remove remark with matching title
    )

    return jsonify({"message": "Remark deleted successfully!"}), 200

 
@app.route('/leave/', methods=['GET', 'POST'])
def leave_page():
    db = client['students']  # Get database connection

    if request.method == 'GET':
        students = list(db.students.find({}, {"_id": 1, "name": 1, "regNo": 1}))  # Fetch student list
        return render_template('leave.html', students=students)  

    if request.headers.get('Content-Type') != 'application/json':
        return jsonify({"error": "Unsupported Media Type. Expected application/json."}), 415

    data = request.get_json()
    if not isinstance(data, list):
        return jsonify({"error": "Invalid data format"}), 400

    for record in data:
        student_id = record.get('student_id')
        date = datetime.strptime(record.get('date'), "%Y-%m-%d")
        reason = record.get('reason')
        status = "Pending"  # Default status

        student = db.students.find_one({"_id": ObjectId(student_id)})

        if student:
            leave_request = {
                "student_id": ObjectId(student_id),
                "date": date,
                "reason": reason,
                "status": status,
                "applied_on": datetime.utcnow()
            }

            db.leaves.insert_one(leave_request)

    return jsonify({"message": "Leave application submitted successfully!"}), 200



# Hostel Leave Request Page
@app.route('/hostel_leave/', methods=['GET', 'POST'])
def hostel_leave_page():
    if request.method == 'POST':
        data = request.form
        leave_request = {
            'student_name': data['student_name'],
            'reg_no': data['reg_no'],
            'reason': data['reason'],
            'from_date': data['from_date'],
            'to_date': data['to_date'],
            'status': 'Pending'
        }
        db.hostel_leave.insert_one(leave_request)
        return redirect(url_for('hostel_leave_page'))

    leave_requests = list(db.hostel_leave.find())
    return render_template('hostel_leave.html', leave_requests=leave_requests)

# Approve or Reject Leave Request
@app.route('/update-leave/<id>/<action>/', methods=['POST'])
def update_leave_status(id, action):
    if action in ['approve', 'reject']:
        status = 'Approved' if action == 'approve' else 'Rejected'
        db.hostel_leave.update_one({'_id': ObjectId(id)}, {'$set': {'status': status}})
    return redirect(url_for('hostel_leave_page'))



@app.route('/get-student/<reg_no>', methods=['GET'])
def get_student(reg_no):
    student = db.students.find_one({"regNo": reg_no})

    if not student:
        return jsonify({"error": "Student not found"}), 404

    attendance_records = list(db.attendance.find({"student_id": student["_id"]}))
    
    subject_wise = {}
    for record in attendance_records:
        subject = record.get("subject", "Unknown") 
        if subject not in subject_wise:
            subject_wise[subject] = {"total": 0, "attended": 0}

        subject_wise[subject]["total"] += 1
        if record.get("status") == "Present":
            subject_wise[subject]["attended"] += 1

    total_attended = sum(data["attended"] for data in subject_wise.values())
    total_classes = sum(data["total"] for data in subject_wise.values())
    overall_attendance = (total_attended / total_classes * 100) if total_classes else 100.0

    return jsonify({
        "name": student.get("name", "Unknown"),
        "overall_attendance": round(overall_attendance, 2),
        "subject_wise": subject_wise,
        "attendance_records": [{
            "subject": rec.get("subject", "Unknown"),
            "date": rec.get("date", "").strftime("%Y-%m-%d") if rec.get("date") else "Unknown",
            "period": rec.get("period", "Unknown"),
            "status": rec.get("status", "Unknown")
        } for rec in attendance_records]
    })


if __name__ == '_main_':
    app.run(debug=True)