from __future__ import annotations

import json

from .approvals import ApprovalManager
from .audit import AuditJournal
from .council import ExpertCouncil
from .cognitive import CognitiveCore
from .db import Database
from .decision import DecisionEngine
from .durable_memory import DurableMemory
from .connectors import ConnectorRegistry
from .reliability import ErrorKnowledgeBase, ExperimentGate
from .execution import ExecutionSafetyLayer
from .memory import MemoryStore
from .models.router import ModelRouter
from .paths import ensure_layout
from .plugins import PluginRegistry
from .projects import ProjectRegistry
from .research import ResearchStore
from .security import SecurityAnalyzer
from .update import SelfUpdatePlanner
from .organization import EngineeringOrganization
from .orchestration import MasterOrchestrator, ContractRegistry
from .languages import ProgrammingLanguageRegistry, HumanLanguageRegistry
from .interactions import PersonaRegistry, InteractionNormalizer
from .access import SessionAccessController
from .enterprise import (
    ContractRegistry as EnterpriseContractRegistry, ServiceBus, CapabilityRegistry,
    TenantContext, PolicyEngine, DurableWorkflowEngine, Observability, PluginRuntime, APIGateway,
)
from .runtime import ClusterManager, DistributedRuntime
from .notifications import NotificationCenter, Channel, Severity
from .mission_control import MissionControl
from .government import GovernmentRuntime
from .workforce_health import OperationalHealthInstitute
from .ministries import build_default_ministry_registry
from .hr import CareerSystem
from .academy import Academy
from .services import build_default_service_registry, FutureServiceDiscovery
from .workers import WorkerRuntime
from .engineering_platform import EngineeringPlatform
from .security_platform import SecurityPlatform
from .knowledge_learning import KnowledgeLearningPlatform
from .providers import MultiModelPlatform, AIRoutingLayer, AIProviderIntegration, AIWorkItem
from .intelligence import (
    ConstitutionEngine, ProjectDigitalTwin, KnowledgeGraph, WisdomEngine,
    DefenseIntelligenceCenter, ProviderRegistry, ConcurrentTaskOrchestrator,
)


class AIOSKernel:
    VERSION = '2.3.0-beta.5'

    def __init__(self) -> None:
        self.paths = ensure_layout()
        self.db = Database(self.paths['db'])
        self.db.initialize()
        self.audit = AuditJournal(self.db)
        self.memory = MemoryStore(self.db)
        self.durable_memory = DurableMemory(self.db)
        self.errors = ErrorKnowledgeBase(self.db)
        self.experiments = ExperimentGate(self.db)
        self.connectors = ConnectorRegistry(self.db)
        self.execution = ExecutionSafetyLayer(self.db, self.paths['home'] / 'backups' / 'executions')
        self.constitution = ConstitutionEngine()
        self.knowledge = KnowledgeGraph(self.db)
        self.digital_twin = ProjectDigitalTwin(self.knowledge)
        self.wisdom = WisdomEngine()
        self.defense = DefenseIntelligenceCenter()
        self.providers = ProviderRegistry()
        self.orchestrator = ConcurrentTaskOrchestrator()
        self.engineering = EngineeringOrganization()
        self.contracts = ContractRegistry()
        self.master_orchestrator = MasterOrchestrator(self.engineering, self.contracts)
        self.programming_languages = ProgrammingLanguageRegistry()
        self.human_languages = HumanLanguageRegistry()
        self.personas = PersonaRegistry()
        self.interactions = InteractionNormalizer()
        self.sessions = SessionAccessController(self.db)
        self.enterprise_contracts = EnterpriseContractRegistry()
        self.service_bus = ServiceBus(self.enterprise_contracts)
        self.capabilities = CapabilityRegistry()
        self.tenants = TenantContext()
        self.enterprise_policy = PolicyEngine()
        self.enterprise_workflows = DurableWorkflowEngine(self.paths['home'] / 'workflows')
        self.observability = Observability(self.paths['home'] / 'logs' / 'enterprise-audit.jsonl')
        self.plugin_runtime = PluginRuntime()
        self.api_gateway = APIGateway(self.enterprise_policy, self.tenants)
        self.cluster = ClusterManager()
        self.distributed_runtime = DistributedRuntime(self.cluster, self.paths['home'] / 'runtime' / 'tasks')
        self.notifications = NotificationCenter('owner', self.paths['home'] / 'logs' / 'notifications.jsonl')
        self.notifications.configure('owner', {Channel.IN_APP, Channel.PUSH, Channel.BOT, Channel.EMAIL, Channel.WHATSAPP}, push_consent=True)
        self.mission_control = MissionControl('owner', self.cluster, self.distributed_runtime, self.notifications)
        self.government = GovernmentRuntime('owner')
        self.workforce_health = OperationalHealthInstitute()
        self.ministries = build_default_ministry_registry()
        self.careers = CareerSystem()
        self.academy = Academy()
        self.services = build_default_service_registry()
        self.future_services = FutureServiceDiscovery()
        self.worker_runtime = WorkerRuntime(self.careers, self.academy, self.workforce_health, self.paths['home'] / 'logs' / 'worker-runtime.jsonl')
        self.engineering_platform = EngineeringPlatform()
        self.security_platform = SecurityPlatform(self.paths['home'] / 'logs' / 'security-assessments.jsonl')
        self.knowledge_learning = KnowledgeLearningPlatform(self.paths['home'] / 'knowledge-learning')
        self.ai_providers = MultiModelPlatform()
        self.ai_routing = AIRoutingLayer(self.ai_providers)
        self.ai_provider_integration = AIProviderIntegration(
            self.ai_providers, self.ai_routing,
            self.paths['home'] / 'logs' / 'ai-provider-interactions.jsonl',
            knowledge=self.knowledge_learning,
        )
        self.projects = ProjectRegistry(self.db)
        self.decisions = DecisionEngine(self.db, self.memory)
        self.council = ExpertCouncil()
        self.cognitive = CognitiveCore(self.paths['home'] / 'governance' / 'decision-ledger.jsonl')
        self.security = SecurityAnalyzer(self.db, self.projects)
        self.research = ResearchStore(self.memory)
        self.plugins = PluginRegistry(self.db)
        self.approvals = ApprovalManager(self.db)
        self.updates = SelfUpdatePlanner()
        self.model = ModelRouter().build_default()

    def status(self) -> dict:
        return {
            'name': 'AIOS',
            'version': self.VERSION,
            'status': 'running',
            'home': str(self.paths['home']),
            'projects': len(self.projects.list()),
            'model_provider': self.model.name,
            'reliability': 'persistent-error-learning',
            'experiment_gate': {'minimum_successes': 2, 'maximum_attempts': 5},
            'execution_safety': 'dry-run-first',
            'constitution': 'enforced',
            'project_intelligence': 'digital-twin-and-knowledge-graph',
            'defense_intelligence': 'authorized-defensive-analysis',
            'task_orchestration': 'concurrent-isolated',
            'engineering_organization': 'specialist-engineer-manager-chief-gates',
            'delivery_orchestration': 'contracts-integration-definition-of-done',
            'language_support': 'multi-programming-and-human-language',
            'interaction_modes': 'text-and-voice-ready',
            'expert_sessions': 'owner-approval-required',
            'enterprise_foundation': 'service-bus-contracts-policy-workflows-observability',
            'tenant_isolation': 'enforced-by-context',
            'plugin_runtime': 'signed-versioned-plugins',
            'distributed_runtime': 'checkpointed-worker-execution',
            'mission_control': 'owner-command-center',
            'notifications': 'consent-routing-escalation-owner-audit',
            'government_runtime': 'councils-constitution-court-owner-office',
            'workforce_health': 'operational-behavior-performance-monitoring',
            'ministries': 'isolated-registries-and-assignments',
            'career_system': 'owner-governed-digital-workforce-lifecycle',
            'academy': 'training-assessment-certification',
            'universal_services': 'owner-controlled-scoped-service-registry',
            'worker_runtime': 'skills-health-career-evidence-review',
            'engineering_platform': 'multilanguage-planning-audit-delivery-gates',
            'security_platform': 'authorized-scanning-risk-remediation-ledger',
            'knowledge_learning_platform': 'scoped-memory-graph-verification-wisdom',
            'ai_provider_platform': 'multi-provider-routing-consensus-audit',
        }

    def validate_action(self, action_name: str, strategies, project: str | None = None) -> dict:
        """Test an action repeatedly; never label it successful without reproducible evidence."""
        known_failures = self.errors.guard(action_name, project)
        result = self.experiments.validate(action_name, strategies, project)
        return {
            'success': result.success,
            'attempts': result.attempts,
            'strategy': result.strategy,
            'evidence': result.evidence,
            'known_failures': known_failures,
            'value': result.value,
        }

    def execute_guarded(self, action_name: str, function, project: str | None = None,
                        context: dict | None = None):
        """Execute with persistent failure capture; callers can resolve learned errors later."""
        try:
            return function()
        except Exception as exc:
            fingerprint = self.errors.record(action_name, exc, project, context)
            self.audit.record('kernel', action_name, 'failed', project,
                              {'error_fingerprint': fingerprint, 'error': str(exc)})
            raise

    def inspect_project(self, root: str, project: str | None = None, *, authorization: bool = False) -> dict:
        """Build a project digital twin and run authorized defensive analysis."""
        import json
        twin = self.digital_twin.build(root, project)
        with self.db.connect() as conn:
            conn.execute(
                'INSERT INTO project_twins(project, root, fingerprint, snapshot) VALUES (?, ?, ?, ?)',
                (twin.project, twin.root, twin.fingerprint, json.dumps(twin.to_dict(), ensure_ascii=False)),
            )
        findings = self.defense.audit(twin, authorization=authorization) if authorization else ()
        if findings:
            rows = [
                (twin.project, f.severity, f.category, f.title, f.location, f.evidence,
                 json.dumps(f.remediation, ensure_ascii=False), json.dumps(f.test_plan, ensure_ascii=False), f.confidence)
                for f in findings
            ]
            with self.db.connect() as conn:
                conn.executemany(
                    'INSERT INTO intelligence_findings(project, severity, category, title, location, evidence, remediation, test_plan, confidence) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                    rows,
                )
        return {
            'project': twin.project, 'root': twin.root, 'fingerprint': twin.fingerprint,
            'files': len(twin.files), 'languages': twin.languages,
            'dependencies': twin.dependency_count, 'warnings': list(twin.warnings),
            'defense_findings': [
                {'severity': f.severity, 'category': f.category, 'title': f.title,
                 'location': f.location, 'evidence': f.evidence,
                 'remediation': list(f.remediation), 'test_plan': list(f.test_plan),
                 'confidence': f.confidence} for f in findings
            ],
        }

    def engineer_project(self, project: str, objective: str, *, departments=None, evidence: dict | None = None) -> dict:
        """Create a staffed engineering blueprint and run manager/chief review gates."""
        blueprint = self.engineering.plan(project, objective, departments=departments)
        supplied = evidence or {}
        for item in blueprint.deliverables:
            item.evidence.update(supplied.get(item.department, {}))
        review = self.engineering.chief_review(blueprint)
        payload = {
            'project': review.project,
            'approved': review.approved,
            'readiness_score': review.readiness_score,
            'blocking_findings': list(review.blocking_findings),
            'rework_plan': list(review.rework_plan),
            'rationale': review.rationale,
            'departments': [
                {
                    'department': d.department,
                    'approved': d.approved,
                    'score': d.score,
                    'findings': list(d.findings),
                    'required_actions': list(d.required_actions),
                    'manager_id': d.manager_id,
                } for d in review.department_decisions
            ],
            'organization': self.engineering.workforce.organization_chart(),
        }
        with self.db.connect() as conn:
            conn.execute(
                'INSERT INTO engineering_reviews(project, approved, readiness_score, review) VALUES (?, ?, ?, ?)',
                (project, int(review.approved), review.readiness_score, json.dumps(payload, ensure_ascii=False)),
            )
        return payload

    def constitutional_review(self, action: str, project: str | None = None, **context) -> dict:
        """Evaluate an action against AIOS constitutional policy and persist the verdict."""
        import json
        verdict = self.constitution.evaluate(action, **context)
        payload = {
            'allowed': verdict.allowed,
            'requires_human_approval': verdict.requires_human_approval,
            'violations': list(verdict.violations),
            'conditions': list(verdict.conditions),
            'rationale': verdict.rationale,
        }
        with self.db.connect() as conn:
            conn.execute(
                'INSERT INTO constitutional_reviews(action, project, allowed, requires_human_approval, verdict) VALUES (?, ?, ?, ?, ?)',
                (action, project, int(verdict.allowed), int(verdict.requires_human_approval), json.dumps(payload, ensure_ascii=False)),
            )
        return payload

    def analyze(self, text: str, project: str | None = None) -> dict:
        decision = self.decisions.evaluate(text, project)
        council = self.council.review(text)
        cognitive = self.cognitive.decide(
            title='Analyze request',
            description=text,
            project=project,
            risk_level='high' if decision.risks else 'medium',
        )
        result = {
            'recommendation': decision.recommendation,
            'alternatives': decision.alternatives,
            'risks': decision.risks,
            'confidence': decision.confidence,
            'expert_council': [
                {'expert': item.expert, 'opinion': item.opinion, 'priority': item.priority}
                for item in council
            ],
            'cognitive_governance': {
                'status': cognitive.status.value,
                'score': cognitive.score,
                'confidence': cognitive.confidence,
                'quorum_reached': cognitive.quorum_reached,
                'human_approval_required': cognitive.human_approval_required,
                'conditions': list(cognitive.conditions),
                'risks': list(cognitive.risks),
                'votes': [
                    {'cell': item.cell_id, 'vote': item.vote.value, 'confidence': item.confidence}
                    for item in cognitive.opinions
                ],
            },
        }
        self.audit.record('user', 'analyze_request', 'planned', project, {'request': text})
        return result

    def chat(self, text: str, project: str | None = None) -> str:
        analysis = self.analyze(text, project)
        model_response = self.model.generate(
            prompt=text,
            system='أنت AIOS، مساعد هندسي عربي. اقترح الأفضل واشرح المخاطر ولا تدّعِ ما لم تتحقق منه.',
        )
        return (
            f"التوصية: {analysis['recommendation']}\n"
            f"المخاطر: {', '.join(analysis['risks']) if analysis['risks'] else 'لا توجد مخاطر واضحة'}\n"
            f"الثقة: {analysis['confidence']:.0%}\n\n"
            f"رد النموذج:\n{model_response.text}"
        )
