from __future__ import annotations
from .models import MinistryDefinition
from .registry import MinistryRegistry

DEFAULT_MINISTRIES = (
    ('engineering','Engineering','Design and build maintainable systems',('architecture','backend','frontend','threejs','testing'),'chief_engineering_officer'),
    ('security','Security','Protect projects and infrastructure',('threat_analysis','secure_review','incident_response'),'chief_security_officer'),
    ('research','Research','Produce verified knowledge and evidence',('research','source_verification','experimentation'),'chief_research_officer'),
    ('human_resources','Human Resources','Manage digital workforce lifecycle',('hiring','evaluation','discipline','promotion'),'hr_director'),
    ('education','Education','Train and certify digital workers',('curriculum','assessment','certification','rehabilitation'),'academy_dean'),
    ('languages','Languages','Preserve meaning across languages and dialects',('translation','dialect','terminology','voice_normalization'),'language_director'),
    ('communications','Communications','Coordinate internal and external communication',('notifications','meetings','customer_messaging'),'communications_director'),
    ('finance','Finance','Control cost, budgets and monetization',('budgeting','pricing','cost_governance'),'chief_finance_officer'),
    ('innovation','Innovation','Evaluate valuable new capabilities',('technology_discovery','prototype_review'),'innovation_director'),
    ('strategy','Strategy','Protect long-term direction',('roadmapping','scenario_analysis','future_risk'),'chief_strategy_officer'),
    ('quality','Quality Assurance','Verify completion and release readiness',('quality_gates','integration_review','release_audit'),'quality_director'),
)

def build_default_ministry_registry() -> MinistryRegistry:
    registry = MinistryRegistry()
    for ministry_id, name, mission, capabilities, manager in DEFAULT_MINISTRIES:
        registry.register(MinistryDefinition(ministry_id, name, mission, tuple(capabilities), manager))
    return registry
