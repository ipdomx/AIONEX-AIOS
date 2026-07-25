from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ExpertOpinion:
    expert: str
    opinion: str
    priority: int


class ExpertCouncil:
    def review(self, request: str) -> list[ExpertOpinion]:
        opinions = [
            ExpertOpinion('Software Architect', 'حافظ على حدود واضحة ووحدات قابلة للاستبدال.', 1),
            ExpertOpinion('Security Engineer', 'طبّق أقل صلاحية واحتفظ بالأدلة وسجل التدقيق.', 1),
            ExpertOpinion('QA Engineer', 'أضف اختبار رجوع يمنع تكرار الخطأ.', 1),
            ExpertOpinion('DevOps Engineer', 'يجب وجود نسخة احتياطية وخطة تراجع ومراقبة.', 2),
            ExpertOpinion('Database Architect', 'افصل الذاكرة الدائمة عن سياق المحادثة.', 2),
            ExpertOpinion('Performance Engineer', 'قم بالقياس قبل التحسين.', 3),
            ExpertOpinion('Strategic Advisor', 'تحقق أن الطلب هو أفضل حل للمشكلة أصلًا.', 1),
        ]
        return sorted(opinions, key=lambda item: item.priority)
