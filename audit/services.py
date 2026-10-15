from .models import AuditLog

def log_event(actor, action, target=None, metadata=None, request=None):
    ip = None
    if request:
        forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
        ip = (forwarded.split(',')[0].strip() if forwarded else request.META.get('REMOTE_ADDR')) or None
    return AuditLog.objects.create(
        actor=actor if getattr(actor, 'is_authenticated', False) else None,
        action=action,
        target_model=target.__class__.__name__ if target else '',
        target_id=str(getattr(target, 'pk', '')) if target else '',
        metadata=metadata or {},
        ip_address=ip,
    )
