#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="/srv/eagna"
SRC_DIR="$PROJECT_ROOT/src"
VENV_DIR="$PROJECT_ROOT/venv"
SERVICE_NAME="eagna"

cd "$PROJECT_ROOT"

source "$VENV_DIR/bin/activate"

python3 - <<'PY' > /tmp/eagna_env_exports.sh
from pathlib import Path
import shlex

env_path = Path("/srv/eagna/.env")

for raw_line in env_path.read_text().splitlines():
    line = raw_line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue

    key, value = line.split("=", 1)
    key = key.strip()
    value = value.strip()

    if len(value) >= 2 and (
        (value[0] == value[-1] == '"') or
        (value[0] == value[-1] == "'")
    ):
        value = value[1:-1]

    print(f"export {key}={shlex.quote(value)}")
PY

source /tmp/eagna_env_exports.sh
rm -f /tmp/eagna_env_exports.sh

cd "$SRC_DIR"

echo "==> Dropping and recreating public schema..."
python manage.py dbshell <<'SQL'
DROP SCHEMA public CASCADE;
CREATE SCHEMA public;
GRANT ALL ON SCHEMA public TO public;
SQL

echo "==> Clearing media..."
rm -rf media/*

echo "==> Creating fresh migrations..."
find apps/accounts/migrations -type f ! -name "__init__.py" -delete
find apps/accounts/migrations -type d -name "__pycache__" -exec rm -rf {} +

python manage.py makemigrations
python manage.py migrate --noinput
python manage.py collectstatic --noinput

echo "==> Seeding full TU dataset..."
python manage.py shell <<'PY'
import io
import random
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone
from PIL import Image, ImageDraw
from pptx import Presentation
from pptx.util import Inches

from apps.accounts.document_parsing import parse_uploaded_office_file
from apps.accounts.models import (
    User,
    StudentProfile,
    LecturerProfile,
    Course,
    AcademicYear,
    Module,
    ModulePlacement,
    ModuleOffering,
    ModuleOfferingEnrollmentStudent,
    ModuleOfferingEnrollmentLecturer,
    ModuleWeek,
    ModuleWeekFile,
    Assignment,
    AssignmentFile,
    AssignmentSubmission,
    AssignmentGrade,
    Quiz,
    QuizQuestion,
    QuizOption,
    QuizAttempt,
    QuizAnswer,
    ModuleAnnouncement,
)
from apps.accounts.views import (
    _sync_current_module_offerings,
    _start_new_academic_year_transition,
    _persist_parsed_document,
)

# ----------------------------
# Config
# ----------------------------

CODE_RNG = random.Random(856857858)
DATA_RNG = random.Random(471856857858)

ADMIN_EMAIL = "cdavis471@outlook.com"
ADMIN_PASSWORD = "DevPass123!"
ADMIN_FIRST_NAME = "Conor"
ADMIN_LAST_NAME = "Davis"

LECTURER_PASSWORD = "DevPass123!"
STUDENT_PASSWORD = "DevPass123!"

ACADEMIC_YEARS = [
    ("2022/23", date(2022, 9, 1), date(2023, 5, 31)),
    ("2023/24", date(2023, 9, 1), date(2024, 5, 31)),
    ("2024/25", date(2024, 9, 1), date(2025, 5, 31)),
    ("2025/26", date(2025, 9, 1), date(2026, 5, 31)),
]

COURSE_SOURCES = [
    {
        "code": "TU856",
        "title": "BSc in Computer Science",
        "length_years": 4,
    },
    {
        "code": "TU857",
        "title": "BSc in Computer Science (Infrastructure)",
        "length_years": 4,
    },
    {
        "code": "TU858",
        "title": "BSc in Computer Science (International)",
        "length_years": 4,
    },
]

M = "MANDATORY"
E = "ELECTIVE"

COURSE_CATALOG = {
    "TU856": {
        1: {
            1: [
                ("Communications", M),
                ("IT Fundamentals", M),
                ("Mathematics 1", M),
                ("Program Design", M),
                ("Programming", M),
                ("Web Development 1", M),
            ],
            2: [
                ("Algorithm Design and Problem Solving", M),
                ("Computer Architecture and Technology", M),
                ("Microprocessor Systems", M),
                ("Operating Systems 1", M),
                ("Programming", M),
                ("Data Exploration", M),
            ],
        },
        2: {
            1: [
                ("Databases 1", M),
                ("Mathematics II", M),
                ("Object Oriented Programming", M),
                ("Operating Systems 2", M),
                ("Software Engineering 1", M),
                ("Web Development 2", M),
            ],
            2: [
                ("GenAI-Assisted Programming", M),
                ("Algorithms & Data Structures", M),
                ("Data Communications", M),
                ("Human Computer Interaction", M),
                ("Legal and Professional Issues", M),
                ("Software Engineering 2", M),
            ],
        },
        3: {
            1: [
                ("Client Serving Programming", M),
                ("Cloud Computing", M),
                ("Databases 2", M),
                ("Mobile Software Development", M),
                ("Software Engineering 3", M),
                ("Introduction to Artificial Intelligence", M),
                ("Individual Project", E),
                ("Study Abroad 1", E),
                ("Study Abroad 2", E),
                ("Study Abroad 3", E),
                ("Study Abroad 4", E),
            ],
            2: [
                ("Business & Enterprise", E),
                ("Individual Project", E),
                ("Mobile Robotics", E),
                ("Service-Learning & Civic Engagement", E),
                ("Team Project", E),
                ("Universal Design & Assistive Technology", E),
                ("Work Placement", E),
                ("Introduction to DevOps", E),
                ("Cryptography & Cyber Security", E),
                ("Software Testing", E),
                ("Global Classroom", E),
                ("Study Abroad 5", E),
                ("Study Abroad 6", E),
                ("Study Abroad 7", E),
                ("Study Abroad 8", E),
            ],
        },
        4: {
            1: [
                ("Final Year Project", M),
                ("Advanced Databases", E),
                ("Advanced Security 1", E),
                ("Machine Learning for Data Analytics", E),
                ("Distributed Systems", E),
                ("Forensics", E),
                ("Games Engines 1", E),
                ("Rich Web Application Technology", E),
                ("Advanced Web Mapping", E),
                ("Fundamentals of IoT", E),
                ("Image Processing", E),
            ],
            2: [
                ("Final Year Project", M),
                ("Advanced Security 2", E),
                ("Artificial Intelligence", E),
                ("Bioinformatics", E),
                ("Enterprise Application Development", E),
                ("Enterprise Sys Inf. and Arch.", E),
                ("Games Engines 2", E),
                ("Geographical Info Systems", E),
                ("Environmental Analytics", E),
                ("Systems Software", E),
                ("Visualizing Data", E),
            ],
        },
    },
    "TU857": {
        1: {
            1: [
                ("Building a PC", M),
                ("Communications and Personal Development", M),
                ("Introduction to Operating Systems", M),
                ("IT Fundamentals", M),
                ("Program Design", M),
                ("Programming", M),
            ],
            2: [
                ("Introduction to Algorithms", M),
                ("Mathematics 1", M),
                ("Network Fundamentals", M),
                ("Programming", M),
                ("Team Computing", M),
                ("Data Exploration", M),
            ],
        },
        2: {
            1: [
                ("Legal and Professional Issues", M),
                ("Microprocessors", M),
                ("Networking 2", M),
                ("Operating Systems and System Administration", M),
                ("System Infrastructure and Architecture 1", M),
                ("Object Oriented Programming", E),
            ],
            2: [
                ("GenAI-Assisted Programming", M),
                ("Databases 1", M),
                ("Human Computer Interaction", M),
                ("Internet Applications and Web Development", M),
                ("Mathematics II", M),
                ("Networking 3", M),
            ],
        },
        3: {
            1: [
                ("Cloud Computing", M),
                ("Databases 2", M),
                ("Mobile Software Development", M),
                ("Networking Programming", M),
                ("Web Development & Deployment", M),
                ("Introduction to DevOps", M),
                ("Individual Project", E),
                ("Study Abroad 1", E),
                ("Study Abroad 2", E),
                ("Study Abroad 3", E),
                ("Study Abroad 4", E),
            ],
            2: [
                ("Business & Enterprise", E),
                ("Individual Project", E),
                ("Mobile Robotics", E),
                ("Service-Learning & Civic Engagement", E),
                ("Systems Infrastructure and Architecture 2", E),
                ("Team Project", E),
                ("Universal Design & Assistive Technology", E),
                ("Work Placement", E),
                ("Cryptography & Cyber Security", E),
                ("Software Testing", E),
                ("Global Classroom", E),
                ("Study Abroad 5", E),
                ("Study Abroad 6", E),
                ("Study Abroad 7", E),
                ("Study Abroad 8", E),
            ],
        },
        4: {
            1: [
                ("Advanced Security 1", M),
                ("Final Year Project", M),
                ("Systems Integration", M),
                ("Advanced Databases", E),
                ("Machine Learning for Data Analytics", E),
                ("Distributed Systems", E),
                ("Forensics", E),
                ("Games Engines 1", E),
                ("Rich Web Application Technology", E),
                ("Advanced Web Mapping", E),
                ("Fundamentals of IoT", E),
                ("Image Processing", E),
            ],
            2: [
                ("Advanced Security 2", M),
                ("Final Year Project", M),
                ("System and Database Administration", M),
                ("Artificial Intelligence", E),
                ("Bioinformatics", E),
                ("Enterprise Application Development", E),
                ("Games Engines 2", E),
                ("Geographical Info Systems", E),
                ("Environmental Analytics", E),
                ("Systems Software", E),
                ("Visualizing Data", E),
            ],
        },
    },
    "TU858": {
        1: {
            1: [
                ("Global Citizenship (Professional and Ethical Communications)", M),
                ("Mathematics 1", M),
                ("Program Design", M),
                ("Programming", M),
                ("Web Development 1", M),
                ("Chinese Language and Culture 1", E),
                ("German Language 1B", E),
                ("Korean Language and Culture 1", E),
            ],
            2: [
                ("Algorithm Design and Problem Solving", M),
                ("Computer Architecture and Technology", M),
                ("Operating Systems 1", M),
                ("Programming", M),
                ("Software for the Global Market 1 (User Interface Design)", M),
                ("Chinese Language and Culture 1", E),
                ("German Language 1B", E),
                ("Korean Language and Culture 1", E),
            ],
        },
        2: {
            1: [
                ("Databases 1", M),
                ("Mathematics II", M),
                ("Object Oriented Programming", M),
                ("Operating Systems 2", M),
                ("Software Engineering 1", M),
                ("Chinese Language and Culture 2", E),
                ("German Language 2B", E),
                ("Korean Language and Culture 2", E),
            ],
            2: [
                ("GenAI-Assisted Programming", M),
                ("Algorithms & Data Structures", M),
                ("Data Communications", M),
                ("Legal and Professional Issues", M),
                ("Software for the Global Market 2 (Internationalisation & Localisation)", M),
                ("Chinese Language and Culture 2", E),
                ("German Language 2B", E),
                ("Korean Language and Culture 2", E),
            ],
        },
        3: {
            1: [
                ("Software Engineering 2", M),
                ("Client Serving Programming", M),
                ("Databases 2", M),
                ("Mobile Software Development", M),
                ("Web Development & Deployment", M),
                ("Chinese Language and Culture 3", E),
                ("Cloud Computing", E),
                ("Introduction to Artificial Intelligence", E),
                ("English for Academic Purposes (EAP) Intermediate 1", E),
                ("English for Academic Purposes (EAP) Upper Intermediate 1", E),
                ("English for Academic Purposes (EAP) Advanced 1", E),
                ("German Language 1A", E),
                ("Study Abroad 1", E),
                ("Study Abroad 2", E),
                ("Study Abroad 3", E),
                ("Study Abroad 4", E),
                ("Irish Cultural Studies 1A", E),
                ("Korean Language and Culture 3", E),
            ],
            2: [
                ("Business & Enterprise", E),
                ("Individual Project", E),
                ("Mobile Robotics", E),
                ("Universal Design & Assistive Technology", E),
                ("Work Placement", E),
                ("Introduction to DevOps", E),
                ("Cryptography & Cyber Security", E),
                ("Software Testing", E),
                ("English for Academic Purposes (EAP) Intermediate 2", E),
                ("English for Academic Purposes (EAP) Upper Intermediate 2", E),
                ("English for Academic Purposes (EAP) Advanced 2", E),
                ("Global Classroom", E),
                ("Study Abroad 5", E),
                ("Study Abroad 6", E),
                ("Study Abroad 7", E),
                ("Study Abroad 8", E),
                ("Irish Cultural Studies 1A", E),
            ],
        },
        4: {
            1: [
                ("Final Year Project", M),
                ("Advanced Databases", E),
                ("Advanced Security 1", E),
                ("Machine Learning for Data Analytics", E),
                ("Distributed Systems", E),
                ("Forensics", E),
                ("Games Engines 1", E),
                ("Rich Web Application Technology", E),
                ("Advanced Web Mapping", E),
                ("Fundamentals of IoT", E),
                ("Image Processing", E),
            ],
            2: [
                ("Final Year Project", M),
                ("Advanced Security 2", E),
                ("Artificial Intelligence", E),
                ("Bioinformatics", E),
                ("Enterprise Application Development", E),
                ("Enterprise Sys Inf. and Arch.", E),
                ("Games Engines 2", E),
                ("Geographical Info Systems", E),
                ("Environmental Analytics", E),
                ("Systems Software", E),
                ("Visualizing Data", E),
            ],
        },
    },
}

FIRST_NAMES = [
    "Aoife", "Eoin", "Niamh", "Cian", "Saoirse", "Ciara", "Darragh", "Orla",
    "Ronan", "Clodagh", "Aisling", "Padraig", "Fiona", "Tadhg", "Grainne",
    "Lorcan", "Maeve", "Conall", "Sinead", "Oisin", "Aideen", "Finn", "Roisin",
    "Caoimhe", "Sean", "Laura", "Declan", "Emma", "Shane", "Megan", "Brendan",
    "Kelly", "Patrick", "Holly", "Jack", "Sarah", "Tom", "Leah", "Mark", "Kate",
]

LAST_NAMES = [
    "Murphy", "Rogers", "Kelly", "Byrne", "Walsh", "Ryan", "Dunne", "Fitzgerald",
    "OBrien", "Murray", "Quinn", "Doyle", "McCarthy", "Lynch", "Farrell", "Power",
    "Daly", "Nolan", "Reilly", "Kavanagh", "Kennedy", "Hughes", "Moore", "Griffin",
    "Hayes", "Whelan", "Carroll", "Keane", "Brennan", "Foley", "OConnor", "Casey",
    "Clarke", "Healy", "Malone", "Coffey", "Gorman", "Flanagan", "Noonan", "Boland",
]

STUDENT_FIRST_NAMES = [
    "Alex", "Sam", "Jamie", "Taylor", "Jordan", "Casey", "Riley", "Morgan", "Avery", "Quinn",
    "Dylan", "Harper", "Rowan", "Parker", "Bailey", "Hayden", "Reese", "Finley", "Cameron", "Skyler",
]

STUDENT_LAST_NAMES = [
    "Byrne", "Murphy", "Kelly", "Doyle", "Ryan", "Walsh", "OBrien", "Murray", "Quinn", "Nolan",
    "Power", "Kennedy", "Clarke", "Farrell", "Kavanagh", "Foley", "Hayes", "Casey", "Brennan", "Moore",
]

# ----------------------------
# Helpers
# ----------------------------

from collections import defaultdict, deque

USED_MODULE_CODES = set()
MODULE_CODE_BY_KEY = {}

def generate_cmpu_code() -> str:
    while True:
        code = f"CMPU{CODE_RNG.randint(1000, 9999)}"
        if code not in USED_MODULE_CODES:
            USED_MODULE_CODES.add(code)
            return code

def get_module_code_for_key(module_key: str) -> str:
    existing = MODULE_CODE_BY_KEY.get(module_key)
    if existing:
        return existing

    code = generate_cmpu_code()
    MODULE_CODE_BY_KEY[module_key] = code
    return code

def normalise_catalog_title(title: str) -> str:
    replacements = {
        "Fundmentals of IoT": "Fundamentals of IoT",
    }
    return replacements.get(title, title)

def dedupe_semester_modules(modules: list[tuple[str, str]]) -> list[tuple[str, str]]:
    seen = set()
    deduped = []

    for title, status in modules:
        title = normalise_catalog_title(title)
        key = (title, status)
        if key in seen:
            continue
        seen.add(key)
        deduped.append((title, status))

    return deduped

def build_course_blueprints():
    blueprints = {}

    for course_info in COURSE_SOURCES:
        course_code = course_info["code"]
        raw_years = COURSE_CATALOG[course_code]
        course_map = {}

        print(f"Building local module catalog for {course_code} ...")

        for year_num, semester_map in raw_years.items():
            year_items = []

            for semester_num, modules in semester_map.items():
                for title, status in dedupe_semester_modules(modules):
                    if title == "Final Year Project":
                        module_key = f"FYP::{course_code}"
                    else:
                        module_key = title

                    year_items.append(
                        {
                            "title": title,
                            "status": status,
                            "semester": semester_num,
                            "code": get_module_code_for_key(module_key),
                        }
                    )

            if not year_items:
                raise RuntimeError(f"No modules defined for {course_code} year {year_num}")

            course_map[year_num] = year_items

        blueprints[course_code] = {
            "course": course_info,
            "years": course_map,
        }

    return blueprints

def lecturer_name_generator():
    counter = 1
    for first in FIRST_NAMES:
        for last in LAST_NAMES:
            yield {
                "first_name": first,
                "last_name": last,
                "email": f"{first.lower()}.{last.lower()}@tudublin.ie",
                "staff_id": f"L{counter:04d}",
            }
            counter += 1

def student_name(counter: int):
    first = STUDENT_FIRST_NAMES[counter % len(STUDENT_FIRST_NAMES)]
    last = STUDENT_LAST_NAMES[counter % len(STUDENT_LAST_NAMES)]
    return first, last

def build_stage_module_selection(course_year_items: list[dict]) -> list[dict]:
    mandatory = []
    elective = []
    seen_codes = set()

    for item in sorted(course_year_items, key=lambda x: (x["semester"], x["title"])):
        if item["code"] in seen_codes:
            continue
        seen_codes.add(item["code"])

        if item["status"] == "MANDATORY":
            mandatory.append(item)
        else:
            elective.append(item)

    target = min(len(seen_codes), DATA_RNG.randint(8, 10))
    selection = list(mandatory)
    selected_codes = {item["code"] for item in selection}

    for item in elective:
        if len(selected_codes) >= target and len(selected_codes) >= 8:
            break
        if item["code"] in selected_codes:
            continue
        selection.append(item)
        selected_codes.add(item["code"])

    if len(selected_codes) < 8:
        for item in elective:
            if item["code"] in selected_codes:
                continue
            selection.append(item)
            selected_codes.add(item["code"])
            if len(selected_codes) >= 8:
                break

    return selection

def make_aware_dt(d: date, hour: int = 9, minute: int = 0):
    return timezone.make_aware(datetime.combine(d, time(hour, minute)))

def build_generic_image_bytes(label: str) -> bytes:
    image = Image.new("RGB", (640, 240), color=(7, 22, 77))
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 20, 620, 220), outline=(173, 216, 230), width=4)
    draw.text((40, 95), label[:40], fill=(255, 255, 255))
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()

def build_pptx_bytes(title: str, subtitle: str, bullets: list[str]) -> bytes:
    presentation = Presentation()

    slide = presentation.slides.add_slide(presentation.slide_layouts[1])
    slide.shapes.title.text = title
    slide.placeholders[1].text = subtitle

    slide2 = presentation.slides.add_slide(presentation.slide_layouts[1])
    slide2.shapes.title.text = "Key Points"
    tf = slide2.placeholders[1].text_frame
    tf.clear()
    for idx, bullet in enumerate(bullets, start=1):
        p = tf.add_paragraph() if idx > 1 else tf.paragraphs[0]
        p.text = bullet

    image_bytes = build_generic_image_bytes(title)
    image_stream = io.BytesIO(image_bytes)
    slide2.shapes.add_picture(image_stream, Inches(6.0), Inches(1.5), width=Inches(2.5))

    out = io.BytesIO()
    presentation.save(out)
    return out.getvalue()

def attach_and_parse_week_file(week: ModuleWeek, lecturer_user: User):
    filename = f"{week.offering.module.code.lower()}-week-{week.week_number}.pptx"
    payload = build_pptx_bytes(
        title=f"{week.offering.module.title} - Week {week.week_number}",
        subtitle=f"{week.offering.course.code} · {week.offering.academic_year.label}",
        bullets=[
            f"Weekly topic for {week.offering.module.title}",
            "Accessible notes deck generated by seed script",
            "Contains text and one image for parser coverage",
        ],
    )

    week_file = ModuleWeekFile.objects.create(
        week=week,
        original_name=filename,
        uploaded_by=lecturer_user,
    )
    week_file.file.save(filename, ContentFile(payload), save=True)

    try:
        parsed_payload = parse_uploaded_office_file(week_file.file)
        _persist_parsed_document(parsed_payload=parsed_payload, week_file=week_file)
    except Exception as exc:
        print(f"WARNING: Week file parse failed for {filename}: {exc}")

def attach_and_parse_assignment_file(assignment: Assignment, lecturer_user: User):
    filename = f"{assignment.offering.module.code.lower()}-assignment-brief.pptx"
    payload = build_pptx_bytes(
        title=f"{assignment.title}",
        subtitle=f"{assignment.offering.course.code} · {assignment.offering.academic_year.label}",
        bullets=[
            "Read the brief carefully",
            "Follow the submission instructions",
            "This generated file is parsed into accessible HTML",
        ],
    )

    assignment_file = AssignmentFile.objects.create(
        assignment=assignment,
        original_name=filename,
        uploaded_by=lecturer_user,
    )
    assignment_file.file.save(filename, ContentFile(payload), save=True)

    try:
        parsed_payload = parse_uploaded_office_file(assignment_file.file)
        _persist_parsed_document(parsed_payload=parsed_payload, assignment_file=assignment_file)
    except Exception as exc:
        print(f"WARNING: Assignment file parse failed for {filename}: {exc}")

def create_quiz_questions(quiz: Quiz):
    prompts = [
        ("Multiple choice", QuizQuestion.Type.MULTIPLE_CHOICE, [
            ("Correct answer", True),
            ("Option 2", False),
            ("Option 3", False),
            ("Option 4", False),
        ]),
        ("True or false", QuizQuestion.Type.TRUE_FALSE, [
            ("True", True),
            ("False", False),
        ]),
        ("Multiple select", QuizQuestion.Type.MULTIPLE_SELECT, [
            ("Correct option 1", True),
            ("Correct option 2", True),
            ("Distractor 1", False),
            ("Distractor 2", False),
        ]),
    ]

    for idx, (stem, qtype, options) in enumerate(prompts, start=1):
        question = QuizQuestion.objects.create(
            quiz=quiz,
            prompt=f"{quiz.offering.module.title}: {stem} question {idx}",
            question_type=qtype,
            marks=Decimal("1.00"),
            display_order=idx,
        )
        for option_text, is_correct in options:
            QuizOption.objects.create(
                question=question,
                option_text=option_text,
                is_correct=is_correct,
            )

def create_assignment_submissions(assignment: Assignment):
    lecturer_enrolment = assignment.offering.lecturer_enrolments.order_by("-is_primary", "id").first()
    marker = lecturer_enrolment.lecturer if lecturer_enrolment else None

    students = list(
        StudentProfile.objects.filter(
            offering_enrolments__offering=assignment.offering
        ).distinct().order_by("id")[:3]
    )

    for idx, student in enumerate(students, start=1):
        submission = AssignmentSubmission.objects.create(
            assignment=assignment,
            student=student,
            status=AssignmentSubmission.Status.SUBMITTED,
        )
        if idx <= 2:
            AssignmentGrade.objects.create(
                submission=submission,
                marker=marker,
                value=Decimal("68.00") + idx,
                feedback_text="Generated feedback for seeded submission.",
            )

def create_quiz_attempts(quiz: Quiz):
    students = list(
        StudentProfile.objects.filter(
            offering_enrolments__offering=quiz.offering
        ).distinct().order_by("id")[:3]
    )
    questions = list(quiz.questions.prefetch_related("options").all())

    for student in students:
        attempt = QuizAttempt.objects.create(
            quiz=quiz,
            student=student,
            started_at=timezone.now() - timedelta(days=2),
            submitted_at=timezone.now() - timedelta(days=1),
            status=QuizAttempt.Status.SUBMITTED,
            score=Decimal("2.00"),
            weighted_score=Decimal("66.67"),
        )
        for question in questions:
            correct_options = list(question.options.filter(is_correct=True))
            selected = correct_options[0] if correct_options else question.options.first()
            QuizAnswer.objects.create(
                attempt=attempt,
                question=question,
                selected_option=selected,
                selected_text=selected.option_text if selected else "",
                is_correct=bool(selected and selected.is_correct),
                marks_awarded=Decimal("1.00") if selected and selected.is_correct else Decimal("0.00"),
            )

def lecturer_name_generator():
    counter = 1
    for first in FIRST_NAMES:
        for last in LAST_NAMES:
            yield {
                "first_name": first,
                "last_name": last,
                "email": f"{first.lower()}.{last.lower()}@tudublin.ie",
                "staff_id": f"L{counter:04d}",
            }
            counter += 1

def student_name(counter: int):
    first = STUDENT_FIRST_NAMES[counter % len(STUDENT_FIRST_NAMES)]
    last = STUDENT_LAST_NAMES[counter % len(STUDENT_LAST_NAMES)]
    return first, last

def build_stage_module_selection(course_year_items: list[dict]) -> list[dict]:
    mandatory = []
    elective = []
    seen_codes = set()

    for item in sorted(course_year_items, key=lambda x: (x["semester"], x["title"])):
        if item["code"] in seen_codes:
            continue
        seen_codes.add(item["code"])

        if item["status"] == "MANDATORY":
            mandatory.append(item)
        else:
            elective.append(item)

    target = min(len(seen_codes), RNG.randint(8, 10))
    selection = list(mandatory)
    selected_codes = {item["code"] for item in selection}

    for item in elective:
        if len(selected_codes) >= max(target, len(selected_codes)):
            if len(selected_codes) >= 8:
                break
        if item["code"] in selected_codes:
            continue
        selection.append(item)
        selected_codes.add(item["code"])
        if len(selected_codes) >= target and len(selected_codes) >= 8:
            break

    if len(selected_codes) < 8:
        for item in elective:
            if item["code"] in selected_codes:
                continue
            selection.append(item)
            selected_codes.add(item["code"])
            if len(selected_codes) >= 8:
                break

    return selection

def make_aware_dt(d: date, hour: int = 9, minute: int = 0):
    return timezone.make_aware(datetime.combine(d, time(hour, minute)))

def build_generic_image_bytes(label: str) -> bytes:
    image = Image.new("RGB", (640, 240), color=(7, 22, 77))
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 20, 620, 220), outline=(173, 216, 230), width=4)
    draw.text((40, 95), label[:40], fill=(255, 255, 255))
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()

def build_pptx_bytes(title: str, subtitle: str, bullets: list[str]) -> bytes:
    presentation = Presentation()

    slide = presentation.slides.add_slide(presentation.slide_layouts[1])
    slide.shapes.title.text = title
    slide.placeholders[1].text = subtitle

    slide2 = presentation.slides.add_slide(presentation.slide_layouts[1])
    slide2.shapes.title.text = "Key Points"
    tf = slide2.placeholders[1].text_frame
    tf.clear()
    for idx, bullet in enumerate(bullets, start=1):
        p = tf.add_paragraph() if idx > 1 else tf.paragraphs[0]
        p.text = bullet

    image_bytes = build_generic_image_bytes(title)
    image_stream = io.BytesIO(image_bytes)
    slide2.shapes.add_picture(image_stream, Inches(6.0), Inches(1.5), width=Inches(2.5))

    out = io.BytesIO()
    presentation.save(out)
    return out.getvalue()

def attach_and_parse_week_file(week: ModuleWeek, lecturer_user: User):
    filename = f"{week.offering.module.code.lower()}-week-{week.week_number}.pptx"
    payload = build_pptx_bytes(
        title=f"{week.offering.module.title} - Week {week.week_number}",
        subtitle=f"{week.offering.course.code} · {week.offering.academic_year.label}",
        bullets=[
            f"Weekly topic for {week.offering.module.title}",
            "Accessible notes deck generated by seed script",
            "Contains text and one image for parser coverage",
        ],
    )

    week_file = ModuleWeekFile.objects.create(
        week=week,
        original_name=filename,
        uploaded_by=lecturer_user,
    )
    week_file.file.save(filename, ContentFile(payload), save=True)

    try:
        parsed_payload = parse_uploaded_office_file(week_file.file)
        _persist_parsed_document(parsed_payload=parsed_payload, week_file=week_file)
    except Exception as exc:
        print(f"WARNING: Week file parse failed for {filename}: {exc}")

def attach_and_parse_assignment_file(assignment: Assignment, lecturer_user: User):
    filename = f"{assignment.offering.module.code.lower()}-assignment-brief.pptx"
    payload = build_pptx_bytes(
        title=f"{assignment.title}",
        subtitle=f"{assignment.offering.course.code} · {assignment.offering.academic_year.label}",
        bullets=[
            "Read the brief carefully",
            "Follow the submission instructions",
            "This generated file is parsed into accessible HTML",
        ],
    )

    assignment_file = AssignmentFile.objects.create(
        assignment=assignment,
        original_name=filename,
        uploaded_by=lecturer_user,
    )
    assignment_file.file.save(filename, ContentFile(payload), save=True)

    try:
        parsed_payload = parse_uploaded_office_file(assignment_file.file)
        _persist_parsed_document(parsed_payload=parsed_payload, assignment_file=assignment_file)
    except Exception as exc:
        print(f"WARNING: Assignment file parse failed for {filename}: {exc}")

def create_quiz_questions(quiz: Quiz):
    prompts = [
        ("Multiple choice", QuizQuestion.Type.MULTIPLE_CHOICE, [
            ("Correct answer", True),
            ("Option 2", False),
            ("Option 3", False),
            ("Option 4", False),
        ]),
        ("True or false", QuizQuestion.Type.TRUE_FALSE, [
            ("True", True),
            ("False", False),
        ]),
        ("Multiple select", QuizQuestion.Type.MULTIPLE_SELECT, [
            ("Correct option 1", True),
            ("Correct option 2", True),
            ("Distractor 1", False),
            ("Distractor 2", False),
        ]),
    ]

    for idx, (stem, qtype, options) in enumerate(prompts, start=1):
        question = QuizQuestion.objects.create(
            quiz=quiz,
            prompt=f"{quiz.offering.module.title}: {stem} question {idx}",
            question_type=qtype,
            marks=Decimal("1.00"),
            display_order=idx,
        )
        for option_text, is_correct in options:
            QuizOption.objects.create(
                question=question,
                option_text=option_text,
                is_correct=is_correct,
            )

def create_assignment_submissions(assignment: Assignment):
    lecturer_enrolment = assignment.offering.lecturer_enrolments.order_by("-is_primary", "id").first()
    marker = lecturer_enrolment.lecturer if lecturer_enrolment else None

    students = list(
        StudentProfile.objects.filter(
            offering_enrolments__offering=assignment.offering
        ).distinct().order_by("id")[:3]
    )

    for idx, student in enumerate(students, start=1):
        submission = AssignmentSubmission.objects.create(
            assignment=assignment,
            student=student,
            status=AssignmentSubmission.Status.SUBMITTED,
        )
        if idx <= 2:
            AssignmentGrade.objects.create(
                submission=submission,
                marker=marker,
                value=Decimal("68.00") + idx,
                feedback_text="Generated feedback for seeded submission.",
            )

def create_quiz_attempts(quiz: Quiz):
    students = list(
        StudentProfile.objects.filter(
            offering_enrolments__offering=quiz.offering
        ).distinct().order_by("id")[:3]
    )
    questions = list(quiz.questions.prefetch_related("options").all())

    for student in students:
        attempt = QuizAttempt.objects.create(
            quiz=quiz,
            student=student,
            started_at=timezone.now() - timedelta(days=2),
            submitted_at=timezone.now() - timedelta(days=1),
            status=QuizAttempt.Status.SUBMITTED,
            score=Decimal("2.00"),
            weighted_score=Decimal("66.67"),
        )
        for question in questions:
            correct_options = list(question.options.filter(is_correct=True))
            selected = correct_options[0] if correct_options else question.options.first()
            QuizAnswer.objects.create(
                attempt=attempt,
                question=question,
                selected_option=selected,
                selected_text=selected.option_text if selected else "",
                is_correct=bool(selected and selected.is_correct),
                marks_awarded=Decimal("1.00") if selected and selected.is_correct else Decimal("0.00"),
            )

# ----------------------------
# Seed process
# ----------------------------

@transaction.atomic
def main():
    if User.objects.exists() or Course.objects.exists() or Module.objects.exists():
        raise SystemExit("Database is not empty. This script expects a fresh schema.")

    blueprints = build_course_blueprints()

    print("Creating admin...")
    admin = User.objects.create_user(
        username=ADMIN_EMAIL,
        email=ADMIN_EMAIL,
        password=ADMIN_PASSWORD,
        first_name=ADMIN_FIRST_NAME,
        last_name=ADMIN_LAST_NAME,
        role=User.Role.ADMIN,
        is_staff=True,
        is_superuser=True,
    )

    print("Creating courses...")
    course_objects = {}
    for source in COURSE_SOURCES:
        course_objects[source["code"]] = Course.objects.create(
            code=source["code"],
            title=source["title"],
            length_years=source["length_years"],
            is_active=True,
        )

    print("Creating earliest academic year...")
    earliest_label, earliest_start, earliest_end = ACADEMIC_YEARS[0]
    current_year = AcademicYear.objects.create(
        label=earliest_label,
        start_date=earliest_start,
        end_date=earliest_end,
        is_current=True,
    )

    print("Creating modules and placements...")
    module_objects = {}
    placement_objects = {}
    fyp_keys = set()

    for course_code, blueprint in blueprints.items():
        course = course_objects[course_code]
        all_items = []
        for year_num in blueprint["years"].values():
            all_items.extend(year_num)

        unique_items = {}
        for item in all_items:
            if item["title"] == "Final Year Project":
                key = f"FYP::{course_code}"
                fyp_keys.add(key)
            else:
                key = item["code"]
            if key not in unique_items:
                unique_items[key] = item

        for key, item in unique_items.items():
            if key in fyp_keys:
                module_code = f"{item['code']}-{course_code}"
                module_title = "Final Year Project"
            else:
                module_code = item["code"]
                module_title = item["title"]

            if key not in module_objects:
                module_objects[key] = Module.objects.create(
                    code=module_code,
                    title=module_title,
                    is_active=True,
                )

            placement = ModulePlacement.objects.create(
                module=module_objects[key],
                course=course,
                available_now=True,
                available_next_rollover=True,
            )
            placement_objects[(course_code, key)] = placement

    created_2022 = _sync_current_module_offerings(current_year)
    print(f"Created {created_2022} current offerings for {current_year.label}.")

    print("Creating lecturers and assigning them to 2022/23 offerings...")
    lecturer_gen = lecturer_name_generator()
    lecturer_assignment_map = {}

    for key, module in module_objects.items():
        primary_seed = next(lecturer_gen)
        primary_user = User.objects.create_user(
            username=primary_seed["email"],
            email=primary_seed["email"],
            password=LECTURER_PASSWORD,
            first_name=primary_seed["first_name"],
            last_name=primary_seed["last_name"],
            role=User.Role.LECTURER,
        )
        primary_profile = LecturerProfile.objects.create(
            user=primary_user,
            staff_id=primary_seed["staff_id"],
        )

        secondary_profile = None
        if key in fyp_keys:
            secondary_seed = next(lecturer_gen)
            secondary_user = User.objects.create_user(
                username=secondary_seed["email"],
                email=secondary_seed["email"],
                password=LECTURER_PASSWORD,
                first_name=secondary_seed["first_name"],
                last_name=secondary_seed["last_name"],
                role=User.Role.LECTURER,
            )
            secondary_profile = LecturerProfile.objects.create(
                user=secondary_user,
                staff_id=secondary_seed["staff_id"],
            )

        lecturer_assignment_map[key] = (primary_profile, secondary_profile)

        offerings = ModuleOffering.objects.filter(
            academic_year=current_year,
            placement__module=module,
        ).select_related("placement__course")

        for offering in offerings:
            ModuleOfferingEnrollmentLecturer.objects.get_or_create(
                offering=offering,
                lecturer=primary_profile,
                defaults={"is_primary": True},
            )
            if secondary_profile:
                ModuleOfferingEnrollmentLecturer.objects.get_or_create(
                    offering=offering,
                    lecturer=secondary_profile,
                    defaults={"is_primary": False},
                )

    print("Rolling forward academic years...")
    for _ in range(3):
        summary = _start_new_academic_year_transition(AcademicYear.objects.get(is_current=True))
        print(
            f"Rolled into {summary['next_year'].label} "
            f"(placements updated={summary['placement_updates']}, "
            f"offerings created={summary['created_offerings']}, "
            f"lecturers copied={summary['copied_lecturers']})"
        )

    all_years = list(AcademicYear.objects.order_by("start_date"))
    current_year = AcademicYear.objects.get(is_current=True)

    print("Preparing stage selections...")
    stage_selection_map = {}
    for course_code, blueprint in blueprints.items():
        stage_selection_map[course_code] = {}
        for stage_num in range(1, 5):
            stage_selection_map[course_code][stage_num] = build_stage_module_selection(
                blueprint["years"][stage_num]
            )

    print("Creating students and historical/current enrolments...")
    student_counter = 20400000

    for course_code in ["TU856", "TU857", "TU858"]:
        for current_stage in range(1, 5):
            cohort_size = DATA_RNG.randint(80, 100)
            relevant_years = all_years[-current_stage:]

            print(f"  {course_code} stage {current_stage}: {cohort_size} students")

            for _ in range(cohort_size):
                student_counter += 1
                student_number = f"C{student_counter:08d}"
                email = f"{student_number}@mytudublin.ie"
                first_name, last_name = student_name(student_counter)

                user = User.objects.create_user(
                    username=email,
                    email=email,
                    password=STUDENT_PASSWORD,
                    first_name=first_name,
                    last_name=last_name,
                    role=User.Role.STUDENT,
                )
                student = StudentProfile.objects.create(
                    user=user,
                    student_number=student_number,
                    course=course_code,
                    status=StudentProfile.Status.ACTIVE,
                )

                for stage_index, academic_year in enumerate(relevant_years, start=1):
                    selected_modules = stage_selection_map[course_code][stage_index]

                    for selected_module in selected_modules:
                        if selected_module["title"] == "Final Year Project":
                            module_key = f"FYP::{course_code}"
                        else:
                            module_key = selected_module["code"]

                        placement = placement_objects[(course_code, module_key)]
                        offering = ModuleOffering.objects.get(
                            placement=placement,
                            academic_year=academic_year,
                        )
                        ModuleOfferingEnrollmentStudent.objects.get_or_create(
                            offering=offering,
                            student=student,
                        )

    print("Creating module announcements, weeks, assignments/quizzes, and parsed files...")
    offerings = list(
        ModuleOffering.objects.select_related(
            "placement__module",
            "placement__course",
            "academic_year",
        ).prefetch_related("lecturer_enrolments__lecturer__user")
    )

    now = timezone.now()

    for offering in offerings:
        lecturer_enrolments = list(offering.lecturer_enrolments.select_related("lecturer__user").all())
        primary_lecturer = next((e.lecturer for e in lecturer_enrolments if e.is_primary), None)
        if not primary_lecturer and lecturer_enrolments:
            primary_lecturer = lecturer_enrolments[0].lecturer

        created_by = primary_lecturer.user if primary_lecturer else admin

        ModuleAnnouncement.objects.create(
            offering=offering,
            title=f"Welcome to {offering.module.title}",
            content=(
                f"This is an automatically generated module announcement for "
                f"{offering.module.title} in {offering.academic_year.label}."
            ),
            created_by=created_by,
        )

        week_total = 10 if offering.is_current else 12
        for week_number in range(1, week_total + 1):
            week = ModuleWeek.objects.create(
                offering=offering,
                week_number=week_number,
                title=f"Week {week_number}",
                description=(
                    f"Generated teaching content for {offering.module.title}, "
                    f"week {week_number}, {offering.academic_year.label}."
                ),
            )

            # Keep parsed content present without exploding media size:
            # attach one parsed file to Week 1 only.
            if week_number == 1:
                attach_and_parse_week_file(week, created_by)

        is_fyp = offering.module.title == "Final Year Project"
        assessment_type = "assignment" if is_fyp or (sum(ord(c) for c in offering.module.code) % 2 == 0) else "quiz"

        if offering.is_current:
            assign_due = now + timedelta(days=14)
            quiz_open = now - timedelta(days=2)
            quiz_close = now + timedelta(days=5)
        else:
            base_day = offering.academic_year.start_date + timedelta(days=84)
            assign_due = make_aware_dt(base_day, 17, 0)
            quiz_open = make_aware_dt(base_day - timedelta(days=7), 9, 0)
            quiz_close = make_aware_dt(base_day, 17, 0)

        if assessment_type == "assignment":
            assignment = Assignment.objects.create(
                offering=offering,
                title=f"{offering.module.title} Coursework",
                description=f"Generated assignment for {offering.module.title}.",
                due_datetime=assign_due,
                max_mark=Decimal("100.00"),
            )
            attach_and_parse_assignment_file(assignment, created_by)
            create_assignment_submissions(assignment)
        else:
            quiz = Quiz.objects.create(
                offering=offering,
                title=f"{offering.module.title} Quiz",
                description=f"Generated quiz for {offering.module.title}.",
                open_datetime=quiz_open,
                close_datetime=quiz_close,
                time_limit_minutes=20,
                max_attempts=1,
                max_mark=Decimal("100.00"),
                is_published=True,
            )
            create_quiz_questions(quiz)
            create_quiz_attempts(quiz)

    print("")
    print("Seed complete.")
    print(f"Admin: {ADMIN_EMAIL} / {ADMIN_PASSWORD}")
    print("Student / Lecturer demo password: DevPass123!")
    print(f"Current academic year: {current_year.label}")
    print(f"Total students: {StudentProfile.objects.count()}")
    print(f"Total lecturers: {LecturerProfile.objects.count()}")
    print(f"Total courses: {Course.objects.count()}")
    print(f"Total modules: {Module.objects.count()}")
    print(f"Total placements: {ModulePlacement.objects.count()}")
    print(f"Total offerings: {ModuleOffering.objects.count()}")

main()
PY

echo "==> Restarting ${SERVICE_NAME}..."
sudo systemctl restart "$SERVICE_NAME"

echo "==> Done."