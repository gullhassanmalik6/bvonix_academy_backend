# Backend (FastAPI + MongoDB)

## Setup

Create a virtualenv, install deps:

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Environment variables

This repo contains `env.example.txt` as a template.

Create `backend/.env` (not committed) and copy values from `env.example.txt`.

Minimum required:
- `MONGODB_URI`, `MONGODB_DB`
- `JWT_SECRET`

## Run

```bash
cd backend
.venv\Scripts\activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

API docs:
- Swagger: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## Endpoints (v1)

### Health
- `GET /api/health` - Health check
- `GET /` - API information

### Authentication
- `POST /api/auth/register` - Register new user
- `POST /api/auth/login` - Login and get JWT token
- `GET /api/auth/me` - Get current user (protected)

### Users
- `GET /api/users` - List all users (paginated, protected)
- `GET /api/users/{user_id}` - Get user by ID (protected)
- `PATCH /api/users/{user_id}` - Update user (protected)
- `DELETE /api/users/{user_id}` - Delete user (protected)

### Courses
- `GET /api/courses` - List all courses (paginated, protected)
  - Query params: `skip`, `limit`, `published_only`
- `GET /api/courses/{course_id}` - Get course by ID (protected)
- `GET /api/courses/instructor/{instructor_id}/courses` - Get courses by instructor (protected)
- `POST /api/courses` - Create new course (protected)
- `PATCH /api/courses/{course_id}` - Update course (protected)
- `DELETE /api/courses/{course_id}` - Delete course (protected)

### Instructors
- `GET /api/instructors` - List all instructors (paginated, protected)
- `GET /api/instructors/{instructor_id}` - Get instructor by ID (protected)
- `GET /api/instructors/user/{user_id}` - Get instructor by user_id (protected)
- `POST /api/instructors` - Create new instructor (protected)
- `PATCH /api/instructors/{instructor_id}` - Update instructor (protected)
- `DELETE /api/instructors/{instructor_id}` - Delete instructor (protected)

### Students
- `GET /api/students` - List all students (paginated, protected)
- `GET /api/students/{student_id}` - Get student by ID (protected)
- `GET /api/students/user/{user_id}` - Get student by user_id (protected)
- `POST /api/students` - Create new student (protected)
- `PATCH /api/students/{student_id}` - Update student (protected)
- `POST /api/students/{student_id}/enroll/{course_id}` - Enroll student in course (protected)
- `POST /api/students/{student_id}/unenroll/{course_id}` - Unenroll student from course (protected)
- `DELETE /api/students/{student_id}` - Delete student (protected)
