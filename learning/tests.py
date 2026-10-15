from django.test import TestCase
from accounts.models import User
from catalog.models import Category, Course
from .models import Enrollment
from .services import create_or_activate_enrollment

class EnrollmentAccessTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(email='admin2@test.local', password='TestPass123!')
        self.student = User.objects.create_user(email='student2@test.local', password='TestPass123!', email_verified=True)
        category = Category.objects.create(name='Dev', slug='dev')
        self.course = Course.objects.create(title='Dev Course', slug='dev-course', category=category, created_by=self.admin, final_exam_required=False)

    def test_block_one_enrollment(self):
        enrollment = create_or_activate_enrollment(self.student, self.course)
        self.assertTrue(enrollment.access_allowed())
        enrollment.status = Enrollment.Status.BLOCKED
        enrollment.save()
        self.assertFalse(enrollment.access_allowed())
