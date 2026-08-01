import type { SupportedLocale } from "@/lib/locale-engine";

type Catalog = Record<string, string>;

const AR: Catalog = {
  "Sign in": "تسجيل الدخول",
  "Create a free account": "إنشاء حساب مجاني",
  "Owner / member sign in": "دخول المالك أو العضو",
  "Free user registration": "تسجيل مستخدم مجاني",
  Email: "البريد الإلكتروني",
  Password: "كلمة المرور",
  "Confirm password": "تأكيد كلمة المرور",
  Username: "اسم المستخدم",
  "Full name": "الاسم الكامل",
  "Date of birth": "تاريخ الميلاد",
  "Mobile number": "رقم الهاتف",
  "Mobile verification": "التحقق من الهاتف",
  "Send code": "إرسال الرمز",
  Verify: "تحقق",
  "Country code (required)": "رمز الدولة (مطلوب)",
  "Required privacy and security consent": "الموافقة المطلوبة على الخصوصية والأمان",
  "Create free account": "إنشاء الحساب المجاني",
  "Projects": "المشروعات",
  "New Project": "مشروع جديد",
  "Create project": "إنشاء مشروع",
  "Project name": "اسم المشروع",
  Description: "الوصف",
  "Select a workspace": "اختر مساحة عمل",
  "Create Project": "إنشاء المشروع",
  Creating: "جارٍ الإنشاء",
  "Search projects...": "البحث في المشروعات...",
  "All Status": "كل الحالات",
  Active: "نشط",
  Planning: "تخطيط",
  Paused: "متوقف مؤقتًا",
  Completed: "مكتمل",
  "Loading projects...": "جارٍ تحميل المشروعات...",
  "Request failed": "فشل الطلب",
  Tasks: "المهام",
  Members: "الأعضاء",
  Owner: "المالك",
  Progress: "التقدم",
  Settings: "الإعدادات",
  Dashboard: "لوحة التحكم",
  Notifications: "الإشعارات",
  Search: "بحث",
  Logout: "تسجيل الخروج",
  Low: "منخفض",
  Medium: "متوسط",
  High: "مرتفع",
  Critical: "حرج",
};

const FR: Catalog = {
  "Sign in": "Connexion",
  "Create a free account": "Créer un compte gratuit",
  Email: "E-mail",
  Password: "Mot de passe",
  Username: "Nom d’utilisateur",
  "Full name": "Nom complet",
  "Date of birth": "Date de naissance",
  "Mobile number": "Numéro de téléphone",
  "Mobile verification": "Vérification mobile",
  "Send code": "Envoyer le code",
  Verify: "Vérifier",
  "Projects": "Projets",
  "New Project": "Nouveau projet",
  "Create project": "Créer un projet",
  "Project name": "Nom du projet",
  Description: "Description",
  "Create Project": "Créer le projet",
  "Search projects...": "Rechercher des projets...",
  Settings: "Paramètres",
  Dashboard: "Tableau de bord",
  Notifications: "Notifications",
};

const ES: Catalog = {
  "Sign in": "Iniciar sesión",
  "Create a free account": "Crear una cuenta gratuita",
  Email: "Correo electrónico",
  Password: "Contraseña",
  Username: "Nombre de usuario",
  "Full name": "Nombre completo",
  "Date of birth": "Fecha de nacimiento",
  "Mobile number": "Número de móvil",
  "Mobile verification": "Verificación móvil",
  "Send code": "Enviar código",
  Verify: "Verificar",
  "Projects": "Proyectos",
  "New Project": "Nuevo proyecto",
  "Create project": "Crear proyecto",
  "Project name": "Nombre del proyecto",
  Description: "Descripción",
  "Create Project": "Crear proyecto",
  "Search projects...": "Buscar proyectos...",
  Settings: "Configuración",
  Dashboard: "Panel",
  Notifications: "Notificaciones",
};

const DE: Catalog = {
  "Sign in": "Anmelden",
  "Create a free account": "Kostenloses Konto erstellen",
  Email: "E-Mail",
  Password: "Passwort",
  Username: "Benutzername",
  "Full name": "Vollständiger Name",
  "Mobile number": "Mobilnummer",
  "Mobile verification": "Mobilverifizierung",
  "Send code": "Code senden",
  Verify: "Bestätigen",
  "Projects": "Projekte",
  "New Project": "Neues Projekt",
  "Create project": "Projekt erstellen",
  "Project name": "Projektname",
  Settings: "Einstellungen",
  Dashboard: "Übersicht",
};

const TR: Catalog = {
  "Sign in": "Giriş yap",
  "Create a free account": "Ücretsiz hesap oluştur",
  Email: "E-posta",
  Password: "Şifre",
  Username: "Kullanıcı adı",
  "Full name": "Ad soyad",
  "Mobile number": "Cep telefonu",
  "Mobile verification": "Mobil doğrulama",
  "Send code": "Kod gönder",
  Verify: "Doğrula",
  "Projects": "Projeler",
  "New Project": "Yeni proje",
  Settings: "Ayarlar",
  Dashboard: "Kontrol paneli",
};

const ZH: Catalog = {
  "Sign in": "登录",
  "Create a free account": "创建免费账户",
  Email: "电子邮箱",
  Password: "密码",
  Username: "用户名",
  "Full name": "全名",
  "Mobile number": "手机号码",
  "Mobile verification": "手机验证",
  "Send code": "发送验证码",
  Verify: "验证",
  "Projects": "项目",
  "New Project": "新建项目",
  Settings: "设置",
  Dashboard: "仪表板",
};

const HI: Catalog = {
  "Sign in": "साइन इन करें",
  "Create a free account": "मुफ़्त खाता बनाएँ",
  Email: "ईमेल",
  Password: "पासवर्ड",
  Username: "उपयोगकर्ता नाम",
  "Full name": "पूरा नाम",
  "Mobile number": "मोबाइल नंबर",
  "Mobile verification": "मोबाइल सत्यापन",
  "Send code": "कोड भेजें",
  Verify: "सत्यापित करें",
  "Projects": "परियोजनाएँ",
  "New Project": "नई परियोजना",
  Settings: "सेटिंग्स",
  Dashboard: "डैशबोर्ड",
};

const UR: Catalog = {
  "Sign in": "سائن اِن",
  "Create a free account": "مفت اکاؤنٹ بنائیں",
  Email: "ای میل",
  Password: "پاس ورڈ",
  Username: "صارف نام",
  "Full name": "پورا نام",
  "Mobile number": "موبائل نمبر",
  "Mobile verification": "موبائل تصدیق",
  "Send code": "کوڈ بھیجیں",
  Verify: "تصدیق کریں",
  "Projects": "منصوبے",
  "New Project": "نیا منصوبہ",
  Settings: "ترتیبات",
  Dashboard: "ڈیش بورڈ",
};

function catalogFor(locale: SupportedLocale): Catalog | null {
  if (locale.startsWith("ar-")) return AR;
  if (locale === "fr-FR") return FR;
  if (locale === "es-ES") return ES;
  if (locale === "de-DE") return DE;
  if (locale === "tr-TR") return TR;
  if (locale === "zh-CN") return ZH;
  if (locale === "hi-IN") return HI;
  if (locale === "ur-PK") return UR;
  return null;
}

export function translateInterfaceText(text: string, locale: SupportedLocale): string {
  const catalog = catalogFor(locale);
  if (!catalog) return text;
  const leading = text.match(/^\s*/)?.[0] ?? "";
  const trailing = text.match(/\s*$/)?.[0] ?? "";
  const core = text.trim();
  if (!core) return text;
  return `${leading}${catalog[core] ?? core}${trailing}`;
}
