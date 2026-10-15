from django.test import TestCase
from accounts.models import User
from catalog.models import Category, Course
from learning.models import Enrollment
from .models import Order, Payment
from .services import approve_payment

class PaymentActivationTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(email='admin@test.local', password='TestPass123!')
        self.student = User.objects.create_user(email='student@test.local', password='TestPass123!', email_verified=True)
        category = Category.objects.create(name='Python', slug='python')
        self.course = Course.objects.create(title='Curso', slug='curso', category=category, price=25, created_by=self.admin, final_exam_required=False)

    def test_approved_payment_creates_enrollment(self):
        order = Order.objects.create(user=self.student, course=self.course, amount=25)
        payment = Payment.objects.create(order=order, amount=25)
        approve_payment(payment, self.admin)
        self.assertTrue(Enrollment.objects.filter(user=self.student, course=self.course, status=Enrollment.Status.ACTIVE).exists())
