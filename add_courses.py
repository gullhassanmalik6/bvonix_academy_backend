"""
Script to add all BvoniX Academy courses to the database.

This script:
1. Creates a default instructor (if needed)
2. Adds all courses from the Academy curriculum
"""

import asyncio
import sys
from datetime import datetime, timezone

from bson import ObjectId

from app.core.config import get_settings
from app.db.mongodb import make_client
from app.core.security import hash_password
from app.repositories.user_repository import UserRepository
from app.repositories.instructor_repository import InstructorRepository
from app.repositories.course_repository import CourseRepository


# All courses data from the document
COURSES_DATA = [
    # Core Development Courses
    {
        "title": "Python Development (Backend & API Development)",
        "description": """Master Python fundamentals, backend frameworks, and API development. Learn database integration and build real-world backend applications.

Skills Learned:
• Python fundamentals
• Backend frameworks
• API development
• Database integration

Outcomes:
• Can work as a backend developer
• Can create APIs for clients
• Can support AI and automation projects

Earning Options:
• Freelancing (backend services)
• Junior backend developer job
• Paid internships""",
        "duration_hours": 120,
        "price": 15000.0,
        "category": "Core Development",
        "is_published": True,
    },
    {
        "title": "Web Development (Frontend & Backend)",
        "description": """Learn frontend and backend web development, SaaS product creation, and website deployment. Build complete web applications from scratch.

Skills Learned:
• Frontend & backend web development
• SaaS product creation
• Website deployment

Outcomes:
• Build websites for clients
• Launch own SaaS projects

Earning Options:
• Freelancing & remote jobs
• Google AdSense
• Selling SaaS services""",
        "duration_hours": 150,
        "price": 18000.0,
        "category": "Core Development",
        "is_published": True,
    },
    {
        "title": "Full Stack Development",
        "description": """Become a complete full stack developer. Learn frontend + backend, databases & deployment, and the complete project lifecycle.

Skills Learned:
• Frontend + backend
• Databases & deployment
• Complete project lifecycle

Outcomes:
• Become job-ready full stack developer
• Build real-world applications

Earning Options:
• Freelancing
• Full-time jobs
• Startup projects""",
        "duration_hours": 200,
        "price": 25000.0,
        "category": "Core Development",
        "is_published": True,
    },
    {
        "title": "Android App Development",
        "description": """Build and launch Android applications. Learn app development, testing, deployment, and Play Store publishing.

Skills Learned:
• Android app development
• App testing & deployment
• Play Store publishing

Outcomes:
• Build and launch own apps
• Work on client apps

Earning Options:
• Client-based app development
• App monetization (Ads, in-app purchases)
• Freelancing""",
        "duration_hours": 140,
        "price": 17000.0,
        "category": "Core Development",
        "is_published": True,
    },
    # AI & Automation Courses
    {
        "title": "AI Development (AI Applications & Integrations)",
        "description": """Build AI-powered applications and integrate AI into real-world projects. Learn AI application development and chatbot creation.

Skills Learned:
• AI application development
• AI chatbot creation
• AI integrations

Outcomes:
• Build AI-powered applications
• Work on AI projects for clients

Earning Options:
• AI freelancing
• Startup product development
• Software house projects""",
        "duration_hours": 130,
        "price": 20000.0,
        "category": "AI & Automation",
        "is_published": True,
    },
    {
        "title": "AI Chatbot Development",
        "description": """Specialized course on creating intelligent chatbots using AI. Learn to build conversational AI systems for businesses.

Skills Learned:
• AI chatbot architecture
• Natural language processing
• Integration with platforms

Outcomes:
• Build production-ready chatbots
• Deploy chatbots for clients

Earning Options:
• Chatbot development services
• SaaS chatbot products
• Freelancing""",
        "duration_hours": 80,
        "price": 15000.0,
        "category": "AI & Automation",
        "is_published": True,
    },
    {
        "title": "AI Agent Development (Code & No-Code)",
        "description": """Develop AI agents using both coding and no-code approaches. Learn to create intelligent automation agents.

Skills Learned:
• AI agent architecture
• Code-based agent development
• No-code agent creation

Outcomes:
• Build custom AI agents
• Create sellable AI solutions

Earning Options:
• Selling AI agents
• Client automation projects
• Subscription-based tools""",
        "duration_hours": 100,
        "price": 18000.0,
        "category": "AI & Automation",
        "is_published": True,
    },
    {
        "title": "Automation & Workflow Development (n8n, tools)",
        "description": """Master workflow automation using n8n and other tools. Learn to automate business processes and create efficient workflows.

Skills Learned:
• Workflow automation
• n8n platform mastery
• Business process automation

Outcomes:
• Build automation tools
• Create sellable automation solutions

Earning Options:
• Selling automation workflows
• Client automation projects
• Subscription-based automation services""",
        "duration_hours": 90,
        "price": 16000.0,
        "category": "AI & Automation",
        "is_published": True,
    },
    # Digital & Business Skills Courses
    {
        "title": "Digital Marketing",
        "description": """Master digital marketing strategies. Learn social media marketing, SEO, paid ads, analytics, and reporting.

Skills Learned:
• Social media marketing
• SEO & paid ads
• Analytics & reporting

Outcomes:
• Manage brand growth
• Handle marketing campaigns

Earning Options:
• Client-based marketing work
• Agency roles
• Freelancing""",
        "duration_hours": 100,
        "price": 12000.0,
        "category": "Digital & Business Skills",
        "is_published": True,
    },
    {
        "title": "Freelancing & Remote Work Mastery",
        "description": """Learn to become a successful freelancer. Master client communication, proposal writing, and project management.

Skills Learned:
• Client communication
• Proposal writing
• Project management

Outcomes:
• Independent earning mindset
• Sales & client acquisition skills

Earning Options:
• Fiverr / Upwork
• Remote client work
• Commission-based sales""",
        "duration_hours": 60,
        "price": 8000.0,
        "category": "Digital & Business Skills",
        "is_published": True,
    },
    {
        "title": "Client Handling & Sales Skills for Tech Professionals",
        "description": """Develop essential sales and client management skills specifically for tech professionals. Learn to close deals and maintain client relationships.

Skills Learned:
• Client relationship management
• Sales techniques for tech services
• Negotiation skills

Outcomes:
• Better client retention
• Higher project success rate
• Increased earning potential

Earning Options:
• Higher-value projects
• Long-term client relationships
• Commission-based earnings""",
        "duration_hours": 50,
        "price": 7000.0,
        "category": "Digital & Business Skills",
        "is_published": True,
    },
    # Earning-Focused & Special Courses
    {
        "title": "SaaS Product Development",
        "description": """Learn to build and launch SaaS products. Master product development, monetization strategies, and scaling techniques.

Skills Learned:
• SaaS architecture
• Product development lifecycle
• Monetization strategies

Outcomes:
• Launch your own SaaS
• Understand recurring revenue models

Earning Options:
• Own SaaS products
• Subscription revenue
• Product-based income""",
        "duration_hours": 160,
        "price": 22000.0,
        "category": "Earning-Focused",
        "is_published": True,
    },
    {
        "title": "App Monetization & Play Store Earnings",
        "description": """Master app monetization strategies. Learn to generate revenue from Android apps through ads, in-app purchases, and subscriptions.

Skills Learned:
• App monetization strategies
• Play Store optimization
• Revenue optimization

Outcomes:
• Generate passive income from apps
• Maximize app revenue

Earning Options:
• App ad revenue
• In-app purchases
• Subscription models""",
        "duration_hours": 70,
        "price": 10000.0,
        "category": "Earning-Focused",
        "is_published": True,
    },
    {
        "title": "AI Tools Selling & Subscription Models",
        "description": """Learn to create and sell AI tools. Master subscription models, pricing strategies, and marketing for AI products.

Skills Learned:
• AI product development
• Subscription model setup
• Marketing AI tools

Outcomes:
• Launch sellable AI tools
• Generate recurring revenue

Earning Options:
• AI tool subscriptions
• Product sales
• Recurring revenue""",
        "duration_hours": 90,
        "price": 15000.0,
        "category": "Earning-Focused",
        "is_published": True,
    },
    {
        "title": "No-Code / Low-Code Business Automation",
        "description": """Master no-code and low-code platforms for business automation. Learn to create automation solutions without extensive coding.

Skills Learned:
• No-code platforms
• Low-code development
• Business automation

Outcomes:
• Build automation without coding
• Create sellable solutions

Earning Options:
• Automation services
• Product sales
• Client projects""",
        "duration_hours": 80,
        "price": 12000.0,
        "category": "Earning-Focused",
        "is_published": True,
    },
    # Internship & Career Programs
    {
        "title": "Industry Internship Program (During Course)",
        "description": """Get real-world experience through our industry internship program. Work on actual projects from our software house during your course.

Program Features:
• Real projects from software house
• Performance-based job offers
• Only competent students hired
• Industry experience during course

Outcomes:
• Real-world project experience
• Industry connections
• Potential job offers

Earning Options:
• Paid internships
• Performance-based hiring
• Job opportunities""",
        "duration_hours": 240,
        "price": 0.0,  # Internship program
        "category": "Internship & Career",
        "is_published": True,
    },
    {
        "title": "Job Readiness & Interview Preparation",
        "description": """Prepare for tech job interviews and become job-ready. Learn interview techniques, resume building, and career planning.

Skills Learned:
• Interview preparation
• Resume building
• Career planning
• Technical interview skills

Outcomes:
• Job-ready skills
• Interview confidence
• Career clarity

Earning Options:
• Better job opportunities
• Higher salary negotiations
• Career advancement""",
        "duration_hours": 40,
        "price": 5000.0,
        "category": "Internship & Career",
        "is_published": True,
    },
    {
        "title": "Startup & Entrepreneurship Fundamentals",
        "description": """Learn the fundamentals of starting and running a tech startup. Master entrepreneurship skills, business planning, and funding strategies.

Skills Learned:
• Startup fundamentals
• Business planning
• Funding strategies
• Entrepreneurship mindset

Outcomes:
• Understand startup ecosystem
• Create business plans
• Develop entrepreneurial skills

Earning Options:
• Start your own business
• Join startups
• Entrepreneurial ventures""",
        "duration_hours": 60,
        "price": 10000.0,
        "category": "Internship & Career",
        "is_published": True,
    },
]


async def get_or_create_default_instructor(db):
    """Get or create a default instructor for courses."""
    user_repo = UserRepository(db)
    instructor_repo = InstructorRepository(db)
    
    # Check if default instructor user exists
    default_email = "instructor@bvonix.academy"
    user = await user_repo.get_by_email(default_email)
    
    if user:
        print(f"[INFO] Found existing instructor user: {user.email}")
        instructor = await instructor_repo.get_by_user_id(user.id)
        if instructor:
            print(f"[INFO] Found existing instructor profile: {instructor.id}")
            return instructor.id
        else:
            # Create instructor profile
            instructor = await instructor_repo.create_instructor(
                user_id=user.id,
                bio="Default instructor for BvoniX Academy courses",
                specialization="Full Stack Development, AI & Automation",
                years_of_experience=10,
            )
            print(f"[OK] Created instructor profile: {instructor.id}")
            return instructor.id
    else:
        # Create default instructor user
        print("[INFO] Creating default instructor user...")
        hashed_password = hash_password("DefaultInstructor123!")
        user = await user_repo.create_user(
            email=default_email,
            full_name="BvoniX Academy Instructor",
            hashed_password=hashed_password,
        )
        print(f"[OK] Created instructor user: {user.id}")
        
        # Create instructor profile
        instructor = await instructor_repo.create_instructor(
            user_id=user.id,
            bio="Default instructor for BvoniX Academy courses. Experienced in full stack development, AI, and automation.",
            specialization="Full Stack Development, AI & Automation, Digital Marketing",
            years_of_experience=10,
        )
        print(f"[OK] Created instructor profile: {instructor.id}")
        return instructor.id


async def add_courses():
    """Add all courses to the database."""
    settings = get_settings()
    
    # Connect to MongoDB
    client = make_client(settings)
    db = client[settings.mongodb_db]
    
    try:
        print("=" * 60)
        print("BvoniX Academy - Course Seeding Script")
        print("=" * 60)
        print()
        
        # Get or create default instructor
        instructor_id = await get_or_create_default_instructor(db)
        print()
        
        # Create course repository
        course_repo = CourseRepository(db)
        
        # Add all courses
        print(f"Adding {len(COURSES_DATA)} courses...")
        print()
        
        added_count = 0
        skipped_count = 0
        
        for course_data in COURSES_DATA:
            title = course_data["title"]
            
            # Check if course already exists
            existing = await course_repo.collection.find_one({"title": title})
            if existing:
                print(f"[SKIP] Course already exists: {title}")
                skipped_count += 1
                continue
            
            # Create course
            try:
                course = await course_repo.create_course(
                    title=title,
                    description=course_data["description"],
                    instructor_id=instructor_id,
                    duration_hours=course_data["duration_hours"],
                    price=course_data["price"],
                    is_published=course_data["is_published"],
                )
                print(f"[OK] Added: {title}")
                print(f"      Category: {course_data['category']}")
                print(f"      Duration: {course_data['duration_hours']} hours")
                print(f"      Price: Rs. {course_data['price']:,.0f}")
                print()
                added_count += 1
            except Exception as e:
                print(f"[ERROR] Failed to add: {title}")
                print(f"        Error: {e}")
                print()
        
        print("=" * 60)
        print("Summary:")
        print(f"  - Added: {added_count} courses")
        print(f"  - Skipped: {skipped_count} courses (already exist)")
        print(f"  - Total: {len(COURSES_DATA)} courses")
        print("=" * 60)
        print()
        print("[SUCCESS] Course seeding completed!")
        
    except Exception as e:
        print(f"[ERROR] Failed to seed courses: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(add_courses())
