from django.test import TestCase
from accounts.models import User
from catalog.models import Category, Course
from learning.services import create_or_activate_enrollment
from .services import issue_certificate_if_eligible

class CertificateTests(TestCase):
    def test_empty_optional_course_can_certify(self):
        admin = User.objects.create_superuser(email='admin3@test.local', password='TestPass123!')
        student = User.objects.create_user(email='student3@test.local', password='TestPass123!', email_verified=True)
        category = Category.objects.create(name='Demo', slug='demo-cert')
        course = Course.objects.create(title='Demo Cert', slug='demo-cert-course', category=category, created_by=admin, final_exam_required=False)
        enrollment = create_or_activate_enrollment(student, course)
        certificate = issue_certificate_if_eligible(enrollment)
        self.assertIsNotNone(certificate)
        self.assertEqual(certificate.enrollment, enrollment)
