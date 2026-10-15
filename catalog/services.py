from django.utils import timezone
from .models import Course

def publish_course(course, actor):
    course.status = Course.Status.PUBLISHED
    course.approved_by = actor
    course.approved_at = course.approved_at or timezone.now()
    course.published_at = timezone.now()
    course.save(update_fields=['status', 'approved_by', 'approved_at', 'published_at', 'updated_at'])
    return course
