import os

from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import User
from billing.models import BankAccount
from catalog.models import Category, Course
from tenancy.models import Academy, AcademyLicense, AcademyBankAccount, AcademyCategory, AcademyCourse, AcademyMembership


class Command(BaseCommand):
    help = 'Migra datos legados a una academia inicial. Solo se ejecuta con --force o MIGRATE_LEGACY_TENANCY=1.'

    def add_arguments(self, parser):
        parser.add_argument('--force', action='store_true', help='Ejecuta la migración de datos legados.')

    @transaction.atomic
    def handle(self, *args, **options):
        enabled = options.get('force') or os.getenv('MIGRATE_LEGACY_TENANCY', '0') == '1'
        if not enabled:
            self.stdout.write('Bootstrap legado omitido. La plataforma queda lista para crear academias desde cero.')
            return

        academy, _ = Academy.objects.get_or_create(
            slug='devlayer-academy',
            defaults={'name': 'Devlayer Academy', 'contact_email': 'info@devlayerstudio.com', 'is_active': True},
        )
        AcademyLicense.objects.get_or_create(
            academy=academy,
            defaults={'plan_name': 'Licencia inicial', 'status': AcademyLicense.Status.ACTIVE, 'max_users': 0},
        )

        role_map = {
            User.Role.OWNER: AcademyMembership.Role.OWNER,
            User.Role.PROFESSOR: AcademyMembership.Role.PROFESSOR,
            User.Role.ADMIN: AcademyMembership.Role.ADMIN,
        }
        for user in User.objects.filter(is_superuser=False):
            AcademyMembership.objects.get_or_create(
                academy=academy,
                user_id=user.pk,
                defaults={
                    'role': role_map.get(user.role, AcademyMembership.Role.STUDENT),
                    'status': AcademyMembership.Status.ACTIVE,
                },
            )

        for course in Course.objects.all():
            target = academy
            membership = AcademyMembership.objects.filter(user_id=course.created_by_id).select_related('academy').first()
            if membership:
                target = membership.academy
            AcademyCourse.objects.get_or_create(course_id=course.pk, defaults={'academy': target})

        for category in Category.objects.all():
            binding = AcademyCategory.objects.filter(category_id=category.pk).first()
            if binding:
                continue
            course_binding = AcademyCourse.objects.filter(
                course_id__in=Course.objects.filter(category=category).values_list('id', flat=True)
            ).select_related('academy').first()
            AcademyCategory.objects.create(category_id=category.pk, academy=course_binding.academy if course_binding else academy)

        for bank in BankAccount.objects.all():
            AcademyBankAccount.objects.get_or_create(bank_account_id=bank.pk, defaults={'academy': academy})

        self.stdout.write(self.style.SUCCESS(f'Datos legados vinculados a: {academy.name}'))
