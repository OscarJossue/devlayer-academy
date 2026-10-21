from .models import AuditLog

def log_event(actor, action, target=None, metadata=None, request=None):
    ip = None
    payload = dict(metadata or {})
    if request:
        forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
        ip = (forwarded.split(',')[0].strip() if forwarded else request.META.get('REMOTE_ADDR')) or None
        academy = getattr(request, 'academy', None)
        if academy:
            payload['_academy_id'] = str(academy.pk)
            payload['_academy_slug'] = academy.slug
    return AuditLog.objects.create(
        actor=actor if getattr(actor, 'is_authenticated', False) else None,
        action=action,
        target_model=target.__class__.__name__ if target else '',
        target_id=str(getattr(target, 'pk', '')) if target else '',
        metadata=payload,
        ip_address=ip,
    )
