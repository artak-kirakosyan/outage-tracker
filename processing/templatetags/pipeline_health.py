from django import template

from processing.dashboard import get_pipeline_health

register = template.Library()


@register.simple_tag
def pipeline_health():
    return get_pipeline_health()
