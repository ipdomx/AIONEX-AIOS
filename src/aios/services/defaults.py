from __future__ import annotations
from .models import ServiceDefinition, ServiceState
from .registry import UniversalServiceRegistry

DEFAULT_SERVICES=(
 ('openai','OpenAI','ai',('code','reasoning','vision','voice')),
 ('anthropic','Claude','ai',('reasoning','code','review')),
 ('gemini','Gemini','ai',('reasoning','vision','research')),
 ('openrouter','OpenRouter','ai_gateway',('multi_model_routing',)),
 ('ollama','Ollama','local_ai',('local_models','private_execution')),
 ('github','GitHub','source_control',('repositories','issues','pull_requests')),
 ('gitlab','GitLab','source_control',('repositories','ci_cd')),
 ('docker','Docker','infrastructure',('containers','images')),
 ('kubernetes','Kubernetes','infrastructure',('orchestration','scaling')),
 ('ssh','SSH','infrastructure',('remote_execution',)),
 ('telegram','Telegram','communications',('bot','notifications')),
 ('email','Email','communications',('notifications','reports')),
 ('whatsapp_owner','WhatsApp Owner','communications',('owner_alerts',)),
)

def build_default_service_registry() -> UniversalServiceRegistry:
    registry=UniversalServiceRegistry()
    for service_id,name,category,capabilities in DEFAULT_SERVICES:
        registry.register(ServiceDefinition(service_id,name,category,tuple(capabilities),default_state=ServiceState.DISABLED))
    return registry
