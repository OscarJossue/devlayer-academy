from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from billing.models import BankAccount
from tenancy.models import Academy, AcademyLicense, AcademyMembership, AcademyPlan
from tenancy.services import bind_bank, bind_user

User = get_user_model()


PLANS = [
    {
        'name': 'Inicial', 'code': 'inicial', 'description': 'Para academias pequeñas que comienzan a vender formación en línea.',
        'max_students': 100, 'max_professors': 5, 'max_admins': 2, 'price': 49, 'currency': 'USD', 'duration_days': 30,
    },
    {
        'name': 'Profesional', 'code': 'profesional', 'description': 'Para academias con varios profesores y una comunidad en crecimiento.',
        'max_students': 500, 'max_professors': 15, 'max_admins': 5, 'price': 149, 'currency': 'USD', 'duration_days': 30,
    },
    {
        'name': 'Empresarial', 'code': 'empresarial', 'description': 'Mayor capacidad para instituciones y operaciones con múltiples equipos.',
        'max_students': 2000, 'max_professors': 50, 'max_admins': 15, 'price': 349, 'currency': 'USD', 'duration_days': 30,
    },
]

ACADEMIES = [
    {
        'name': 'Academia Horizonte', 'slug': 'academia-horizonte', 'brand_color': '#1769E0',
        'tagline': 'Aprende habilidades que abren nuevas oportunidades.',
        'public_description': 'Academia demo para probar el plan Inicial y el flujo de transferencias.',
        'plan': 'inicial', 'owner_email': 'dueno.horizonte@demo.local', 'owner_password': 'Horizonte2026!',
        'owner_first': 'Andrea', 'owner_last': 'Horizonte', 'payment_transfer_enabled': True, 'payment_whatsapp_enabled': True, 'payment_whatsapp_number': '593985721899', 'support_whatsapp_2_label': 'Contabilidad', 'support_whatsapp_2_number': '593985721899',
        'bank': ('Banco Pichincha', 'Ahorros', '2200010010', 'Academia Horizonte Demo'),
    },
    {
        'name': 'Nova Tech Academy', 'slug': 'nova-tech', 'brand_color': '#6544E5',
        'tagline': 'Tecnología práctica para construir el futuro.',
        'public_description': 'Academia demo con identidad violeta, plan Profesional y pagos mixtos.',
        'plan': 'profesional', 'owner_email': 'dueno.nova@demo.local', 'owner_password': 'NovaTech2026!',
        'owner_first': 'Carlos', 'owner_last': 'Nova', 'payment_transfer_enabled': True, 'payment_whatsapp_enabled': True,
        'payment_whatsapp_number': '593999000222',
        'bank': ('Banco Guayaquil', 'Corriente', '1100020020', 'Nova Tech Academy Demo'),
    },
    {
        'name': 'Impulso Academy', 'slug': 'impulso-academy', 'brand_color': '#D97706',
        'tagline': 'Convierte conocimiento en crecimiento real.',
        'public_description': 'Academia demo para revisar el plan Empresarial, color naranja y pagos por WhatsApp.',
        'plan': 'empresarial', 'owner_email': 'dueno.impulso@demo.local', 'owner_password': 'Impulso2026!',
        'owner_first': 'María', 'owner_last': 'Impulso', 'payment_transfer_enabled': False, 'payment_whatsapp_enabled': True,
        'payment_whatsapp_number': '593999000333', 'bank': None,
    },
]


class Command(BaseCommand):
    help = 'Crea tres planes y tres academias demo; Academia Horizonte incluye dos profesores y dos cursos completos.'

    @transaction.atomic
    def handle(self, *args, **options):
        plan_map = {}
        for data in PLANS:
            plan, _ = AcademyPlan.objects.update_or_create(code=data['code'], defaults=data)
            plan_map[data['code']] = plan

        today = timezone.localdate()
        for data in ACADEMIES:
            plan = plan_map[data['plan']]
            academy, _ = Academy.objects.update_or_create(
                slug=data['slug'],
                defaults={
                    'name': data['name'], 'contact_email': data['owner_email'], 'brand_color': data['brand_color'],
                    'tagline': data['tagline'], 'public_description': data['public_description'], 'is_active': True,
                    'payment_transfer_enabled': data['payment_transfer_enabled'],
                    'payment_whatsapp_enabled': data['payment_whatsapp_enabled'],
                    'payment_whatsapp_number': data.get('payment_whatsapp_number', ''),
                    'support_whatsapp_1_label': data.get('support_whatsapp_1_label', ''),
                    'support_whatsapp_1_number': data.get('support_whatsapp_1_number', ''),
                    'support_whatsapp_2_label': data.get('support_whatsapp_2_label', ''),
                    'support_whatsapp_2_number': data.get('support_whatsapp_2_number', ''),
                    'payment_instructions': 'Usa el código de la orden como referencia y sube un comprobante legible.',
                },
            )
            AcademyLicense.objects.update_or_create(
                academy=academy,
                defaults={
                    'plan': plan, 'plan_name': plan.name, 'status': AcademyLicense.Status.ACTIVE,
                    'starts_at': today, 'ends_at': today + timedelta(days=plan.duration_days - 1),
                    'max_users': plan.max_students, 'max_professors': plan.max_professors, 'max_admins': plan.max_admins,
                    'price': plan.price, 'amount_paid': plan.price, 'currency': plan.currency,
                    'financial_status': AcademyLicense.FinancialStatus.PAID,
                    'notes': 'Licencia demo generada automáticamente para validar el flujo completo.',
                },
            )
            owner, created = User.objects.get_or_create(
                email=data['owner_email'],
                defaults={
                    'first_name': data['owner_first'], 'last_name': data['owner_last'],
                    'role': User.Role.STUDENT, 'email_verified': True, 'is_active': True,
                },
            )
            owner.first_name = data['owner_first']
            owner.last_name = data['owner_last']
            owner.email_verified = True
            owner.is_active = True
            owner.set_password(data['owner_password'])
            owner.save()
            bind_user(owner, academy, role=AcademyMembership.Role.OWNER, status=AcademyMembership.Status.ACTIVE)

            bank_data = data.get('bank')
            if bank_data:
                bank, _ = BankAccount.objects.get_or_create(
                    bank_name=bank_data[0], account_number=bank_data[2], holder_name=bank_data[3],
                    defaults={'account_type': bank_data[1], 'is_active': True, 'order': 0},
                )
                bind_bank(bank, academy)

        call_command('seed_horizonte_academic_demo')
        self.stdout.write(self.style.SUCCESS('Demo creada: 3 planes + 3 academias + 3 dueños. Academia Horizonte incluye 2 profesores y 2 cursos completos.'))
        self.stdout.write('Dueños demo:')
        for data in ACADEMIES:
            self.stdout.write(f"  {data['slug']}: {data['owner_email']} / {data['owner_password']}")
