# AIONEX AIOS — New Production Server Migration Roadmap

## 2026-10-09 21:08 UTC — PREBOOT HELPERS / RUNBOOK CHECKPOINT

**حقائق محدثة لتحاشي فشل نصوص الإنقاذ بعد إعادة الإقلاع:**

- تم فحص الجذر المضغوط داخل SystemRescue 13.02 الأصلي على OLD للقراءة فقط عبر `unsquashfs -cat ... etc/os-release`، ووجدنا **`ID=sysrescue`** (و`ID_LIKE=arch`)، وليس `ID=arch`. تم إصلاح حارسي التنفيذ في نصين مخصصين من حالة `ID=arch` الخطأ إلى `ID=sysrescue` الحقيقي قبل أي استخدام.
- سكريبت الشبكة الآمن المحفوظ على قسم BOOT القديم: `/boot/iso/AIONEX-RESCUE-NETCHECK.sh`، Bash syntax PASS، وضع 0700 وroot؛ SHA256 `1f386737061bf63d2c9feba699e892ee7b46ae676517a63b6dbbbfb66d089eed`. **يُرفض التنفيذ على Ubuntu** (RC3)، ويُسمح فقط داخل live SystemRescue. بعد الإقلاع، يفحص أولًا منفذ TCP22 على NEW؛ إذا لم تعمل شبكة Rescue الافتراضية، يكتشف منفذ WAN الفيزيائي من MAC الموجود في السكريبت **المحلي فقط** ويعيد إعداد عنوان OLD العام الثابت `209.74.65.106/24` وبوابة `209.74.65.1` **في ذاكرة Rescue فقط**، ثم يتحقق من NEW. لا ينقل ملفات أو يصور أقراصًا ولا يغيّر شبكة BMC المعزولة.
- سكريبت فحص SSH فقط `/boot/iso/AIONEX-RESCUE-SSH-CHECK.sh`، root0700، Bash syntax/Ubuntu refusal PASS، SHA256 `11092d12de528ce1972e3811deab3aafaa4da5ceeaf794ab47daea5f7fd22107`. في Rescue فقط، يحاول تركيب قسم Ubuntu القديم ext4 **للقراءة فقط بدون تحميل journal** (`mount -t ext4 -o ro,noload`) للاستفادة من هوية SSH المصرح بها والمطابقة مسبقًا على OLD بدون نسخها أو نشرها؛ ويجرب على NEW فقط إرجاع hostname المتوقع `nc-ph-4354`. **لم يُختبر في Rescue بعد ولا يضمن قبول SSH تلقائيًا**.
- سكريبت الفحص المختصر `/boot/iso/AIONEX-RESCUE-PREFLIGHT.sh`، root0700، Bash syntax/Ubuntu refusal PASS، SHA256 `1266f45934e183847623c471ef52542ca767abdc44672a1a99082f448d370c2f`. يشغّل فحص الشبكة ثم فحص SSH ثم يعرض هوية وأحجام الأقراص وحالة RAID دون تصوير. لا يستخدم كلمات سر أو ينفذ dd. **لن يُشغَّل حتى يدخل المالك إلى Rescue بشكل واضح ويُجهز console**.
- **طريقة الاستعمال المخطط لها داخل Rescue فقط** بعد موافقة منفصلة على reboot وظهور شاشة Live SystemRescue والتأكد أن md0p1 موجود وغير متصل للكتابة، كل سطر قصير ليتناسب مع iPhone:
  ```sh
  mkdir -p /mnt/oldboot
  mount -o ro,noload /dev/md0p1 /mnt/oldboot
  bash /mnt/oldboot/iso/AIONEX-RESCUE-PREFLIGHT.sh
  ```
  لو فشل أي سطر بسبب اسم جهاز مختلف أو md غير مركب أو حالة ISO mount، **قف وأرسل شاشة الخطأ**، لا تستخدم mount rw أو force ولا تغير RAID. هذا **ليس أمراً بالتنفيذ الآن في Ubuntu**.
- NEW لديه تقرير محمي `/var/lib/aionex-migration/r1-management-20261008/SYSTEMRESCUE-NO-FEE-PREBOOT-20261009T210756Z.json`، SHA256 `923bdc2f1b65510a3c1e27ab21f3fee8c4ff25b72ee538853a8a803b5937e7c7`، يؤكد 36 حاوية على الجديد وغياب GRUB next_entry وغياب reboot/copy.
- **NO-GO قائم:** لم يحدث الإقلاع التجريبي في Rescue، ولا اتصال Rescue→NEW، ولا أي استنساخ RAW. أي reboot الآن يعطل Connector AIONEX Server MCP 2 الحالي لأنه يمر عبر Ubuntu القديم؛ بعد reboot **لن يستطيع ChatGPT الحالي إدارة القديم أو الجديد بأدوات MCP القديمة**. سيحتاج المستخدم كونسول IPMI وSSH الجديد. لا تضع `grub-reboot` في grubenv أو تفعل Restart من دون موافقة مالك صريحة. عند الموافقة يتطلب الاختيار مرة واحدة فقط مع إثبات GRUB/الرجوع؛ الجاهزية البرمجية لا تساوي نجاح الإقلاع الحقيقي.

**التسليم لهذه اللحظة:** ISO الرسمي بشاهد SHA PASS؛ boot ISO مستقل SHA PASS؛ custom.cfg موجود ومتحقق نحويًا، اختيار Ubuntu الافتراضي باقٍ، helper scripts محمية ومختبرة لرفض التشغيل في Ubuntu؛ NEW سليمة (36 حاوية)؛ **لم تحدث خطوة تصوير أو استبدال أقراص أو إعادة إقلاع إضافية**.

---

## 2026-10-09 — NO-FEE LOCAL GRUB ISO STAGING: SOURCE-VERIFIED (LATEST)

**ملخص عاجل لاستكمال أي محادثة من هذه النقطة:** المالك طلب تصوير قرصي السيرفر القديم بالكامل **بدون أي رسوم Namecheap**، ويستخدم iPhone مع SSH قصير بدون Nano/EOF، ويمكنه الدخول إلى كونسول Supermicro IPMI القديم عبر VPN. مسار Virtual Media/SMB الخارجي غير متاح لأن شبكة BMC معزولة، ودعم Namecheap يعرض RescueCD مدفوعًا فقط؛ لذلك انتقلنا للمسار المجاني المعتمد رسميًا: الإقلاع من **ISO على القرص الداخلي بواسطة GRUB**. المرجع الأساسي: https://www.system-rescue.org/manual/Installing_SystemRescue_on_the_disk/ و https://www.system-rescue.org/manual/Booting_SystemRescue/ .

### ما تم فعليًا (كلّه قبل أي إعادة تشغيل أخرى)

1. **Rescue ISO الأصلي تم تنزيله والتحقق منه بالكامل** في OLD `nc-ph-4862`، Ubuntu root ext4 /dev/md0p2:
   - الإصدار **SystemRescue 13.02**، الحجم بالبايت **1,381,629,952**.
   - الملف `/root/aionex-rescue-iso-20261009/systemrescue-13.02-amd64.iso`، root0600.
   - ملف نسخة الإقلاع الفعلية `/boot/iso/systemrescue.iso`، root0600، أيضًا الحجم 1,381,629,952.
   - **SHA256 لكل من النسختين مطابق للبصمة المسترجعة من ناشر SystemRescue الرسمي**: `ad4d670b72859d887c7960142a9a9d36a3e50446694a035e254442f65d6e7572`. المصدر `https://www.system-rescue.org/releases/13.02/systemrescue-13.02-amd64.iso.sha256`.
   - فحص ISO للقراءة فقط أثبت وجود `/boot/grub/loopback.cfg`، `/sysresccd/boot/x86_64/vmlinuz`، `/sysresccd/boot/x86_64/sysresccd.img`. الـISO يتضمن قائمة `copytoram` و `checksum`.
2. **GRUB وجاهزية الإقلاع:** تم العثور على ملف `/boot/grub/custom.cfg` (موجود بالفعل عند فحص 21:00 UTC) يحوي قائمة `AIONEX SystemRescue OFFLINE RAM (no-fee; owner authorized reboot only)` ومعرّف `aionex-systemrescue-ram`، ويشير من نظام ملفات `/boot` المنفصل إلى `/iso/systemrescue.iso`، وليس إلى المسار الفعلي في نظام Linux `/boot/iso/systemrescue.iso`. هذا التمييز **صحيح** لأن الـISO على قسم /boot منفصل. إعداد القائمة يطلب `copytoram checksum`، ويفتح نواة/initramfs من ISO عبر GRUB loopback.
   - **`grub-script-check /boot/grub/custom.cfg` PASS**، و `grub-script-check /boot/grub/grub.cfg` PASS.
   - **`grub-fstest /dev/md0p1 ls /iso/` PASS** وأظهر `systemrescue.iso`. كذلك جرّبنا `grub-fstest /dev/md0p2 ls /root/aionex-rescue-iso-20261009/` بنجاح.
   - **النظام ما زال مهيأ للإقلاع الافتراضي إلى Ubuntu:** `GRUB_DEFAULT=0`, `GRUB_TIMEOUT=0`, `GRUB_TIMEOUT_STYLE=hidden`. فحص `grub-editenv /boot/grub/grubenv list` رجع فارغًا: **لا توجد next_entry محددة ولا grub-reboot مختارة**. لم يُطلب reboot ولا أجري من هذه المرحلة.
   - يوجد مسودة GRUB أخرى غير فعّالة `/root/aionex-rescue-iso-20261009/AIONEX-SYSTEMRESCUE-ONE-TIME-CANDIDATE.cfg` اختُبرت نحويًا، لكنها **ليست** القائمة الفعلية. لا تنشئ قوائم مكررة، ولا تُعدل `/boot/grub/grub.cfg` أو `/etc/default/grub` تلقائيًا.
   - `/boot` أصبح يستخدم 84% من 2GB تقريبًا وبقي **310MB** فقط. لا تُنشئ نسخة ISO ثالثة في /boot ولا تُحدّث kernel أثناء هذه المرحلة.
3. **حالة النظام بعد restart حدث سابقًا خارج هذه المرحلة:** `who -b` أكد أن OLD Ubuntu أعاد التشغيل **2026-10-09 19:56:49 UTC**. في فحوص 20:57–21:01 كانت خدمتا Docker وcontainerd على OLD **inactive/dead**، والمجلدات المشفرة Docker غير مركّبة، بينما أداة `aionex-phase22c-2-tunnel.service` لا تزال **active**. **لا تعيد تفعيل Docker على OLD** دون دراسة تعارض العمال، لأنه ليس الإنتاج الرئيسي. NEW `nc-ph-4354` كان عليه **36 حاوية تعمل، صفر unhealthy/restarting، وتوقيتا systemd للمراقبة active**. لا تفترض أن restart القديم حدث بواسطة هذه المحادثة، أو أن البيانات القديمة تُفقد بمجرد توقف Docker.
4. **جهة الاستقبال:** NEW `203.161.33.64` يحتفظ بمجلد `/var/lib/aionex-migration/old-host-offline-disk-image/` root0700، ومساحة 3.27TB متاحة بالتحقق السابق، مع وصول SSH إداري مستقل من iPhone. OLD RAID1 يعمل [UU]، قرصا SAMSUNG `sda` و `sdb` **960,197,124,096 بايت لكل واحد**، وخيار البصمة الكامل يحتاج صورتين من بيئة **متوقفة بالكامل عن الكتابة**.

### الخطوة التالية قبل أي reboot: تثبيت قناة شبكة Rescue والطريق العكسي

- **لا تُفعّل grub-reboot أو power/reset حتى موافقة مالك صريحة بعد نجاح شروط ما قبل الإقلاع.** تشغيل Rescue يوقف Ubuntu OLD ويقطع وصول ChatGPT MCP2 الحالي فورًا؛ الأدوات الموجودة في هذه المحادثة لا تستطيع الاتصال بـNEW مباشرة عبر MCP الحالي بعد توقف OLD، حتى لو كان SSH إلى NEW يعمل من iPhone. يجب أن يستعد المالك لإكمال أوامر Rescue من كونسول IPMI عبر VPN.
- الشبكة OLD Ubuntu **static**, عنوانه العام `209.74.65.106/24` على `wan0` والبوابة `209.74.65.1`. **SystemRescue الافتراضي يستخدم DHCP** وقد لا يحصل على IP لدى Namecheap. أثناء Rescue افحص `ip -br link` و`ip -br -4 a`، وتعرف على NIC العام الصحيح عبر MAC/PCI لا تتوقع اسم `wan0`. ثم عند الحاجة اضبط عنوان old static نفسه مؤقتًا في RAM/Rescue، ولا تغير شبكة IPMI. اختبر اتصال Rescue→NEW `203.161.33.64:22` بشكل آمن.
- Rescue يأتي عادة بــsshd لكن جدار الحماية قد يمنع الاتصالات الواردة؛ يُفضّل **خروج SSH من Rescue إلى NEW** مع مصادقة مالك مأذونة، بدل تعريض Rescue root password للشبكة. لا تحفظ مفاتيح خاصة في GitHub أو المحادثة، ولا تستخدم كلمات مرور في kernel args. تحقق عمليًا من مصادقة جهة NEW قبل بدء صورة كبيرة. راجع https://www.system-rescue.org/manual/Network_configuration_and_programs/ .
- ISO على RAID1 والـboot عبر GRUB؛ حاذر أن auto-assembly الافتراضي لـmd RAID قد يكتب metadata (الدليل الرسمي `nomdlvm` يمنع auto-activation لكن قد يعيق العثور على ISO الموجود على RAID). **لا تُعد أن النسخة الجنائية الصارمة غير معدلة قبل اختبار boot**؛ شرط هدفنا الحصول على صورة كاملة متسقة بعد دخول Rescue وتوقف الكتابة، وبصمة الصورة يجب أن تتحقق من الحالة المقروءة بعد Rescue. لا تستخدم filesystem repair أو mount rw.
- دخول Live Rescue يحتاج مراجعة `lsblk -b -o NAME,TYPE,SIZE,FSTYPE` و `cat /proc/mdstat` من كونسول IPMI قبل أي أوامر تصوير. عرّف disks بــ`/dev/disk/by-id` وحجم 960,197,124,096 لكل قرص. لا تفترض تطابق ترتيب sda/sdb بين Ubuntu وRescue.
- احفظ خطة الرجوع: GRUB one-shot عند الموافقة فقط، فلا تعيد كتابة default Ubuntu. عند فشل boot يظل IPMI Console متاحًا لبدء Ubuntu يدويًا. لا تفترض Rescue reboot آمنًا أو عودة تلقائية من أي hang.
- **نقل صورتَي الأقراص عبر SSH إلى NEW كملفين عاديين** بعد فحص المساحة والصلاحية، وضبط source read-only، ومن دون الكتابة إلى أي `/dev/*` على NEW، وبلا نسخ RAW إلى GitHub. إجمالي 1,920,394,248,192 بايت (بدون ضغط)، وأقل وقت نظري على 1Gbps نحو **4 ساعات و16 دقيقة** مع استبعاد كل overhead؛ التنفيذ قد يستغرق أطول بكثير، ولا يُضمن انتهاء العملية اليوم. مراقبة progress/timeout واستئناف آمن + SHA256 المصدرين والصورتين وحالة أخطاء القراءة مطلوبة.
- **موانع إغلاق OLD:** ملفات RAW كاملة الحجم ومطابقة SHA256 وحفظ المفاتيح في مكان مستقل عن السيرفرين، وتقبل المالك لفقد MCP القديم أو ربط البديل باختبار حقيقي، وتحقق TURN relay بعد تحديث external-ip في NEW، وسلامة التشغيل. ممنوع الادعاء أن النسخ الاحتياطي لـR2 اختُبر استرجاعه عمليًا حديثًا: آخر سجل DR dry_run=true.
- **الأدلة التاريخية لملفات AIOS الأصلية** (JKS ومفاتيح الإصدار، OpenSong وWorktrees وRuntime وHunyuan ومنصة الإنتاج) محفوظة بالفعل NEW وفق SHA سجل #884؛ لا تكرر نقلها. IMAGE RAW مطلوب فقط لأن المالك طلب حرفيًا كل قديم مخفي تحت mount points بجانب التطبيقات.
- **إذا منصة ChatGPT رفضت تنفيذ خطوة نقل سرية/RAW أو init ملف MCP سابقًا، فلا تعاودها بمسار أداة أخرى/worker.** الاستمرار المسموح به يشمل التدقيق غير الحساس والتحضير والتوثيق فقط إلى أن تتضح صلاحيات التنفيذ.

**القرار:** ISO الرسمي/GRUB read-only PREPARATION = PASS. Rescue boot = **NOT STARTED**, RAW disk image bytes moved = **ZERO**, full-new-server-restore = NOT CLAIMED. الخطوة القادمة موافقة منفصلة على restart بعد تصميم Rescue static network and authenticated NEW receiver. لا توقف السيرفر دون ذلك.

---

## 2026-10-09 21:02 UTC — NO-FEE LOCAL-GRUB SYSTEMRESCUE STAGED & VERIFIED (NOT BOOTED)

**Supersedes paid-RescueCD-only assumption:** Based on the owner's explicit no-extra-cost requirement, we verified the official SystemRescue free **local-disk GRUB2 ISO loopback boot** procedure. Reference https://www.system-rescue.org/manual/Installing_SystemRescue_on_the_disk/ and official download https://www.system-rescue.org/Download/ . It does NOT need external IPMI Virtual Media, SMB/CIFS or paid Namecheap RescueCD assistance. It still requires an explicitly approved one-time reboot and working console. Do **not** confuse staging with successful rescue boot or complete-disk backup.

### Completed read-only + staged preparation on OLD nc-ph-4862 at Oct 9 20:50–21:02 UTC

- Verified SystemRescue official current **13.02 amd64** (released 2026-08-01, downloaded via official Fastly HTTPS CDN). File size **1,381,629,952 bytes**, publicly published vendor SHA256 **`ad4d670b72859d887c7960142a9a9d36a3e50446694a035e254442f65d6e7572`**; local bytes matched exactly. Source retained as root0600 at **`/root/aionex-rescue-iso-20261009/systemrescue-13.02-amd64.iso`**. Exact verified identical copy placed root0600 on separate OLD 2GB RAID1 /boot partition at **`/boot/iso/systemrescue.iso`**. Remaining OLD /boot space **310 MiB**; remove redundant ISO from /boot after successful imaging and return to normal operation to avoid blocking future kernel upgrades. No secret inside upstream ISO is assumed.
- Inspected official ISO's own `/boot/grub/loopback.cfg` and `grubsrcd.cfg` **without mounting/writing the disks**, using `grub-fstest`. The official ISO includes an explicit menu option `Boot SystemRescue and copy system to RAM (copytoram)`, with `checksum` support. OLD has **62 GiB RAM**, enough for ~1.38GB RAM boot, and GRUB2 supports custom.cfg loading. The old system boots via BIOS (not UEFI), on ext4 /boot RAID1; kernel boot partition ext4 UUID was probed before making GRUB script.
- Created a **non-default** pre-staged GRUB2 menu entry **`aionex-systemrescue-ram`** in OLD **`/boot/grub/custom.cfg`** (mode0600), with source `/root/aionex-rescue-iso-20261009/AIONEX-SYSTEMRESCUE-FREE-RAM.grub.cfg`. Entry searches `/iso/systemrescue.iso`, obtains its filesystem UUID, loads the ISO's SystemRescue kernel/initramfs from loopback, passes `img_dev=/dev/disk/by-uuid/...`, `img_loop=/iso/systemrescue.iso`, and `copytoram checksum`. **`grub-script-check` PASS**, script SHA256 **`6545127bfaf4ffc596cc4576c5df6fc3c3077cd9bdd50cb03b5d78b2fc039520`**. Original GRUB config and grubenv copies preserved in root-only source directory.
- Guarded confirmation: `GRUB_DEFAULT=0` remains unchanged; `grub-editenv ... list` empty, **no `next_entry` selected**, no normal boot config overwritten, **NO REBOOT, NO DISK IMAGING** performed. The installed menu entry is only *available* for a later approved one-time boot. Existing OLD current boot time 2026-10-09 19:56:44 UTC unchanged by this preparation; the old Docker/containerd units were found **inactive** at 20:59, but the OLD ChatGPT `aionex-phase22c-2-tunnel.service` remains ACTIVE. NEW still had **36 running containers**, both independent native monitoring timers ACTIVE at 21:01 UTC. Do not automatically reactivate OLD Docker: NEW is authoritative. No customer NEW production workload altered.
- NEW image-receiver directory previously created `/var/lib/aionex-migration/old-host-offline-disk-image/`, root0700, remains ready with ~3.27TB capacity. Old physical disks each 960,197,124,096 bytes. **No RAW image has been transferred**.

### Next critical preflight BEFORE owner approves disruptive reboot

1. **Safety gate:** New native SSH access and monitoring are independently functional; back up recovery credentials outside BOTH machines; confirm owner can still access OLD IPMI KVM console through VPN during old Ubuntu down and understands the existing **ChatGPT MCP old endpoint disconnects**. This is a *real* production/management-impacting reboot, not implied authorization from asking for backups.
2. **Rescue WAN connectivity:** OLD Ubuntu WAN 209.74.65.106/24 (plus .107/24) default gateway 209.74.65.1 on `wan0` is static. SystemRescue uses auto/DHCP by default, so **do not assume** live Rescue gets external SSH automatically or preserves interface name `wan0`. Booted Rescue must establish a working source→NEW SSH connection using its **normal public production network**, which is different from isolated IPMI/BMC network; use the KVM console for safe short network commands if needed. No public Samba service and no paid provider imaging are required. Do not embed network/private SSH secrets in a public GitHub file or GRUB kernel arguments.
3. **GRUB boot reliability:** Entry syntax validation does **not** prove BIOS/RAID loopback boot on this hardware. If approved later, perform a **one-time GRUB selection only**, not permanent default update, with automatic fallback to normal Ubuntu on the next boot; observe console and verify actual `SystemRescue 13.02` login from IPMI KVM. If the boot fails, boot the original Ubuntu entry and do not overwrite partition tables.
4. **No automated RAW copy yet:** SystemRescue `copytoram` must be proven to detach ISO backing filesystem; ensure underlying OLD RAID1/boot/root and LUKS are *not* mounted for write before imaging. Software RAID activation and journal replay might write metadata if not guarded. Reconfirm the two physical disk IDs using serial/by-id, and confirm source-only read operation. A complete OFFLINE image of EACH physical drive goes only to new files inside NEW root-only destination, never to block devices/new PROD volumes. Verify bytes, SHA256, boot/RAID/LUKS structures read-only before claiming anything; do not prematurely erase OLD.
5. **Full new-host-only operational handoff:** Existing ChatGPT MCP NEW tunnel profile is still absent; platform previously refused initializing it and some old secret transfers, do not bypass. If owner accepts temporarily losing ChatGPT MCP from OLD after rescue, independent NEW direct SSH/native watchers remain good. TURN external-ip files on NEW were corrected on disk but no confirmed service restart/relay call PASS; latest R2 ciphertext 4/4 byte/SHA matches but dry-run only. These blockers must be reported honestly before declaring 100% decommission.
6. **Rollback:** If no reachable Rescue IP or if GRUB boot fails, return to OLD normal Ubuntu using IPMI KVM and original GRUB entry, without adding rescue ISO hosting costs. The one-time GRUB boot selection is NOT yet set and must not be set without the owner's explicit approval.

**Owner next decision:** Confirm an authorized one-time reboot to free SystemRescue ONLY after acknowledging old MCP downtime, KVM recovery/network requirements. Until then READY_TO_ATTEMPT_FREE_RESCUE_BOOT, not STARTED. This approved-free route displaces earlier Namecheap paid-mount support quotes; DO NOT re-open payment demands unless local GRUB boot actually fails and owner asks for alternatives.

---

## 2026-10-09 — Namecheap confirmed Virtual Media permissions; rescue boot offered as paid assistance

**أحدث رد مباشر من Namecheap بعد استيضاح صلاحيات IPMI — يُقدّم على الاستنتاجات الأقدم:**
> 1. It has permissions, but IPMI is isolated from the world, so using any 3-party links would be impossible (also applies to question 3)
> 2. We can mount rescueCD and boot the server into it as paid assistance.

**التفسير الدقيق:** دعم Namecheap يؤكد أن حساب IPMI **له صلاحية استخدام Virtual Media المطلوبة**، رغم أن صفحة Network تعرض تحذير منع تغيير إعدادات الشبكة؛ ليست صلاحية Administrator الشاملة مضمونة. شبكة BMC/IPMI **معزولة عن العالم الخارجي**، فلا يمكن الاعتماد على مشاركة SMB/ISO على خادم NEW أو رابط طرف ثالث؛ لا تفتح منفذ SMB/445 للعامة ولا تحاول تجاوز عزلة BMC. Namecheap **ترفض تصوير الأقراص بنفسها** لكنها تعرض **تركيب rescueCD والإقلاع منه كخدمة مدفوعة**؛ الإقلاع فقط لا يعني نسخ البيانات.

### نقطة القرار التالية R02/R04 — الحصول على عرض مدفوع قبل أي Reset/Boot

اطلب من موظف Namecheap، **دون منح أي تفويض بالتنفيذ**:
1. **السعر المحدد** للعملية، إن كان مبلغًا ثابتًا أو بالساعة، والضرائب/رسوم المساعدة/تكرار المحاولة/حد الجلسة، والموعد ومدة التنفيذ.
2. **اسم وإصدار RescueCD** ونوع الدخول بعد الإقلاع (كونسول IPMI، شبكة، SSH) وهل يمكنه الإقلاع إلى بيئة live بلا format أو إعادة تثبيت أو كتابة على أقراص /dev/sda و/dev/sdb أو تجميع RAID1 للكتابة؛ rescue ينبغي أن يترك أقراص المصدر غير مركبة للكتابة.
3. **أهم شرط تشغيلي:** هل تعمل للشاشة Rescue الشبكة العامة الخاصة بـOLD، وهل يمكن الوصول إلى **NEW 203.161.33.64 عبر SSH/22** من نظام الإنقاذ نفسه (ليس BMC)، وهل تسمح Namecheap بنقل نحو 1.92TB إلى خادم آخر تابع للحساب نفسه، وأي حدود سرعة/حجم/تكلفة bandwidth؟ **عزلة BMC لا تثبت عزلة Rescue Linux**؛ مساران شبكيان مختلفان. لا تفترض إمكان اتصال Rescue قبل تأكيد/اختبار مباشر.
4. هل يمكن الاحتفاظ بـRescueCD قيد الإقلاع مدة كافية لتصوير القرصين والتحقق من البصمات، وهل تستطيع الشركة توفير **نظام تشغيل إنقاذ يستطيع تشغيل SSH وdd/sha256sum** بشكل مستقل دون السماح لها برؤية كلمات مرور أو مفاتيح الحساب الخاصة؟ كيف ينتهي وصول المساعدة وحسابات الإنقاذ؟
5. هل سيستمر وصول **IPMI عبر VPN** أثناء Rescue، وهل يمكن التحكم بعملية الإقلاع التالية/إلغاء Rescue والوصول إلى OLD Ubuntu إذا أخفقت شبكة Rescue؟ هل يمكن الحصول على موافقة المالك بشكل منفصل **قبل** Boot؟

**قرار التشغيل الحالي: HOLD — لا توافق على الدفع أو إعادة تشغيل القديم حتى تتوفر الأجوبة السابقة.** اطلب فقط العرض والتفاصيل؛ لا تطلب من الدعم إعادة تشغيل الجهاز أثناء المحادثة. أداة @AIONEX Server MCP 2 ما زالت متصلة عبر OLD Ubuntu وسوف تتوقف أثناء أي Rescue boot؛ يجب تثبيت طريقة إدارة مستقلة قابلة للاستعمال (IPMI console مع اتصالات Rescue→NEW وNEW SSH) وتقبُّل فترة انقطاع أداة ChatGPT القديمة قبل إعطاء موافقة صريحة. لا تضغط أي زر Save/Mount/Reboot من الواجهة الحالية، والخانات تبقى فارغة لأن مشاركة ISO خارجية غير قابلة للوصول عبر BMC.

### إذا جاءت الموافقة والشروط PASS: خطة التنفيذ المفوضة المقبلة

- تأكد من سلامة NEW ومراقبته ووجود مساحة 3TB تقريبًا في مخزن الاستقبال المخصص root0700، وخطة العودة واحتياطي المفاتيح. لا تغيير لإنتاج NEW أو أقراصه.
- بعد موافقة المالك على السعر والوقت والعملية، **Namecheap** تركّب RescueCD وتقلع OLD بتوقيت محدد؛ لا تقوم بإعادة التثبيت ولا تفتح/تعدل LUKS أو RAID ولا تبدّل إعدادات الإقلاع الدائمة.
- تحقق من هوية القرصين في Rescue بواسطة /dev/disk/by-id وSerial وأحجام كل منهما (960,197,124,096 بايت حسب OLD Ubuntu، ويجب إعادة تأكيدها داخل Rescue)، وافحص أن RAID/الجذر القديم **غير مركبين للكتابة**.
- اختبر اتصال Rescue→NEW الآمن، ونفّذ تصوير كل **قرص فيزيائي كامل** إلى ملف **عادي** جديد على NEW عبر SSH مشفر، وليس نسخًا إلى كتلة /dev/* أو overwrite production. سجل حجم كل ملف، SHA256 للقرص المصدر والصورة المنقولة، خطأ read، حالة نقل البيانات، واحتفظ بالملفات المؤقتة .partial حتى تكتمل صلاحيتها.
- تحقق من بنية partition/RAID/LUKS للقراءة فقط في صورة RAW، واحتفظ بمفاتيح الاسترجاع خارج OLD وNEW ومع الصور المؤمّنة. عند الفشل عُد بسلام إلى Ubuntu القديم دون حذف الأصل أو الادعاء بأن النسخة مكتملة.
- لا تعتمد Shutdown/Decommission بعد تصوير RAW وحده؛ اختبر NEW MCP مستقلًا أو سلّم صراحة أن OLD ChatGPT Connector سيتوقف، وأكمل TURN relay وoffline key escrow والنقاط الأخرى الموثقة. من غير اختبار REAL new-host round-trip لا تدّع أن أداة ChatGPT نُقلت إلى NEW.

**معايير الحالة الحالية:** Namecheap Virtual Media privilege **confirmed by support**, BMC third-party ISO routing **not supported**, **paid provider RescueCD boot possible in principle**, **quote NOT YET RECEIVED**, Rescue public network/SSH access NOT VERIFIED, image transfer NOT STARTED, old-host boot unchanged, NEW production kept running. هذا النص للتوثيق والمتابعة ولا يُعتبر تفويضًا بإعادة تشغيل OLD.

---

## 2026-10-09 — IPMI network screenshot / BMC Operator privilege restriction (current blocker)

**New factual evidence from two owner screenshots after opening Configuration > Network, same OLD Supermicro BMC (not Ubuntu console):**
- Login header: **User root (Operator)**. The account name "root" in IPMI **does not grant Linux-root or IPMI Administrator capabilities**. A blocking popup explicitly states: **"You don't have privileges to apply for changes or actions."** Treat this as demonstrable restriction on at least the Network configuration actions; do **not** assert that the specific CD-ROM Image Mount action is denied until tested by authorized means. This is a **permission/RBAC blocker candidate** for ISO configuration.
- Read-only Network page shows **IPv4 static** RFC1918 172.17.x.x, subnet mask **255.255.248.0 (/21)**, gateway RFC1918 172.17.24.x, internal DNS, IPv6 disabled (as displayed), VLAN disabled, effective active network interface **Dedicated**, connected **1 Gb/s full duplex**, Shared disconnected. Do not paste BMC exact internal IP, MAC or credentials into the public GitHub roadmap or issue. The fact that the owner reaches BMC through iPhone VPN does **not** prove this BMC LAN can access the NEW public server or arbitrary SMB. Network changes are both unauthorized to current Operator and risky for future remote access.
- Official Supermicro privileges FAQ https://www.supermicro.com/en/support/faqs/faq.php?faq=11235 distinguishes Operator (restricted BMC configuration) from Administrator. Official IPMI User Guide https://www.supermicro.com/manuals/other/IPMI_Users_Guide.pdf documents Virtual Media > CD-ROM Image, Share Host, Path to Image, Save then Mount. The BMC screenshot shows Devices 1/2/3 `No disk emulation set`. No ISO currently attached or network share verified.

**Next authorized step is Namecheap BMC support permission validation (not disk imaging labor):** owner to open Namecheap Dedicated/IPMI live-support ticket and ask: (a) whether the supplied IPMI login is intentionally restricted to **Operator** and how the owner can obtain *authorized* BMC Administrator access or specifically permission to configure **Virtual Media > CD-ROM Image Save/Mount**, without sharing passwords; (b) whether Namecheap exposes an isolated management-side **SMB/CIFS ISO share** that BMC can read; (c) whether management/private network permits BMC to access an ISO share on NEW and which supported SMB protocol/version/ports/network routes are possible; (d) whether a trusted one-time rescue boot can be initiated through approved Namecheap IPMI controls without provider disk-image assistance. Clarify: support previously **refused to create the complete image**, but this is a smaller permission/network capability inquiry, not a renewed imaging request.
- **Current UI instruction:** click **Close** on privilege warning; do not press Save, alter IP/gateway/DNS, mount a guess ISO, enable public TCP445/SMB1, click Power/Reset, or log into Ubuntu tty1. Return to **Virtual Media > CD-ROM Image** only to observe status; owner can send Namecheap's reply or screenshot of approved BMC permission settings. No private SMB service, ISO, reboot, imaging or production change should be executed until explicit authorization, trusted network path, verified ISO, rescue→NEW access and safe rollback plan are in place.
- **Contingency if Namecheap declines privilege:** Do not attempt to elevate IPMI via Linux ipmitool/firmware rewrite or other backdoor to bypass vendor role. Continue NEW authoritative AIOS production using previously verified copies, and pursue supported off-host backup/offline rescue window using BMC Administrator legitimately issued to owner. Mark **R02 and R04 HOLD: IPMI privilege and BMC-to-share reachability unknown**. No claim of complete bitwise copy today.

**State:** evidence documented; permission and network confirmation **PENDING**; BMC settings unchanged; OLD operating system and ChatGPT old-only MCP remain active.

---

## 2026-10-09 — Namecheap OLD physical RAID imaging via Supermicro IPMI / CD-ROM Image

**المهمة والعهدة:** هذه الخريطة هي مرجع التنفيذ عند انقطاع المحادثة. المالك يريد الاحتفاظ بكل بايت من السيرفر القديم اليوم إن أمكن، ثم إدارة AIONEX AIOS حصريًا من الجديد، قبل تاريخ توقف القديم المعلن 2026-10-22. السيرفران Dedicated عند Namecheap. فريق الدعم قال صراحة إنه **لن ينشئ صورة قرص أو يساعد في التصوير**؛ إجراءات النسخ على عاتق المالك. هذا لا يساوي حصولنا على موافقة بإعادة التشغيل أو ادعاء أن Rescue ISO متاح تلقائيًا.

### 0. حقائق مؤكدة وحالة المرحلة — مصدر زمني 2026-10-09 19:45 UTC

| العنصر | الدليل/النتيجة | الحالة |
| --- | --- | --- |
| OLD | nc-ph-4862، IP 209.74.65.106، جهاز Supermicro SYS-5039MC-H12TRF، لوحة X11SCE-F، BMC firmware 1.74 | PASS/READ ONLY |
| NEW | nc-ph-4354، IP 203.161.33.64، خادم الإنتاج الفعلي منذ NS10 2026-10-05، 36 حاوية قيد التشغيل عند آخر تحقق | PASS/READ ONLY |
| قرصا OLD | /dev/sda و/dev/sdb، كلاهما SAMSUNG MZ7L3960، حجم كل واحد **960,197,124,096 بايت** | PASS/READ ONLY |
| RAID1 | md0 من sda2+sdb2، حالة [UU]، قسم /boot وقسم root ext4 /dev/md0p2؛ توجد ملفات حاوية LUKS2 داخل الجذر | PASS/READ ONLY |
| المساحة المتاحة NEW | **3,274,956,136,448 بايت** تقريبًا، وصورتا القرصين بدون ضغط تحتاجان معًا **1,920,394,248,192 بايت**، بالإضافة إلى مساحات العمل وملفات ISO | PASS/READ ONLY |
| مسار صور الأقراص NEW | /var/lib/aionex-migration/old-host-offline-disk-image/ — موجود root:root بصلاحية 0700 | PASS |
| عيب الجرد المرئي OLD | df للجذر = 765,030,105,088 بايت مستخدمة؛ du المرئي = 351,990,788,096؛ فارق **413,039,316,992 بايت**. فحص ext4 للقراءة فقط وجد Docker/containerd قديمين تحت نقاط تركيب مشفرة تحجب الملفات؛ نسخ TAR للملفات الظاهرة ليس نسخة كاملة | CONFIRMED / DO NOT OVERCLAIM |
| صور الأقراص كاملة | **لم يبدأ تصوير أي قرص بعد**؛ لا توجد صورة RAW مكتملة أو بصمتها | NOT STARTED |
| IPMI | دخول المالك عبر VPN إلى ipmi.web-hosting.com، واجهة Supermicro BMC بحساب operator وتحت Virtual Media > CD-ROM Image | PASS/SCREENSHOT |
| الأجهزة الافتراضية | Device 1/2/3 كلها “No disk emulation set” في الصورة الأخيرة | NOT MOUNTED |
| تشغيل rescue | لا ISO مستضاف أو مركّب، ولا تم اختبار وصول BMC إلى مشاركة شبكة، ولا حدث reboot | NOT STARTED |
| ChatGPT MCP | أداة @AIONEX Server MCP 2 الحالية تتصل عبر OLD؛ في NEW يوجد الكود ومفتاح التشغيل، لكن لا توجد profile نفق مفعلة. محاولات التهيئة السابقة رُفضت من فحوص المنصة | BLOCKED / DO NOT CIRCUMVENT |
| بيانات AIOS الفعلية | NEW المصدر الأحدث لقواعد البيانات والملفات والإنتاج؛ أرشيفات Open Song وWorktrees وRuntime والمفاتيح الأصلية محفوظة NEW ببصمة SHA متطابقة وفق سجلات issue #884 | PASS FOR COLD CUSTODY |
| TURN على NEW | ملفا الإعداد على القرص تغير فيهما external-ip من OLD إلى NEW مع حفظ نسخ تراجع، لكن حاوية TURN لم تُعَد تشغيلها وما زال اختبار relay الوظيفي غير مكتمل | CONFIG FILE FIXED / RUNTIME NOT ACCEPTED |
| DR الخارجي | أحدث Cloudflare R2 backup مشفر من 2026-10-09 17:05 UTC، أربعة ciphertext objects متطابقة SHA256 وحجمًا؛ automated restore dry_run وليس استعادة كاملة حديثة | OFFSITE INTEGRITY PASS / RESTORE GATE OPEN |
| GitHub | الوصول من NEW إلى GitHub origin HEAD نجح؛ PR #887 للوثائق لم يُدمج لأن اختبار Browser E2E/NS14A فشل، رغم نجاح اختبارات أخرى | PR CI HOLD |

**تعريف النجاح:** كفاية التخزين الجديد لا تساوي نجاح النسخ. لا تقل “نقلنا كل شيء” إلا بعد صورتين كاملتين متسقتين OFFLINE من الأقراص الصحيحة، والتحقق من طول وبصمة SHA256 لكل صورة، وتسجيل خريطة RAID/الإقلاع والقدرة على فتحها للقراءة؛ ثم تحقق استقلال الإدارة والميزات قبل الإطفاء النهائي. GitHub لا يحتوي البيانات السرية أو أقراص النظام أو مخازن Docker/RAID المخفية.

### 1. تفسير شاشة IPMI الأخيرة — تعليمات المالك الحالية، بلا إجراء تدميري

الصورة عند Supermicro BMC القائمة **Virtual Media > CD-ROM Image** (وليست شاشة تسجيل دخول Ubuntu). تعرض:
- Device 1 وDevice 2 وDevice 3: No disk emulation set.
- Share Host: **عنوان مضيف مشاركة SMB/CIFS يحتوي ISO** الذي يستطيع BMC الوصول إليه. ليس عنوان السيرفر القديم أو الجديد تلقائيًا.
- Path to Image: **المشاركة + اسم ملف ISO**؛ مثال توضيحي فقط في حال كانت المشاركة اسمها rescue والملف ثبتت تسميته بالفعل: \rescue\systemrescue-amd64.iso. الصيغة الفعلية المحددة من Supermicro هي backslash + share + backslash + filename.
- User وPassword: حساب محدود الصلاحية للقراءة من المشاركة فقط إذا تطلبته، يُحفظ خارج المحادثة والمستودع.
- Save: حفظ حقول الإعداد بعد تجهيز مشاركتها. Mount: محاولة ربط ISO. Unmount: إزالة ISO. زر Refresh Status آمن للقراءة.

**القرار الآن: اترك الخانات فارغة، لا تضغط Save/Mount أو Power/Reboot ولا تدخل كلمة مرور Ubuntu.** لا يوجد ISO ولا Samba share مؤهلان حاليًا. التوثيق الرسمي: https://www.supermicro.com/manuals/other/IPMI_Users_Guide.pdf (قسم CD-ROM Image)، https://www.supermicro.com/en/support/faqs/faq.php?faq=32233، وصيغة المسار https://www.supermicro.com/en/support/faqs/faq.php?faq=17567.

### 2. R01 — اختيار Rescue ISO موثوق والتحقق من تنزيله على مضيف مناسب

- استخدم ISO إقلاع حي للأعمال الاسترجاعية مثل **SystemRescue amd64**، وليس ملف ISO للتثبيت الذي قد يمسح الأقراص. المصدر الرسمي https://www.system-rescue.org/Download/ وتعليماته https://www.system-rescue.org/Quick_start_guide/.
- قم بتنزيل ISO والتوقيع الرقمي/ملف SHA256 من نفس الإصدار الرسمي؛ احفظه تحت مسار استقبال منفصل خاص بالجديد، وتأكد أن SHA256 يطابق القيمة المنشورة للإصدار المحدد قبل عرضه للـBMC. لا تثبت رقم إصدار غير مدقق داخل الأوامر المستقبلية. لا تستخدم ISO غير موثوق أو روابط مخترعة.
- لا تبدأ إعادة تشغيل القديم من أجل ISO قبل إتمام R02 وR03. تنزيل ISO على NEW لا يعني تلقائيًا أن BMC يعرف الوصول إلى NEW.

**معيار القبول:** ISO موجود بالمصدر الرسمي وله SHA256 مثبت على مضيف المشاركة. الحالة الحالية NOT STARTED.

### 3. R02 — مشاركة ISO الخاصة فقط ومسار الوصول من BMC

- الواجهة الظاهرة تستخدم **network share**؛ عادةً SMB/CIFS، ولها خانة Share Host وخانة Path to Image. لا يمكن إدخال مسار لينكس محلي مثل /root/... في Path to Image.
- تحقق أولًا، بشكل غير تدميري، من عنوان شبكة BMC ومسار اتصاله: الوصول إلى واجهة IPMI من iPhone عبر VPN **لا يثبت** قدرة الـBMC نفسه على الوصول لعنوان 203.161.33.64 أو إلى منفذ SMB في شبكة NEW. لا تفترض أن IPMI وواجهة Linux على نفس الشبكة أو أن منفذ 445 مفتوح.
- يفضل مشاركة ملف ISO وحيد **read-only** من مضيف يمكن للـBMC الوصول إليه عبر **شبكة إدارة خاصة/VPN موثوقة**؛ حساب Samba مؤقت بلا صلاحيات تعديل، جدار ناري يقتصر على عنوان الـBMC المعروف، وعدم عرض SMB/445 للعالم. بعض BMC القديمة تتطلب SMB1؛ لا تفعل SMB1 العام على خادم NEW الإنتاجي. إذا كان SMB1 مطلوبًا، استخدم وسيطًا معزولًا محدود الوصول أو أوقف هذه الطريقة وراجع بديلًا مدعومًا.
- اختبار صحة مشاركة ISO يجب أن يتم من نفس مسار الشبكة الخاص بالـBMC، قدر الإمكان، قبل إدخال بيانات الاعتماد. لا تخزن Samba/ISO credentials في GitHub أو النصوص أو سجلات عامة.
- إذا كان BMC لا يستطيع الوصول إلى المضيف، توقف عند **NETWORK/BMC SHARE BLOCKED**. البدائل: مشاركة خاصة متاحة عبر إدارة Namecheap، أو كونسول Java موثوق على كمبيوتر حقيقي متصل بالـVPN إذا كانت البيئة/الرخصة تسمح؛ **لا تفترض** أن زر HTML5 غير الفعال يبرر إعدادات عامة غير آمنة.

**معيار القبول:** مشاركة مقروءة عبر شبكة إدارة آمنة ومجرب وصول BMC؛ لا خدمات SMB عامة. الحالة NOT STARTED.

### 4. R03 — تجهيز مسار نقل RAW ومفتاح الإدارة والنسخ الاحتياطية قبل أي توقف

- NEW لا يتغير عليه الإنتاج. مجلد الحفظ الموجود /var/lib/aionex-migration/old-host-offline-disk-image/ هو مخزن **ملفات عادية** فقط بصلاحيات جذرية 0700؛ أي ملف صورة يكون 0600 ويُعامل كأصل يحمل **أسرارًا شخصية، ملفات اعتماد وخوادم، وجذر OLD غير المشفر**. لا تنشر الصورة أو SHA لها إذا تضمنت معلومات حساسة.
- تحقق أن NEW يستطيع استقبال **1,920,394,248,192 بايت** على الأقل بالإضافة إلى مساحة أمان. افحص حصص نظام الملفات، الإنذارات، واتصال SSH المباشر والجدار الناري. لا تستخدم dd of=/dev/mdX أو أي block device على الجديد إطلاقًا.
- هيئ طريقة مصادقة SSH آمنة مؤقتة لبيئة الإنقاذ (Rescue قد لا يحمل مفاتيح SSH أو مسار IP القديم). **لا تعتمد على اتصال OLD Ubuntu الجاري بعد reboot**؛ وقد تصبح أداة ChatGPT القديمة غير قابلة للاستعمال أثناء Rescue.
- احفظ نسخ R2 المشفرة ومفتاح استعادتها خارج OLD قبل توقيفه؛ لا تدعي أن اختبار dry_run استعادة كاملة. سجل لحظة التوقف، أسماء الأجهزة الأصلية، حالة RAID1، أرقام الأقراص في سجلات خاصة لا تكشف الأسرار.
- لا تغير إعداد SSH/Cloudflare أو اسم مضيف NEW، ولا تلمس قواعد البيانات أو LUKS الجديدة. لا توقف OLD ما لم يصرح المالك بتوقيت إنقاذ يؤدي إلى انقطاع أداة MCP الحالية.

**معيار القبول:** اتصال Rescue→NEW مؤمَّن ومجرب بخطوة بسيطة من دون تصوير، مساحة تحقق، وخطة عودة إذا فشل الإقلاع. الحالة NOT STARTED.

### 5. R04 — تركيب ISO من شاشة المستخدم الحالية

**فقط بعد اكتمال R01/R02/R03:** في صفحة IPMI Virtual Media > CD-ROM Image:
1. **Share Host** = عنوان مشاركة SMB/CIFS القابل للوصول من BMC الذي قيس فعليًا، لا IP تخميني.
2. **Path to Image** = \اسم-المشاركة\اسم-ISO-المؤكد.iso حسب ما تم إنشاؤه؛ Backslash وليس مسار /opt أو رابط HTTPS.
3. **User / Password** = حساب قراءة مؤقت إذا كان مطلوبًا؛ لا إرسال للقيم في محادثة ChatGPT أو صور الشاشة.
4. اضغط **Save** ثم **Mount**؛ اضغط **Refresh Status** وتحقق أن أحد Device 1/2/3 يعرض اسم ISO، بدل No disk emulation set. ظهور Mounted لا يعني أن النظام أقلع Rescue.
5. **لا تضغط Power Control أو Reset** حتى تكون جميع شروط R03 محققة ويعطي المالك موافقة صريحة على نافذة توقف. إذا فشل Mount: راجع مشاركة SMB الخاصة والشبكة والصيغة بدون المساس بالتشغيل.

**معيار القبول:** صورة ISO موصولة مرئيًا على BMC، دون reboot. الحالة NOT STARTED.

### 6. R05 — إقلاع Rescue مرة واحدة بعد موافقة المالك

- تأكد أن NEW يقدم الخدمة بالفعل، وأن القديم لا يستقبل كتابة مستخدمين حية، وأن جميع المهام الخلفية المهمة قد أُغلقت بسلام أو حالتها محفوظة. أوضح للمالك أن كل أدوات ChatGPT الحالية التي تمر عبر OLD ستنقطع بمجرد الخروج من Ubuntu.
- احصل على **موافقة مستقلة صريحة** لإعادة تشغيل OLD في Rescue. استخدم Boot Menu/one-time virtual media إن توفر؛ لا تغيّر boot order بشكل دائم ولا تستخدم Install/Reinstall/Wipe.
- تحقق على شاشة الكونسول أن الظاهر هو SystemRescue live environment وليس Ubuntu القديم أو شاشة مثبت. عند فشل الإقلاع، أزل Virtual Media وأعد تشغيل النظام القديم بالترتيب الأصلي مع توثيق النتيجة؛ لا تستمر في التصوير.
- داخل Rescue افحص lsblk و /dev/disk/by-id وmd RAID metadata وحجم كل قرص ورقم سلسلة الأجهزة؛ **قد تتغير أسماء sda/sdb** بين Ubuntu وRescue. لا تفترض الأسماء بدون Serial/WWN/size. يجب أن يكون OLD RAID/filesystems **غير مركبة للكتابة**، ولا يتم تشغيل fsck أو mdadm assemble --write أو فتح/تعديل LUKS أو عمل newfs/parted/cryptsetup format.

**معيار القبول:** بيئة الإنقاذ تعمل، مصدرا القرصين معروفان بهوية ثابتة، والقراءة بدون كتابة، واتصال NEW يعمل. الحالة NOT STARTED.

### 7. R06 — تصوير كل قرص RAW من Rescue إلى NEW كملفات فقط

**شرط قاطع:** هذه المرحلة بعد نجاح الإقلاع Rescue فقط؛ أوامر dd لا تُنفذ داخل Ubuntu القديم أثناء التشغيل ولا على أقراص الإنتاج في الجديد. لا يُنفذ أي أمر فعلي حتى يثبت المسؤول أسماء /dev/disk/by-id الصحيحة واتصال SSH. نظرًا لأن المستخدم يعمل من iPhone ويستخدم SSH لا يتحمل Nano/EOF، تُرسل الأوامر التنفيذية الصغيرة واحدة واحدة بعد ظهور Rescue.

- الترتيب: صورة **القرص الفيزيائي الأول كاملًا**، ثم صورة **الثاني كاملًا** لأن المطلوب حفظ metadata كلا القرصين وليس مجرد نسخة ملفات md0.
- التدفق المقصود: **اقرأ القرص المصدر read-only من Rescue → انقل البيانات عبر SSH موثق/مشفر → اكتب regular file جديد إلى NEW داخل مجلد الحفظ**، مثل old-physical-disk-A.raw.partial ثم B.raw.partial. أسماء الديسكات المصدر تكون by-id بناءً على Serial الفعلي، ولا يُكتب أبدًا على القرص نفسه أو NEW block devices.
- لا تستخدم إعادة توجيه تعيد كتابة ملفات موجودة أو تعيد البدء فوق نسخة صالحة. اختبار المصدر والحجم، عدم وجود ملف الوجهة، مساحة استقبال كافية، صلاحيات وجهة 0600، وحفظ مخرجات الخروج للأنبوب pipefail كلها شروط قبل النقل.
- إذا استعمل ضغطًا أثناء النقل فيجب أن تكون الأداة والخوارزمية والنسخة ووسيلة فك الضغط موثقة، وأن يُعاد احتساب SHA للبيانات **بعد فك الضغط**؛ RAW بدون ضغط أسهل في التحقق ومناسب من حيث السعة على NEW. لا تعد بمدة إنهاء ثابتة؛ تتأثر بسرعة القرص والشبكة ووصول IPMI.
- يمكن استمرار النقل داخل جلسة Rescue مستقلة عن متصفح iPhone باستخدام أداة جلسات طويلة معروفة، لكن لا تفترض استئناف RAW جزئي آمن بدون تحقق حدود القطاعات والبصمات. أي ملف .partial ليس نسخة ناجحة.
- احتفظ ببيانات SHA256 للمصدرين المُجمدين/القراءة فقط والأحجام الفعلية، ولا تعتمد على مجرد نجاح rsync أو الظهور في المجلد.

**معيار القبول:** الملفان منتجان بالكامل بالحجم الصحيح، دون أي عمليات write إلى الأقراص الأصلية أو أقراص NEW الإنتاجية. الحالة NOT STARTED.

### 8. R07 — إثبات حفظ جميع البايتات والاستعادة المختبرية

- لكل قرص، تأكد أن حجم ملف RAW النهائي على NEW **960,197,124,096 بايت** (إذا أعادت معاينة Rescue تأكيد هذه الأحجام نفسها)، وأن **SHA256 لكل ملف** يساوي SHA256 للقرص المصدر من البيئة الهادئة. إذا كان هناك خطأ قراءة I/O أو تعذر تطابق بصمة: FAIL، لا تعتمد الملف كنسخة كاملة.
- استخدم أدوات قراءة فقط لفحص جدول الأقسام والإقلاع وRAID superblocks وLUKS2 metadata داخل الملفات. إثبات أن البيانات المخفية تحت mount points محفوظة يتم من خلال فحص صورة OLD المصدر بطريقة للقراءة فقط، لا بإعادة استخراجها فوق NEW.
- وثّق صورة كل قرص باسم by-id/serial وتاريخ النسخ، الأداة، SHA256، حجم الملف، الوقت والأخطاء، واختبار فتح الصورة للقراءة. خزّن manifest root-only 0600 على NEW مع نسخة مستقلة آمنة خارج الخادمين إن كانت ممكنة. بعد نجاح الفحص فقط حوّل أسماء .partial إلى .raw نهائية.
- نسخة RAW تحمل أسرار OLD، فلا توضع على GitHub أو R2 عام ولا تُسلَّم لجهة خارجية من دون سياسة تشفير مفاتيح وحيازة. يفضّل تشفير النسخ المخزنة بمفتاح استرجاع يحتفظ به المالك **خارج OLD وNEW** ومراجعة استعادة تجريبية؛ إذا أخفق التشفير أو خرج المفتاح من السيطرة لا تحذف الأصل قبل إثبات النسخة الآمنة.
- **لا تجرّب استعادة أي صورة raw فوق الأقراص الحية على NEW**. تحقق استعادة النظام الكاملة، إن طُلب، يتم على بيئة مختبر معزولة تمامًا.

**معيار القبول:** المصدران RAW + SHA256 + manifest + فحص الهياكل PASS (ومعالجة أمن حفظ الصور). الحالة NOT STARTED.

### 9. R08 — إغلاق اعتماد OLD وخدمات MCP وTURN قبل الإلغاء

- **New-only management:** أداة ChatGPT MCP الحالية ما زالت تتصل بـOLD. توافر كود NEW وحده لا ينقل اتصالها. الربط الجديد يجب أن يتم بالمسار المرخص وبتكوين موثق ثم **اختبار tool round-trip يعيد hostname=nc-ph-4354**. عمليات إعداد الملف الشخصي التي رفضتها المنصة سابقًا لا تُعاد عبر أدوات بديلة. إن انتهى وقت OLD قبل الربط، يبقى SSH المباشر والمراقبة المحلية على NEW هما القناة المؤكدة؛ يسجل فقد ChatGPT مؤقتًا بصراحة.
- **TURN:** external-ip الأصلي 209.74.65.106 كان ظاهرًا على NEW، وصُحح الملفان على القرص إلى 203.161.33.64 مع نسخ تراجع، لكن لا يوجد reboot/restart ناجح للحاوية ولا اختبار فعلي لترحيل المكالمات. يلزم إجراء صيانة مشروع واختبار relay audio/video من خارج شبكة الخوادم قبل PASS؛ فحص healthy وحده غير كاف.
- **مفاتيح وخدمات مؤجلة:** المفتاح الثنائي Android JKS وأسرار الإصدار الأصلية وSecondary RunPod محفوظة في صندوق NEW الخاص ببصمة مطابقة، لكن لم تُفعّل. بعض رموز Meta القديمة لم تُنقل بسبب رفض منصة أمان، وتحتاج إعادة تهيئة رسمية إذا رغب المالك؛ لا تتجاوز الرفض بإعادة تغليف أو أدوات أخرى. TrendBost منتج مستقل موقوف عن النقل الفعال بقرار المالك.
- **ضمانات DR:** أرصدة R2 الحديثة مشفرة ومتحقق منها byte-for-byte؛ **اختبار الاستعادة الأخير dry_run** ونسخة مفتاح استرجاع خارج الخوادم غير متحققة. تجنب ادعاء أن الفشل الكلي للخادم الجديد مضمون الاستعادة.
- **إيقاف OLD:** بعد تحقق R07، وتثبيت قناة الإدارة المطلوبة، واختبار TURN أو قبول المالك بصراحة لبقاء العيب الوظيفي، يوافق المالك على إيقاف OLD دون حذفه أو إلغاء فاتورته تلقائيًا. لا تنفذ shut down مبكرًا لمجرد وجود صورة ISO. اختبر NEW لمدة مراقبة مناسبة مع traffic/user routes مستقلة، ثم المالك يلغي التجديد من Namecheap بنفسه قبل موعد 22 أكتوبر. تأكد من أن صور RAW خارج OLD وستظل متاحة عند فقد الحساب القديم.

**معيار القبول النهائي:** صورتا القرصين سليمـتان ومؤمنتان، NEW يعمل، اختبارات الاتصال والإدارة مكتوبة، توقف القديم متعمّد وموثق، وتقرير تاريخي واضح بما تم وتأجل وتقبل المالك من مخاطر. المرحلة HOLD حتى استكمال الشروط.

### 10. بوابات NO-GO والعودة وقيود الأوامر

- لا عمل عالي الخطورة قبل **فحص اسم الجهاز والقرص في Rescue والوجهة كملف عادي على NEW**؛ لا أي Restore للقرص من الصورة على NEW الإنتاجي.
- انقطاع mount أو قدرة BMC للوصول إلى Samba، أو عدم وجود شبكة/SSH من Rescue إلى NEW، أو نقص المساحة، أو خطأ في bytes/hash/RAID، أو عدم وضوح حفظ المفاتيح → **STOP** مع حفظ الأدلة، ثم العودة الآمنة إلى OLD Ubuntu دون مسح.
- لا نقل لأسرار أو صورة قرص حاوية للملفات الحساسة via GitHub، ولا تفعيل SMB1/445 مكشوف للإنترنت، ولا نشر مفاتيح ISO/SMB/SSH/RunPod/Meta في شاشات المحادثة أو logs.
- لا تعتمد أن تصوير القرصين أو نسخ 1.92TB سينتهي اليوم؛ تحكم سرعة شبكة NEW/OLD والوصول عبر Rescue قد يستغرق ساعات طويلة. إذا تعذر إنجاز كامل نسختي RAW، لا تدّعي إغلاق كامل، ويمكن تأجيل الفصل الفيزيائي حتى اتضاح الخطة؛ لا تفقد البيانات من أجل موعد طموح.
- أي طلبات جديدة من iPhone: أوامر SSH قصيرة منفصلة **سطرًا بسطر**، بدون Nano أو EOF، ومع تأكيد Done/تم لكل خطوة. استمرارية العمل عبر issue #884 والمراحل R01–R08 بالأدلة الحديثة.
- لا تعيد نسخ الأرشيفات الثلاثة الأساسية أو بيانات الإنتاج الأكبر عند محاولة حل مشكلة ISO؛ فهي محفوظة مسبقًا، والغرض من تصوير الأقراص هو استكمال **كل البيانات المخفية والتاريخية** التي لا يغطيها ترحيل المشروع.

**الخطوة الوحيدة للمالك عند الصورة الحالية:** إبقاء صفحة CD-ROM Image مفتوحة والخانات فارغة؛ لا Save/Mount/Power. على المسؤول إعداد ISO موثوق ومشاركة SMB خصوصية قابلة للوصول من BMC والتحقق منها. ثم تعود المحادثة بأسماء Share Host/Path to Image المؤكدة فقط دون بيانات اعتماد، ليُكتب للمالك ما يدخل في كل خانة.

---

## Verified new-only handover update — 9 Oct 2026, after 17:16 UTC

**Use this latest section before historical material below.** Owner will not renew OLD nc-ph-4862 after reported 22 Oct 2026. NEW nc-ph-4354 is the authoritative production server. Detailed immutable source references, original SHA records and accepted tests are in GitHub issue [#884](https://github.com/ipdomx/AIONEX-AIOS/issues/884). The separate privately developed AIONEX AI system is not part of AIOS host migration.

### Completed — live service and irreplaceable source custody

- NEW production has 36 running containers, zero unhealthy/restarting as observed Oct9 17:16 UTC. The Oct5 NS10 transfer made NEW authoritative for PostgreSQL, uploads and execution vaults; OLD user-write admission was closed. NEW-native NS12 hourly observation produced 25 retained samples by Oct9 17:00; the latest sample reported no anomalies and all ten HTTP checks at expected codes. Both independent NEW monitoring timers are active. The owner mobile root SSH public key had independently authenticated to NEW without using OLD.
- **Supersession of early 9 Oct Android risk:** Owner independently transferred the ORIGINAL Android release JKS binary, its signing environment and deferred secondary RunPod environment by SFTP to the private NEW inbox folder /root/AIONEX-MANUAL-INBOX/critical/. All three files exactly matched OLD size and SHA256 and were chmod 0600/root:root. Receipt USER-SFTP-APP-FILES-VERIFIED-20261009T152520Z.json on NEW SHA256 c4b50a023efa4dca16e7861937b478997629ebec1db3a4f249950eb2d528ae37. Prior statements that JKS was still missing described an EARLIER point in time, not current custody. Three separate Phase34 Ed25519 signing public/private key artifacts have additionally been preserved in NEW private cold custody with exact old/new SHA256 matches; no key value is committed to Git.
- Three unique original OLD cold archives are stored intact on NEW, root-only and not extracted into production: Open Song (3,055,034,823 bytes, SHA256 943b054ed6a7fd8af8d4446fdf4e7b0002b32d5dcdc59b073c38d4dd2ca83084), historical Worktrees (4,801,312,993 bytes, SHA256 d5d01bf5f1d59ccba62b1a59878d52765ee0012d6e361f1a0b3569a8106b9738), and historical runtime (17,548,751,033 bytes, SHA256 a80e03d5b33f4dae30de260a155010555a4dbc7e7a08c4889c3419f8f3dacefd). Open Song and Worktrees passed TAR structure checks; full Runtime member listing timed out, but old/new SHA256 parity passed. NEW private staging: /root/AIONEX-MANUAL-INBOX/models and /root/AIONEX-MANUAL-INBOX/history. See issue #884 receipts. Do not recopy/reinstall blindly.
- Previously accepted distinct root-only cold archives also preserve original Hunyuan3D/RunPod gateway source and Git history (isolated Git reconstruction PASS), AFS/tools/disabled source-closure coordinator, TrendBost helper, old releases, old FR04C1 source and consistent 24-table historical SQLite, and RunPod job identifiers. These have immutable exact SHA evidence in issue #884.

### New acceptance evidence and further preserved files

- The two legacy SMTP installer scripts and old ADB firewall service unit were preserved inertly in NEW /var/lib/aionex-migration/retirement-evidence-20261008/legacy-operator-scripts/RETIREMENT-LEGACY-OPERATOR-SCRIPTS-20261009T1700Z.tar.gz; 1,976 bytes, SHA256 f2c2273067e04f9516e205597b08369739fd9d489468f1bb366b9b232c5a6532. They were not executed or installed in NEW.
- Historical Android APK/AAB, iOS source and portal release artifacts from OLD root config releases directory were preserved in NEW legacy-app-release-artifacts/RETIREMENT-LEGACY-APP-RELEASES-20261009T1710Z.tar.gz; 237,173,412 bytes, 1,919 TAR members, SHA256 7f911ea8c00fcb206ef373ed7246eaa3f303542896a7180705b2b48c63972151. Sensitive .env/PEM/key/P12 files and one token-like JSON were excluded. This is a cold source archive, not production deployment.
- Five nonsensitive historical RunPod metadata files are in NEW root-only legacy-runpod-metadata/RETIREMENT-RUNPOD-NONSECRET-METADATA-20261009T1720Z.tar.gz, SHA256 e96eddc08ffc2d4ebb2af9f7f7d052733dd8a7da4b243a7da4ddf383b0787329. Two separate OLD RunPod JSON files may contain token/env fields and were deliberately not copied raw; the owner already secured the separate original secondary RunPod environment through SFTP.
- Docker: all **nine named Docker volume identities** on OLD also exist on NEW. This is structural identity parity, not all-vault byte identity. OLD has 105 anonymous volumes; zero are attached to running OLD containers, 104 are unattached to ANY OLD container and one belongs only to stopped OLD TURN. NEW has its own active TURN. Do not overwrite live NEW customer volumes with stale OLD raw PostgreSQL or Redis data or copy orphaned test cache volumes by default.
- Ollama gemma3:4b is available on both servers. All **seven actual model blob and manifest files** (3,338,804,078 bytes) matched per-file SHA256 exactly OLD versus NEW. Two per-host Ollama Ed25519 identity files legitimately differ; never overwrite NEW private identity from OLD.
- NEW scheduled production backup 7279bdc5-89ca-4822-a11c-8badd68b742c completed on Oct9 17:05:54Z with offsite status completed. A fresh independent NEW-to-Cloudflare-R2 read-only streaming GET verified entire ciphertext size and SHA256 for **all four** latest offsite objects (database 21,607,228 bytes, manifest 1,973, 3D 54,937,868, platform assets 54,937,868): 4/4 PASS. Automated restore validation recorded completed, validated and offsite_validated at 17:06:13Z, but **dry_run=true**; this does NOT prove real restoration of that latest encrypted backup. Separate NEW-only real isolated restoration of the Oct5 NS10 PostgreSQL dump passed with 176 public tables. NEW keyring already matches OLD and has the required R2 encryption key identity. External off-NEW keyring custody remains unverified.

### Explicit residual dependency and safe old-host retirement decision

1. **ChatGPT custom MCP is the operational blocker.** NEW already has tracked operator source at /opt/AIOS/ops/mcp2/server.py (28 handlers) and local root-only runtime key, but current read-only profile listing confirms **no NEW tunnel-client profiles configured**; NEW phase22c systemd tunnel services are inactive. Connected ChatGPT @AIONEX Server MCP 2 still executes against OLD. A NEW MCP profile/credential/init attempt was previously platform-safety-refused. Do not bypass it via another tool/host/account/worker. Keep OLD ChatGPT plugin/host active until a legitimate NEW endpoint is independently configured and actual NEW-host tool round-trip accepted; if old expires first, root SSH and NEW-native monitoring keep production manageable but the old ChatGPT bridge will stop. New ChatGPT entitlement/write permission may limit MCP actions even after connecting; no paid upgrade has been approved.
2. **OLD Meta marketing access tokens remain excluded.** Three OLD provider token files are not verified on NEW. A direct secure transfer was platform-safety-blocked before execution, and NEW escrow staging directory did not appear. Do not retry/repackage the denied effect. Owner retains provider credentials privately and may reprovision through authorized provider/account interfaces later. No raw token is included in Git.
3. **Full OLD byte-clone was NOT performed.** Old anonymous Docker volumes, partial old .deployment-backups, emulator and other project's files, rebuildable dependencies and miscellaneous old state were not attested as a lossless 689GiB image. Preserve project boundaries. The accepted listed unique AIOS runtime archives, signing keys, running service/data cutover and fresh remote backup do not mean every unrelated OLD filesystem byte moved.
4. **Independent disaster restoration remains distinct.** Full NEW-host-loss recovery would require verified backup keyring custody outside BOTH servers and a controlled genuine decrypt/restore of latest offsite files. Automatic PostgreSQL post-reboot startup and expanded NS14A authenticated/browser fault tests also remain not fully accepted. Do not infer these gates from healthy Docker/HTTP points.
5. **TrendBost is a separate hosted product deferred by Owner.** Legacy bridge files are preserved but NEW bridge is disabled and OLD one active; this optional tool is not required for current AIOS user-serving production and can be legitimately provisioned later.

**Decision:** NEW AIOS is production-authoritative and can be administered through proven direct SSH, with authentic user-created archives, original signing identity, Hunyuan/RunPod/Git material and offsite ciphertext preserved. **Do not erase or unregister the ONLY LIVE OLD ChatGPT MCP** merely because code/key files are present on NEW. Retire the bridge only after NEW-specific connector verification or an explicit owner decision to give up ChatGPT MCP control.

## Old-host retirement dependency closure — 2026-10-09 (verified field evidence)

### 9 Oct owner custody correction and safe historical archives (14:31–14:55 UTC)

**OWNER CONFIRMS: the only independently retained private notes contain provider API keys; no Android/mobile application signing keystore or app-specific signing credentials are held outside OLD.** A specifically bounded root-only old-host file-status and SHA audit found the actual original Android `android-release.jks` binary **4,392 bytes**, `android-release.env` **143 bytes**, and deferred secondary RunPod environment file **420 bytes**, all mode `0600`. The three original files are **not** present at their expected NEW locations; a scoped, non-exhaustive NEW vault/migration/archival filename search found no identical application JKS. NEW root-only *metadata only*, without any secret value or original file: `/var/lib/aionex-migration/r1-management-20261008/UNRECOVERED-ORIGINAL-APP-SIGNING-20261009T1437Z.json`, SHA-256 `995f46b112149c9e3f7a24d47f15be99a44b7275c6a1ebd72fd2d8d9be95dd04`. **Critical: the original Android JKS binary must be retained through a legitimately authorized secure process before expiry. Never synthesize a new signer and claim it retains original release signing identity.** The previous exact sensitive transfer effect was explicitly platform-refused; continuing user authorization is not permission to bypass/repackage through other tools or paths.

**NEW primary production configuration cross-host SHA audit:** all **11** specifically enumerated active config/credential files are present on both hosts, with **10 byte-identical** old/new SHA-256 values. Only `.env.production` differs in whole-file hash; both have **108** variables with identical names and **107 identical values**. Its sole changed key name is `AIOS_REALTIME_PUBLIC_IP`, an expected host-specific IP setting after the cutover. No credential content or value was printed. NEW root-only receipt: `/var/lib/aionex-migration/r1-management-20261008/PRIMARY-CONFIG-PARITY-20261009T1455Z.json` SHA-256 `5084dfa2e8e60c142c79cdb56f98cdb38c66e0d0542fa126806bd5d600cc419e`. This is **allowlist parity only**, not proof that unenumerated OLD secret files or the Android keystore moved.

**Additional separately scoped old-only non-production materials now present, hash-verified, root-owned and inert on NEW:**

- Historic user-portal deliveries and 3D release assets from OLD `releases/`: NEW `/var/lib/aionex-migration/retirement-evidence-20261008/legacy-releases/RETIREMENT-OLD-RELEASES-20261009T1436Z.tar.gz`, SHA-256 `1c6e74fca3d5aa49959c4572b9fc72337e40ee654c966c8125df886644b60b6b`, **16,118,729 bytes**, 417 archive members. Historical release only; does not supersede the LIVE NEW deployment.
- Historical FR04C1 source-safety snapshot from OLD: NEW `/var/lib/aionex-migration/retirement-evidence-20261008/legacy-fr04c1-snapshot/RETIREMENT-FR04C1-SOURCE-20261009T1444Z.tar.gz`, SHA-256 `44717bde54f558b76ff194cd24f4c79c9f2244870e73abfb69364188935c9c0c`, **4,085,498 bytes**, **2,396 archive members**. It intentionally excludes historical database content, mypy/pycache and three source-text files triggering token/PEM-looking scan heuristics. A sample `.env.example` with no unexpected high-entropy active assignments remains; this is NOT a production secret source or a full audit of every source byte.
- Historical FR04C1 SQLite retained separately with transactional backup and actual NEW read-only `PRAGMA integrity_check = ok`, **24 tables**, never imported into production: NEW `/var/lib/aionex-migration/retirement-evidence-20261008/legacy-fr04c1-snapshot/RETIREMENT-FR04C1-SQLITE-20261009T1445Z.tar.gz`, SHA-256 `bfe60de3fb9ea307e8fd076e3abf62b6f5290c8915ae342d959a3e14fbea495f`, 3,152 bytes. The SQLite in OLD `/opt/AIOS/data/aios.db` had exact same SHA as this already-preserved historical database.
- Six historical phase33/34c RunPod job/template/endpoint IDs from OLD `/opt/AIOS/data/phase*.txt`, without publicly disclosing values: NEW root-only `/var/lib/aionex-migration/retirement-evidence-20261008/legacy-job-identifiers/RETIREMENT-LEGACY-JOB-IDS-20261009T1447Z.tar.gz`, SHA-256 `f63f620fb06c0e79d9e8dc5c687b8046cf2f51221a16ea4bc8ef746c69505811`, 6 files.
- Root-only consolidated verification of first three archives: NEW `/var/lib/aionex-migration/retirement-evidence-20261008/ADDITIONAL-OLD-SOURCE-VERIFIED-20261009T144441Z.json` SHA-256 `37d78b9feaf28440348c700e06863cf0f6df7b645437b32b577d60fb62ce30b1`, verified **3/3** archives and **20,207,379** combined archive bytes.

**Other old-host handling:** TrendBost live bridge activation is now explicitly deferred at Owner discretion; its original launcher, systemd service and a Python helper were preserved on NEW, but the remote ChatGPT tunnel still depends on OLD until independently re-authorized. Do not use TrendBost bridge as a condition for *NEW AIOS production services*; disclose loss of optional legacy ChatGPT bridge on old expiry. Independent SSH and NEW-local observability are already working.

**Retirement remains `HOLD_LOSSLESS_OLD_CLONE` despite NEW production being live and independent of OLD for customer service.** The old machine's occupied root volume (~689 GiB at 14:32 UTC) was not cloned in full. Do not overwrite newer NEW live DB/assets/volumes with old backups. Historical 28 GiB scanner/runtime evidence, 17 GiB old worktrees, ~3.8 GiB Open Song weights and unreviewed possible secrets still lack exhaustive lossless preservation. Prior exact platform refusals for Open Song preflight, broad OLD inventory and Android/secondary-provider transfers remain binding; don't repeat effects via renamed archive/host/account/worker. If platform does not authorize the original-file signing key transfer, record the risk transparently before owner cancels/not-renews, seek an independently approved secure retention mechanism, and do not represent fabricated files as originals.

**Decision: HOLD_OLD_HOST_RETIREMENT.** The public AIOS application has already cut over to NEW (Oct 5); no second application migration or overwriting of live NEW customer data is authorized. Owner's reported OLD suspension is **2026-10-22** (exact provider hour/time zone unverified); Oct 20 is an internal safety buffer, not a guarantee. The separate independently developed AIONEX AI project is not part of this server-retirement change; never deploy it implicitly.

### Verified now / preserved

1. **Container coverage:** OLD has 29 running AIOS Compose container names, and every one is also among NEW's 36 running names. The additional seven on NEW include Cloudflare, realtime, Telegram and operations observation. NEW point sample: zero unhealthy/restarting containers, zero observed restart counts. Name coverage is NOT an independent API/auth/functionality or restore acceptance.
2. **Authority and durable data:** NS-10 Oct 5 recorded successful NEW-authoritative PostgreSQL, asset and project-execution vault cutover, with OLD admission authority closed, new authoritative, verified post-cutover encrypted backup and recorded validation; do not blindly replace NEW live DB or vault data with OLD snapshots. Rounded `fr06-vaults` size is approximately 233 GiB on each host; size alone is not byte parity.
3. **Local monitoring transferred:** NEW `aionex-runtime-watch.timer` runs every ~60 seconds, enabled/active with successful real timer executions (`Result=success`, `ExecMainStatus=0`); both service and timer files match OLD SHA-256. Independent immutable receipt on NEW: `/var/lib/aionex-migration/r1-management-20261008/RUNTIME-WATCH-HANDOVER-20261009T0707Z.json`, SHA-256 `9e9838b1f28a9754e831eb4112bb8d9b2b7880334afd8e76ff1cea6f06f30c4e`. Separate NEW hourly `aionex-ns12-observer.timer` already exists and must not be duplicated.
4. **Independent emergency administration:** Actual successful NEW `root` public-key SSH acceptance from the owner's mobile SSH ID was verified without OLD relay. NEW evidence `/var/lib/aionex-migration/r1-management-20261008/OWNER-INDEPENDENT-SSH-20261009T073959Z.json` SHA-256 `5765472f9170c480a7bfca167fc82d1372e2206d790a4a9d3b100e1224cb427c`. This proves independent SSH control, NOT new ChatGPT MCP control.
5. **Dormant coordinator preserved:** OLD-only, already-disabled AIONEX source-closure coordinator script and its service/timer preserved as NEW root-only archive `/var/lib/aionex-migration/retirement-evidence-20261008/legacy-source-closure/RETIREMENT-SOURCE-CLOSURE-20261009T0730Z.tar.gz`, SHA-256 `e52f2b38d09ad0ef099d9afff562a1f7fffe606dd8e97868340d26c594d0a828`. Three member hashes matched source. Archive not activated; do not install/restart implicitly.
6. **Non-runtime tools preserved:** AFS source, `TOOLS`, `aionex-ops` scripts and synthetic security fixtures (44 archive members) preserved on NEW `/var/lib/aionex-migration/retirement-evidence-20261008/legacy-tools/RETIREMENT-LEGACY-TOOLS-20261009T0741Z.tar.gz`, SHA-256 `d9ef36e8b20b36bf5d5639e9d808f220f3c4383068925d7384806786d98cfef8`, mode 0600, not installed. Rebuildable virtualenv/cache omitted.
7. **Earlier inert source records:** NEW preserves historical Git transfer (1,045 refs/103 worktree heads), 50 uncommitted file versions plus 34 patches from 17 dirty worktrees, SQLite/operations historical snapshots, 27 acceptance receipts and 17 unpublished test files in prior hashed archives. Historical data is not automatically current source.
8. **AIOS primary configuration:** 11 specifically enumerated active production credential/config paths were verified present on NEW. *Presence does not prove content parity, functional validity or independent off-host custody.*

### Further verified 9 Oct preservation (after initial closure report)

- **Actual isolated database restore PASS:** NEW on 9 Oct restored the on-disk, SHA-matched NS10 snapshot `/var/lib/aionex-migration/NS10-FINAL-DB-20261005.dump` (SHA-256 `d973e1c4724876ac58ae8742a9a1c8778f2d94d677a6e01af059e01f8c87d6b8`) into a temporary PostgreSQL 16 container using a tmpfs data directory, **`--network none`**, no externally published ports, bounded memory/CPU, `pg_restore --exit-on-error`. Real restoration completed successfully with **176 public tables**, and the test container was removed afterwards; all **36** original NEW production containers stayed running and minute watcher showed `Result=success`. Separate NEW receipt `/var/lib/aionex-migration/r1-management-20261008/NS10-REAL-ISOLATED-RESTORE-20261009T082445Z.json` SHA-256 `09bcdcba80d525afa1a247cdaf9f928504d1068faf2a56285aa97ba95a0993a1`. This proves **only** restoring the **Oct 5 NS10 database dump**; it does **NOT** prove isolated restore of **Oct 8 or newer offsite encrypted backups**, key custody or full live-application recovery.
- **Hunyuan3D and RunPod source escrow on NEW:** Root-only **inert** archive `/var/lib/aionex-migration/retirement-evidence-20261008/legacy-3d-runpod/RETIREMENT-HUNYUAN3D-RUNPOD-SOURCE-20261009T0820Z.tar.gz`, **155,095,711 bytes, 697 archive entries, SHA-256 `4b9637bad44b2348588ae7b93437e5a3a9a302c965c3fbea35beb8a53e254cd4`**. Transfer verification receipt alongside archive `TRANSFER-VERIFIED-20261009T0820Z.json` SHA-256 `50623e0d1af52f8d57cef09812716edec97b06ceb2663df89616ee092ef1c699`. Includes custom Hunyuan3D-2.1 source/assets and RunPod gateway/serverless/Docker/bootstrap code; omits nested upstream `.git` and rebuildable caches. A limited textual heuristic checked 137 source files without matching selected high-risk token/private-key patterns; **this is NOT comprehensive secret/license/production acceptance**. No containers or endpoints were changed or activated. This is **NOT** the separate `/opt/aionex-models/open-song` model weight tree, which remains unpreserved.
- **TrendBost hosting is separate from OLD bridge:** NEW reached hosted HTTPS origin and received HTTP 200 with valid TLS verification, and a separate TrendBost hosting-operator read-only `server_status` returned ONLINE. This shows the remote hosting service is reachable **without routing through the old machine**, not that a new ChatGPT management bridge has been activated. The OLD TrendBost tunnel poller remains the only verified active ChatGPT management route; NEW service remains disabled pending legitimate independent credentials + tool round-trip.
- **Uninterrupted anomaly history:** NEW locally collected NS12 observation `NS12-WATCH-20261009T080028086427Z.json` at ~08:00 UTC recorded `vip_de` process exit 28 / unavailable (one anomaly, `REVIEW_REQUIRED`). A later independent NEW HTTPS GET to the actual locale URL `https://ai.vip-e.net/de/` returned HTTP 200 (and /es/ returned 200) in under one second. Do not erase original timeout or claim zero outages; retain as transient observation pending trend monitoring.
- **Owner-held recovery keys:** The owner reports privately retained key material outside ChatGPT and authorizes rebuilding re-creatable components after OLD expires rather than paying renewal. This statement is **not** proof that the original Android JKS binary, corresponding signing certificate, every recovery token, or historical proprietary model artifact is actually available. Never log owner secrets in this public roadmap, and never assert cryptographic equivalence of replacement keys.

### Oct 9 remote R2 ciphertext proof and extra historical Git preservation

- **LATEST R2 full remote ciphertext content integrity PASS (4/4):** Production DB `backup_records` identifies backup `c07dedcc-1fc3-4cd6-beef-002d1cc48956` as the most recent completed backup as of Oct 9 ~11:55 UTC, generated **2026-10-08 17:01:45 UTC**. Authenticated *read-only* Cloudflare R2 S3 `GET` on NEW streamed and SHA-256 hashed all four entire encrypted remote objects, comparing independent `offsite_evidence.encryption.ciphertext_size_bytes` and `ciphertext_sha256`. All sizes and SHA-256 hashes matched: database **21,481,844 bytes**, manifest **1,973**, 3D snapshot **54,937,868**, platform asset snapshot **54,937,868**. All use AES-256-GCM; the difference of 268 bytes against recorded inner source sizes is the documented external encryption-envelope overhead, not a mismatch. Root-only NEW receipt: `/var/lib/aionex-migration/r1-management-20261008/R2-OFFSITE-OBJECTS-VERIFIED-20261009T115253Z.json` SHA-256 `20b660c09917730d11c317c50a5f76af6c9e6bbac756fb8d2b25de9edb0dd115`. **Verified:** remote existence, remote complete encrypted bytes and hash integrity; production unchanged, secret values neither printed nor copied.
- **Encryption key identity availability on NEW:** The root-owned NEW backup encryption keyring is mode `0400`, its sole active `key_id` was independently matched (by ID only, with no secret output) to the `key_id` in **all four** Oct 8 offsite encryption manifests. This verifies local key identity existence, **not** successful full decryption, recent offsite database+asset restoration, or independent external key escrow/custody. The existing Oct 8 DR record `df8476a5-a779-43b4-9862-6f68ef288ed0` says `restore_validation completed/validated/offsite_validated=true` and `dry_run=true`; do not invent a separately observed fresh real restore from those flags. The *separate* Oct 5 NS10 database dump was actually restored in a disposable network-isolated PostgreSQL container on NEW on Oct 9 (176 public tables), as recorded above.
- **Hunyuan3D full nested Git history additionally preserved:** Previously archived on-disk Hunyuan/RunPod source excluded the 154 MiB nested `.git` directory. Now NEW has separate inert root-only archive `/var/lib/aionex-migration/retirement-evidence-20261008/legacy-3d-runpod/RETIREMENT-HUNYUAN3D-GIT-HISTORY-20261009T1200Z.tar.gz`, size **154,278,445 bytes**, 46 entries, SHA-256 `a923dc6fb6f9d0ec83c8001f24ad66efe01d664e4f4143cfaf6befc2d48c5779` equal OLD. A real disposable NEW reconstitution using *both* the source archive and `.git` history completed: Git HEAD `82920d643c0dc2f7bfd7255f45f62d386edfe60c` verified, Git connectivity `fsck` PASS, **three** original dirty worktree entries retained; temporary files removed. NEW verification receipt `HUNYUAN3D-GIT-HISTORY-VERIFIED-20261009T115833Z.json` in the same protected directory SHA-256 `c0ee38cfc7fd77e85211e196b4978e7e4388bd3feae5bb3cb5692fea616e6009`. This is unrelated to missing Open Song model weights.
- **TrendBost bridge code ready but NOT connected:** Exact OLD/NEW launcher SHA and unit SHA parity preserved. NEW `sh -n` and `systemd-analyze verify` both PASS; NEW service `inactive/disabled`, OLD bridge remains `active`. Original credential-source inspection was platform-safety-refused: no repackage/reroute, no blind second poller, and no false claim that new authenticated tunnel is live. The separately hosted PHP operator remains reachable via HTTPS from NEW. A legitimately provisioned *new* independent credential and confirmed tool round-trip are still missing. After OLD expiry the existing ChatGPT-bridged control may stop even while the hosted TrendBost operator remains online.
- **Persistent handoff:** GitHub <https://github.com/ipdomx/AIONEX-AIOS/issues/884> is the owner-approved **no-renewal** retirement checklist and includes these exact new evidence references. User plans to let OLD contract expire by **2026-10-22**, but no automatic early stop/wipe/provider cancellation is authorized. Remaining untouched hard gates: original Android signing binary escrow/official recovery, deferred secondary RunPod secret, original Open Song weights or licensed reconstruction, fresh isolated latest-offsite decrypt+restore and external key custody, independent TrendBost/ChatGPT bridges, real reboot startup and relevant authenticated/NS14A releases. Preserve no-disclosure, no duplicate legacy tunnel, and no replacement of NEW live production state.

### Remaining blockers (do not mark complete)

- **TrendBost bridge:** TrendBost hosting endpoint answered independently via its own operator connector, but OLD `trendbost-mcp-bridge-tunnel.service` remains active and NEW is installed but **disabled/inactive**. Executable and systemd unit hashes match exactly on OLD/NEW (binary SHA `ae852b18ced97d8bd3320e7429d8c3709b5b60dddee19baef8895c1cb5d9f3d2`, unit SHA `f4860698d9d2756d80d0e6d5f223dd2c33e720fcd49be7d08faca50ed495f992`). The old bridge requires a control-plane credential, whose source was not approved for inspection; no successful NEW authentication/connection or OLD disconnect has occurred. This is a **separate TrendBost service** and requires an authorized new credential or approved migration, verified new-tunnel polling/tool round-trip, then measured old disconnection. Do not run both blindly, assume hosted MCP means old bridge is unneeded, or silently deactivate.
- **New ChatGPT MCP:** NEW tracked `ops/mcp2/server.py` has all 28 tool handlers and a local root-only runtime key for independent tunnel `tunnel_6ac82b37d9508191a504553fafe701a7`. NEW `tunnel-client` returned **zero registered profiles**, so it is NOT active. Tunnel profile initiation was blocked by platform safety check at approximately 2026-10-09 06:24 UTC. Support case **16766780** reports Full MCP write/modify not available on user's Pro tier. Neither Workspace reuse nor an API key alone fixes write entitlement. Do not circumvent previously refused configuration execution via alternate tool, host, script or worker; allow an independent SSH-based operational process rather than claiming ChatGPT management independence.
- **Deferred secret custody:** Original Android release signing keystore/config and secondary RunPod provider config were not verified copied onto NEW; requested transfer was platform-refused. **Never synthesize a replacement signing identity** and claim upgrades will remain compatible: preserve the original keystore securely or use supported signing-key recovery/rotation procedure. Secondary provider credential can only be reissued through its authorized provider/account, not reverse-engineered. Keep providers deferred and never print secret values.
- **Open Song local model materials:** OLD `/opt/aionex-models/open-song` occupies ~3.8 GiB, 20,970 files and six symlinks; that path is absent on NEW. These data were not bind-mounted on the three inspected OLD production services, but may be important for reproducibility/future offline operation. A sensitive-source preflight was blocked; transfer/recreation is NOT complete. Only preserve after permitted provenance/sensitivity review, or independently reconstruct from approved upstream models pinned to license/checksums without misrepresenting equivalence.
- **Historical evidence/caches:** OLD has approximately 28 GiB under `docs/project/runtime` and 17 GiB of worktrees, largely historical test/security/build artifacts; selected critical records are preserved, full archival inventory and retention classification are not certified. Do not equate lossless OLD retirement with transferring every rebuildable cache.
- **Recovery / release:** The Oct 5 NS10 database snapshot passed an actual NEW-only network-isolated PostgreSQL restore (176 tables) on Oct 9; **Oct 8 Cloudflare R2 encrypted ciphertext bytes and SHA-256 are now independently verified 4/4 and all four needed key identifiers exist in the NEW keyring**. The Oct 8 automated DR validation is recorded `completed/dry_run=true`, but **a separately witnessed real isolated restoration of that latest offsite encrypted backup, external encryption-key custody and whole-application recovery remain NOT proven**. Full authenticated browser/TCP/reconnect tests, VIP security publication, local PR #877 publication and some source reconciliation remain HOLD or refused. The 72-hour NS-12 elapsed threshold does not substitute for complete observation coverage. Check latest NS-12 receipts and source CI rather than backfilling successes.
- **Cross-project completeness:** Other OLD jobs, integrations or address-based dependencies must be attested before full hardware retirement. No blanket disable/wipe/cancellation merely because AIOS itself is live on NEW.

### Safe completion sequence and future assistant handoff

1. Read this map **together with** live protected-main SHA, NS-10 cutover evidence, newest NEW host monitor and migration receipts. Always prefer recent live evidence over old screenshots and Oct 7 source-version references.
2. Complete only genuinely *permitted*, scoped, reversible actions; hash and read-back verify copies before relying on them. If an exact effect was platform refused, log `BLOCKED` and require legitimate authorization resolution rather than repackaging the same action. Do not fabricate files/keys/models.
3. For TrendBost, explicitly retain service ownership, gain an authorized independent new-host tunnel credential and test new-host roundtrip before stopping the OLD bridge. Never merge this with AIOS production credentials.
4. Resolve Android signing key custody and secondary provider deferral independently. Preserve unique records; treat non-reconstructable keys differently from rebuildable runtime caches.
5. Prove isolated recovery with independent key custody, ownership of admin access, current data backup, authenticated journeys, and latest release gates. Obtain owner sign-off and separately confirm external addresses, provider callbacks and old-only jobs no longer depend on OLD.
6. **Only then** mark `OLD_RETIREMENT_READY_FOR_OWNER_APPROVAL`. Actual OLD wipe, provider cancellation or shutdown requires explicit, separate owner authorization. Until then `HOLD_OLD_HOST_RETIREMENT` remains authoritative.

## Current authoritative state — 2026-10-07

Status: CUTOVER_COMPLETE_NEW_SERVER_AUTHORITATIVE_NS12_OBSERVATION_ACTIVE_BACKEND4C6_VIP1FED_NS15_RECONCILIATION

- The new Debian 12 production server is the authoritative public runtime.
- The old production server is retained intact as the rollback anchor and must not be retired before the original NS-12 observation gate and explicit Owner approval.
- Protected GitHub `main` is currently `1fedff22300c1abb699439f32409bbb10ccb7ce7`. Backend/new-server runtime remains the accepted application release `4c6ae50091fb568b491eacbffa0fec53a444092d`; the separate shared-hosting VIP user portal is published from `1fedff22300c1abb699439f32409bbb10ccb7ce7` after PR #878.
- PR #875 closed the earlier VIP dependency alerts, and PR #878 subsequently moved VIP Sharp to 0.35.5 for GHSA-wq5f-xc86-pv6w. Exact-head and post-merge CI are PASS, the published VIP package has `npm audit --omit=dev = 0`, and Dependabot reports **0 open alerts** after reindex. Four source-manifest-only Trivy Docker-module alerts remain documented as evidence-backed not-used dismissals; this is not an absolute-security claim.
- The currently deployed application release is `4c6ae50091fb568b491eacbffa0fec53a444092d`. Exact-source backend/image-derivative/frontend images were rolled out on the new production server after protected-main CI PASS; Sharp runtime is 0.35.5 with libvips 8.18.7, rollback tags are preserved, public/user/API/Owner smoke is PASS, production unhealthy/restarting counts are zero, and maintenance admission is reopened at generation 50.
- The active `ai.vip-e.net` user portal remains on its established shared-hosting route and is now published from protected main `1fedff22300c1abb699439f32409bbb10ccb7ce7`: pre-deploy backup created, rsync dry-run reviewed, package-owned SHA-256 parity `362/362`, all six locale roots plus login/projects/API checks HTTP 200, and no DNS/Cloudflare Tunnel/backend/Owner-policy mutation.
- Canonical FR-09 1,000-user acceptance is PASS on the new server; the staged authenticated-read growth envelope through 5,000 sessions is recorded as a synthetic capacity envelope, not a claim of 5,000 simultaneous heavy AI/GPU generations.
- NS-12 observation started at `2026-10-05T16:43:26Z`; the earliest 72-hour completion is `2026-10-08T16:43:26Z`. Application updates do not reset this original window.
- FR-07F conversation anti-stall/reconnect protection is merged from PR #872 and remains deployed/verified in release `4c6ae50091fb568b491eacbffa0fec53a444092d`. Runtime source hash matches the protected source; heartbeat=10s, stale-running fail-closed threshold=180s, provider hard timeout=150s, and unauthenticated policy routing is live/fail-closed. Public smoke is PASS. The broader NS-14A fault matrix (mid-stream transport drops, auth refresh/expiry, repeated reconnect and terminal-event loss) remains required before final release closure.
- NS-15 tracked reconciliation is being refreshed to the split current truth: protected main/VIP portal `1fedff22300c1abb699439f32409bbb10ccb7ce7`, backend/new-server runtime `4c6ae50091fb568b491eacbffa0fec53a444092d`, and the original NS-12 observation window unchanged. The retained append-only runtime journal remains the execution ledger; generated STATE/PROJECT-REPORT are updated only through project_hub.

### Current continuation transport

The approved continuation path is **MCP2 management entry -> approved SSH administration channel with strict host-key verification -> new production server -> clean exact-SHA checkout/worktree**. The tracked map intentionally does not contain the new host IP, SSH private-key path/material, credentials, or raw environment secrets.

## Historical migration baseline — 2026-10-04

The block below is the original pre-migration baseline and must not be treated as the current runtime state after cutover.

Status at that time: NEW_SERVER_PROVISIONED_PROVIDER_HARDWARE_VERIFIED_AWAITING_INDEPENDENT_HOST_AUDIT

### Live authority and continuity rule

Before any continuation, operator or assistant action must reconcile all of the following rather than trusting a screenshot or stale paragraph:

1. protected GitHub main and the exact candidate/head commit SHA;
2. the latest retained migration/runtime checkpoint and evidence;
3. the actual new-host source SHA, running image identities, database/schema state and health;
4. current protected CI for the exact head being considered;
5. rollback state on the old server.

If these disagree, the discrepancy is recorded as documentation drift and live/GitHub evidence wins until canonical reconciliation. A stale map must never trigger a blind pull, reset, deletion, deployment, replay or provider action.

The new dedicated server has been purchased and access details have been received. The provider control panel shows Debian 12 x86_64. Provider technical support has confirmed all of the following:

- All 4 x 1.92 TB NVMe drives are detected correctly.
- The drives are configured as RAID 10.
- The RAID array is healthy, fully synchronized, and has no degraded disks.
- The server has the full 128 GB RAM.
- Both AMD EPYC 7313 CPUs are detected correctly.

No application data has been uploaded to the new server. Migration has not started. The existing production server remains the source of truth and must remain online and unchanged until the cutover, observation, rollback, and retirement gates below are all satisfied.

Expected new-server profile:
- Dual AMD EPYC 7313, 2 x 16 physical cores, 32 physical cores total.
- 128 GB RAM.
- 4 x 1.92 TB NVMe in RAID 10, approximately 3.84 TB usable before filesystem overhead.
- 1 Gbps unmetered network subject to provider network-protection/fair-use policy.
- Debian 12 x86_64.
- User-Responsible management.
- No cPanel, Webuzo, Softaculous, or WHMCS.
- Full root and out-of-band IPMI/recovery access expected.

Never store passwords, SSH private keys, IPMI credentials, recovery keys, provider secrets, raw environment files, or customer data in this roadmap, Git, receipts, or chat logs.

## Migration invariants

1. The old production server remains authoritative until explicit cutover acceptance.
2. No destructive change, wipe, cancellation, or cleanup of old production before rollback-retirement approval.
3. Provider confirmation is not enough by itself; an independent read-only host audit must pass before the first data upload.
4. No blind copying of secrets. Secrets move only through approved secure handling and are never committed.
5. RAID is redundancy, not backup. A separate encrypted backup and tested restore path is mandatory.
6. Public traffic is not switched until the new server passes isolated application acceptance.
7. The new server has a different public IP. Every direct-IP dependency, allowlist, callback, webhook, monitoring target, and external integration must be inventoried before cutover.
8. Prefer the existing Cloudflare Tunnel architecture so public hostnames are not tightly coupled to the server IP.
9. The old and new servers run in parallel during migration and observation.
10. Every phase ends with a documented PASS, HOLD, or ROLLBACK decision.
11. No paid-provider fanout or real customer data is used in load tests unless separately approved.
12. Deferred scope remains deferred: XR, unconnected/secondary providers, payments/store-app activation, and other explicitly deferred items are not silently reactivated by the migration.

## NS-00 — Independent pre-migration host audit

Run before uploading any application data.

Verify from the new server itself:
- Debian 12 release and kernel.
- CPU model, sockets, cores, threads, NUMA topology.
- Total RAM, available RAM, memory topology/ECC visibility where exposed.
- All four NVMe devices, model/firmware/health, without publishing sensitive hardware identifiers.
- RAID 10 membership and health.
- Array fully synchronized, no rebuild, no degraded member.
- Actual usable filesystem capacity consistent with RAID 10.
- Partition table and boot layout.
- Boot redundancy and recovery path.
- Filesystem type, mount options, free space, and inode capacity.
- Network interfaces, link state, negotiated speed, gateway, DNS resolution, and time synchronization.
- Root access works.
- IPMI/out-of-band console access works independently of SSH.
- No unexpected hosting panel or preinstalled stack is present.
- No unexplained public listeners.

Exit: independent OS/hardware/RAID/network baseline PASS. If anything differs from the order or provider confirmation, stop before upload and have the provider correct it.

## NS-01 — Host security baseline

Before installing the application:
- Apply Debian 12 security updates using a controlled maintenance step.
- Record the kernel and package baseline.
- Set final hostname, timezone, NTP/chrony/systemd-timesyncd and verify synchronized time.
- Establish approved SSH key access.
- Establish least-privilege admin/sudo path and emergency root recovery.
- Harden SSH and disable weak authentication/algorithms according to project policy.
- Configure firewall/nftables with deny-by-default inbound policy.
- Expose only explicitly required management and application paths.
- Configure fail2ban or equivalent brute-force protection.
- Configure unattended security updates consistent with maintenance policy.
- Configure journald/logrotate retention and disk-growth controls.
- Verify no accidental public DB, Redis, Docker API, metrics, or admin listeners.
- Keep IPMI credentials outside the project repository and application environment.
- Confirm the provider network and reverse DNS requirements, if any.

Exit: hardened host with a proven independent recovery path.

## NS-02 — Storage and filesystem operating model

Before copying production state:
- Confirm RAID 10 health monitoring.
- Enable periodic RAID health checks/scrubs where appropriate.
- Confirm NVMe SMART/health monitoring.
- Choose the final filesystem and mount layout before bulk data transfer.
- Define separate locations for application source, Docker data, database volumes, uploads/assets, logs, build/cache data, and migration staging.
- Preserve large free-space headroom; normal production should not be planned near the old server's 95% usage.
- Target operational disk warnings before 70%, escalation at 80%, urgent remediation before 85%.
- Define cleanup rules for build caches, stale worktrees, temporary artifacts, old images, and logs.
- Keep backup copies off the same server/RAID.
- Confirm backup target capacity and encryption.

Exit: storage layout documented, health monitoring available, and independent backup destination ready.

## NS-03 — Base runtime installation

Install only required supported components:
- Docker Engine.
- Docker Compose v2.
- Git and deployment utilities.
- Required monitoring/storage/network tools.
- Cloudflared package and service files prepared but not used for production cutover yet.
- Host Node/Python tooling only when genuinely required; prefer project containers for reproducibility.
- Required systemd units only from reviewed project source.
- No cPanel or unrelated hosting stack.
- Record all installed versions.

Exit: clean reproducible host runtime with no production traffic.

## NS-04 — Source and configuration preparation

- Fetch the canonical ipdomx/AIONEX-AIOS repository from protected main.
- Use the approved new-server production root.
- Verify exact commit SHA and clean checkout.
- Do not copy a dirty old-server checkout as the source of truth.
- Validate Compose files and deployment manifests before startup.
- Prepare required directories, permissions, ownership, and file modes.
- Migrate configuration through secure secret handling.
- Never commit secrets or raw env files.
- Inventory all old-IP dependencies before changing them:
  - firewall allowlists,
  - provider callbacks,
  - webhooks,
  - monitoring targets,
  - outbound allowlists,
  - third-party dashboards,
  - backup endpoints,
  - SSH trust/known-host references where operationally relevant.
- Preserve all current deferrals and provider-live safeguards.

Exit: source/configuration ready with no public traffic and no paid-provider side effect.

## NS-05 — Pre-migration backup and rollback package

Before copying mutable production state:
- Create a fresh encrypted production backup using the accepted backup path.
- Create a consistent PostgreSQL backup/snapshot and verify integrity.
- Capture required persistent volumes, uploads, assets, and metadata.
- Capture service topology and deployment manifests without exposing secrets.
- Record:
  - source commit SHA,
  - container image identities/digests where available,
  - database schema/migration level,
  - application release/version,
  - backup timestamp,
  - RPO reference point.
- Verify the backup can be read.
- Perform an isolated restore test before relying on it.
- Establish rollback owner and rollback trigger criteria.

Exit: independently restorable pre-migration package PASS.

## NS-06 — Initial bulk migration while old production stays live

- Transfer immutable and large data first.
- Use integrity-preserving copy methods and checksums/manifests.
- Copy application uploads/assets and persistent storage.
- Restore a database copy to the new server in isolated mode.
- Do not blindly copy ephemeral caches.
- Restore Redis persistent state only if required by the application contract.
- Bring up PostgreSQL, Redis, application containers, and supporting services on the new server without public production traffic.
- Keep old production accepting normal traffic.

Exit: isolated complete replica available for testing.

## NS-07 — Isolated application acceptance

Validate the new server before any public cutover:
- Expected containers start successfully.
- Intentionally drained services remain intentionally drained.
- No running container is unhealthy.
- Backend health/readiness endpoints pass.
- PostgreSQL connectivity, schema, migrations, row/data integrity, indexes, and extensions are correct.
- Redis connectivity and queue/session semantics are correct.
- Nginx public/private origin layout is correct.
- Public portal, user portal, and Owner portal routes work.
- Authentication and authorization work.
- Owner controls, suspension, revocation, policy limits, and audit trails work.
- Multiple projects and multiple conversations work.
- Save/resume and isolation work.
- Upload/download and asset isolation work.
- WebSocket/event-stream behavior works.
- Six-language, RTL, dark mode, mobile, Safari, and accessibility checks run where applicable.
- Browser E2E, security baseline, source validation, and final validation suites pass.
- Provider connectors remain synthetic/fail-closed unless a separately approved real-provider acceptance is required.
- Resource/provider credit alerts and monitoring contracts work.

Exit: isolated new-server application acceptance PASS with no unexplained regression.

## NS-08 — Cloudflare and network cutover preparation

- Inventory all current DNS records, Tunnel routes, Access policies, callbacks, webhooks, monitoring endpoints, and direct-IP dependencies.
- Preserve current Cloudflare policy; migration is not permission to redesign Access or DNS.
- Prepare the new server as a reviewed Cloudflare Tunnel connector/origin.
- Keep the old connector/origin available for rollback.
- Verify the user portal, public site, and Owner portal private/public routing boundaries.
- Update direct-IP allowlists or callbacks deliberately, one by one, with evidence.
- Reduce DNS TTL only where a direct DNS switch is genuinely needed.
- Test the traffic-switch and rollback method before the maintenance window.

Exit: reversible traffic-switch plan proven.

## NS-09 — Rehearsal and final-delta plan

- Perform a complete rehearsal restore from accepted backup.
- Measure restore duration.
- Reconcile DB integrity, file counts, hashes/manifests, and persistent-volume completeness.
- Define the final maintenance/write-drain window.
- Define which queues/jobs must drain or stop accepting new work.
- Confirm no ambiguous in-flight provider jobs.
- Define final database snapshot and file-delta synchronization procedure.
- Confirm rollback can be executed without relying on the new server.

Exit: signed-off cutover checklist and proven rollback.

## NS-10 — Production cutover

Sequence:
1. Enter the controlled maintenance/write-drain window.
2. Gate new mutable work on the old server using accepted controls.
3. Allow in-flight work and queues to reach the defined safe state.
4. Take final DB backup/snapshot.
5. Perform final delta sync of persistent files/assets.
6. Restore/apply final delta on the new server.
7. Re-run migrations, DB integrity, readiness, permissions, and filesystem checks.
8. Start the new production stack.
9. Verify internal health before public traffic.
10. Activate the new Cloudflare Tunnel connector/origin or other preapproved traffic switch.
11. Run real-public-hostname smoke tests.
12. Verify authentication, Owner portal, user portal, projects, conversations, uploads, queues, DB, Redis, and critical APIs.
13. Monitor closely.
14. Keep the old server intact and ready for rollback.

Exit: production traffic successfully served by the new server while rollback remains available.

## NS-11 — Immediate rollback criteria and procedure

Rollback immediately for any material:
- database inconsistency or missing data,
- authentication/authorization regression,
- persistent 5xx/availability failure,
- broken Cloudflare routing or Access,
- queue duplication/loss or unsafe replay,
- corrupted upload/download,
- billing/entitlement inconsistency,
- critical security regression,
- critical monitoring/backup failure that makes continued operation unsafe.

Rollback sequence:
- Stop new writes on the new server.
- Route traffic back to the old server using the preplanned switch.
- Confirm old-server health before reopening writes.
- Preserve new-server evidence; do not wipe it.
- Reconcile data written during the attempted cutover before any second attempt.

## NS-12 — Post-cutover observation

Keep both servers for at least 72 hours, and longer if operational evidence requires it.

Monitor:
- HTTP/API error rate and latency.
- Authentication and authorization failures.
- PostgreSQL health, connections, locks, replication/backup state where relevant.
- Redis memory, latency, persistence, and queue behavior.
- Queue depth and wait time.
- Container health/restarts.
- CPU/load and scheduler pressure.
- RAM/swap/OOM events.
- RAID/NVMe health.
- Disk space, filesystem growth, IOPS and latency.
- Network throughput and 1 Gbps ceiling.
- Cloudflare Tunnel health.
- Scheduled jobs and monitoring.
- Backup success, age, and restoreability.
- Security/update/audit findings.

Exit: stable observation window with no unresolved critical issue.

## NS-13 — Capacity acceptance and 5,000-user growth readiness

The new hardware is intended to provide significant headroom, but 5,000 users does not mean 5,000 simultaneous heavy AI/GPU generations on one host.

Required:
- Re-run the canonical 1,000 authenticated-user / multiple-project / multiple-conversation acceptance on the new production-equivalent configuration.
- Characterize safe staged synthetic concurrency, as appropriate, across 500, 1,000, 2,500, and up to 5,000 sessions/projects without uncontrolled paid-provider fanout.
- Measure p50/p95/p99 latency.
- Measure request rate, error rate, queue depth/wait, CPU, RAM, swap, DB connections/locks, Redis, disk IOPS/latency, and network throughput.
- Preserve tenant isolation, zero lost jobs, and zero duplicate terminal executions.
- Abort escalation on correctness loss, rising 5xx, DB/queue saturation, swap thrash, unsafe provider fanout, RAID/storage pressure, or network saturation.
- Record a safe operating envelope rather than claiming unlimited capacity.
- Treat the 1 Gbps network as a possible future bottleneck.
- Define horizontal scale-out triggers:
  - additional application/worker nodes,
  - dedicated database node,
  - dedicated Redis/queue node,
  - external object storage/CDN for large assets,
  - specialized media/AI workers.
- Scale horizontally before a single-host bottleneck becomes a production incident.

Exit: measured capacity report with clear limits and scale-out triggers.

## NS-14 — Monitoring and ongoing operations

Required alerts:
- RAID degraded/rebuild.
- NVMe SMART/health.
- Disk and inode pressure.
- CPU/load.
- RAM/swap/OOM.
- Container unhealthy/restart loops.
- PostgreSQL availability/resource pressure.
- Redis availability/resource pressure.
- Queue depth/wait/failures.
- Public endpoints and Cloudflare Tunnel.
- Backup success/age/restoreability.
- Provider credit/usage alerts.
- Security updates/audit findings.

Maintain cleanup for:
- stale worktrees,
- build caches,
- obsolete images,
- old temporary migration files,
- logs and diagnostics,
while preserving evidence required by project policy.

## NS-14A — Client response and streaming resilience

This is a release-scope requirement prompted by the observed class of UI failure where a long response can stop with a generic “streaming interrupted / waiting” state. The external ChatGPT client failure is not evidence that AIOS itself has the same bug, but the analogous failure mode is now explicitly in AIOS scope and must be tested before final release closure.

Required behavior for every AIOS long-lived response, stream, live progress feed, or equivalent asynchronous delivery path:
- Never silently hang forever. Use bounded idle/overall timeouts plus heartbeat/progress semantics where a long-lived transport is used.
- Preserve the accepted request/job identity independently of the client transport.
- A network drop, app background/foreground transition, proxy timeout, server restart, or client reconnect must not create a duplicate billable provider request or duplicate terminal execution.
- If the transport is resumable, reconnect from an acknowledged cursor/sequence/event id with bounded exponential backoff and jitter.
- If the upstream/provider stream cannot be resumed, the client must fall back to durable job/status retrieval rather than pretending the partial stream completed.
- Duplicate/replayed chunks or terminal events must be idempotently de-duplicated.
- UI states must distinguish connecting, streaming/running, reconnecting, recovered, completed, cancelled and failed; a generic indefinite spinner is not acceptable.
- Partial content/progress that is safe to retain should remain visible after reconnect.
- Authentication/session expiry during reconnect must fail closed and present a recoverable user action without losing the underlying durable job when policy permits.

Acceptance must cover at least: mid-stream TCP drop, Cloudflare/proxy interruption, client app background/foreground, network change, repeated reconnect, duplicate events, server/container restart, auth refresh/expiry, terminal-event loss, and fallback polling/status recovery.

Status: MERGED_DEPLOYED_RUNTIME_STRUCTURAL_PASS_EXTENDED_FAULT_ACCEPTANCE_PENDING. PR #872 exact head `d17c54530c9142f04bbf9aab50a1df01f5abe926` merged as `9dd7a79d3b590a25675d5209de14b5176cba7f7f` and is deployed in release `960dab80fe8ec27b1e8bf59425b766e03f9b9783`. Runtime structural/public smoke is PASS; the complete NS-14A disconnect/reconnect fault matrix remains required before final acceptance.

## NS-15 — Canonical documentation reconciliation

After stable cutover:

### Exact-SHA new-server operating discipline

The accepted operating path is explicit and immutable-SHA based:

1. MCP2 may land on the retained management/old host; do not infer from the MCP name that the process is executing directly on the new host.
2. Reach the new host only through the already-approved SSH migration/administration channel with strict host-key verification; never place host IPs, private-key paths/material, credentials or raw host secrets in tracked docs.
3. Resolve the exact protected-main or reviewed PR head SHA from GitHub before mutation.
4. On the new host, fetch the required ref and verify the exact SHA. Do not use a blind `git pull` as the release decision.
5. Build/test from a clean detached worktree or clean checkout bound to that immutable SHA. Dirty source is never release authority.
6. Protected CI evidence is valid only for the exact head SHA it tested. A newer commit requires fresh exact-head acceptance.
7. Before rollout, preserve rollback source/image identities and revalidate maintenance/admission authority.
8. After rollout, verify runtime source/content hashes or image identities, database/schema expectations, public/authenticated health and relevant feature smoke against the accepted SHA.
9. Keep the old server and rollback artifacts intact until the observation/retirement gates and explicit Owner approval are satisfied.

This is the continuity method to use if a conversation is interrupted: recover the last accepted SHA and evidence first, then continue from the new host without replaying already-performed effects.

### Update ledger and map reconciliation policy

Every material project transition must be retained, including unsuccessful work. The minimum record is: UTC time, phase/batch, exact source/candidate SHA, target environment/host role, action, outcome, evidence reference/hash where available, whether production was mutated, and the explicit next action.

Allowed operational outcomes are at least: IN_PROGRESS, PASS, FAIL, BLOCKED/HOLD, PENDING_RETRY, ROLLBACK and COMPLETE. Failed or superseded attempts are evidence and are not overwritten to make the history look clean.

The append-only runtime journal/checkpoint is the immediate execution ledger. The canonical PLAN/roadmap is the durable reviewed summary and is reconciled at material checkpoints; transient minute-by-minute CI polling does not require a Git commit for every poll. Generated STATE.json and PROJECT-REPORT.md are updated through `scripts/project_hub.py`, never hand-edited.

Before starting a new continuation, read the canonical map, latest checkpoint/journal, GitHub protected state and live new-host evidence. If any “done / failed / still required” state is absent or contradictory, record the drift before further mutation.

- Update PLAN and canonical project state through scripts/project_hub.py.
- Never hand-edit generated STATE.json or PROJECT-REPORT.md.
- Record the new production hardware profile, Debian 12 baseline, source SHA, images, DB schema, migration/cutover timestamp, and acceptance evidence.
- Update recovery, backup, monitoring, and rollback runbooks.
- Confirm the old public IP is no longer required by any DNS record, allowlist, callback, webhook, monitoring target, or provider integration.
- Never store credentials in tracked documentation.

Exit: source, production, documentation, monitoring, and recovery evidence agree.

## NS-16 — Old-server retirement

Only after all prior gates and explicit Owner approval:
- Take final archival backup of old production.
- Independently verify new-server backup/restore.
- Confirm no user traffic, scheduled job, provider callback, monitoring target, or Cloudflare route still depends on the old server.
- Rotate/revoke old-server-only credentials and SSH trust as appropriate.
- Remove the old Cloudflare Tunnel connector only after new-connector stability is proven.
- Preserve required audit/history evidence.
- Contact provider Billing to cancel the old server only after explicit Owner approval.
- Never cancel early merely to save cost.

## Migration complete definition

Migration is complete only when all are true:
- Independent new-host audit PASS.
- Security/storage/runtime baseline PASS.
- Source/configuration/data migration verified.
- New server serves public production traffic.
- Required production acceptance PASS.
- Canonical 1,000-user capacity acceptance PASS on the new server.
- 5,000-user growth envelope and horizontal scaling triggers are documented honestly.
- Backup/restore/recovery and monitoring PASS.
- Old-server rollback observation window completes successfully.
- Client response/stream delivery resilience acceptance PASS, including reconnect/fallback without duplicate execution or provider charge.
- Canonical project documentation is reconciled.
- Owner explicitly approves retirement of the old server.

Until then the status remains MIGRATION_IN_PROGRESS_NOT_COMPLETE.
