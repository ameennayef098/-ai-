# ============================================================================
# سيرفر أمين — سيرفر محلي بايثون (بدون مكتبات خارجية)
# ----------------------------------------------------------------------------
# يخدم موقعين + وسيط للذكاء الاصطناعي:
#   1) مرصد التهديدات السيبرانية (/)    → مجلد cyber-threat-observatory
#   2) اركان AI / سايبو     (/arkan)      → مجلد arkan-ai
#
# المسارات (API):
#   /api/chat          وسيط الذكاء الاصطناعي (NVIDIA NIM مع احتياطي Ollama)
#   /api/tts           POST {text, voice} → MP3 عربي (ElevenLabs) — يُخزّن بكاش
#   /api/stt           POST (ملف صوتي خام) → {text} (ElevenLabs scribe_v1)
#   /api/data          حفظ تعديلات الأدمن (أركان + صفحة عن الموقع)
#   /api/queue/*       نظام الدور — 3 أجهزة تجاوب معاً والباقي ينتظر برقم
#   /api/stats/*       الإحصائيات (زوار، أسئلة، تصدير CSV، تصفير)
#   /api/qrcode        GET ?text= → باركود SVG (للزوار يمسحونه بموبايلهم)
#   /api/ollama/start|stop  تشغيل/إيقاف النموذج المحلي (للمضيف فقط)
#
# ملاحظة: الصفحة كلها تعتمد على هذا السيرفر — بدونه ما تفتح.
# التشغيل:  python server.py     ثم افتح http://localhost:8080/arkan
# ============================================================================
# سيرفر محلي — يخدم موقعين + وسيط Ollama
# 1) مرصد التهديدات السيبرانية (/)  → مجلد cyber-threat-observatory
# 2) اركان AI (/arkan)              → مجلد arkan-ai
# وكل طلبات /api/* تُمرَّر إلى Ollama على جهازك
import http.server, socketserver, json, urllib.request, urllib.parse, os, socket, threading, time, hashlib

# باركود QR — يولّد SVG من نص
try:
    import segno
    HAS_QR = True
except Exception:
    HAS_QR = False

PORT = int(os.environ.get("PORT", 8080))
OLLAMA = "http://127.0.0.1:11434"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ===== NVIDIA NIM API (سحابي — سريع) =====
NVIDIA_API_KEY = os.environ.get("NVIDIA_API_KEY", "")
NVIDIA_MODEL = "nvidia/nemotron-3-super-120b-a12b"
NVIDIA_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
NVIDIA_EXTRA = {"chat_template_kwargs": {"enable_thinking": False}}

# ===== ElevenLabs API (نص → صوت عربي طبيعي) =====
# المفتاح: صلاحيات tts + speech_to_text (بدون voices_read/models_read)
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
# صوت سايبو (CYBO) — المتحدث الرئيسي
ELEVENLABS_VOICE = "JBFqnCBsd6RMkjVDRZzb"     # George — متعدد اللغات ويدعم العربي
# صوت الاحتيال — يُستخدم في «معركة الذكاء» عشان يفرق الزائر بين الشخصيتين سمعياً
ELEVENLABS_VOICE_FRAUD = "pNInz6obpgDQGcFmaJgB"  # Adam — ذكر مختلف تماماً عن سايبو
ELEVENLABS_MODEL = "eleven_multilingual_v2"    # أفضل موديل للعربي
ELEVENLABS_URL = "https://api.elevenlabs.io/v1/text-to-speech/" + ELEVENLABS_VOICE
ELEVENLABS_URL_FRAUD = "https://api.elevenlabs.io/v1/text-to-speech/" + ELEVENLABS_VOICE_FRAUD
ELEVENLABS_STT_MODEL = "scribe_v1"              # موديل تحويل الكلام إلى نص (يدعم العربي)
ELEVENLABS_STT_URL = "https://api.elevenlabs.io/v1/speech-to-text"
TTS_DIR = os.path.join(BASE_DIR, "arkan-ai", "tts")   # كاش الملفات الصوتية

# ملف البيانات المشترك — كل الزوار يرون نفس التعديلات
DATA_FILE = os.path.join(BASE_DIR, "arkan-ai", "data.json")
STATS_FILE = os.path.join(BASE_DIR, "arkan-ai", "stats.json")

SITES = {
    "/": os.path.join(BASE_DIR, "cyber-threat-observatory"),
    "/arkan": os.path.join(BASE_DIR, "arkan-ai"),
}

# ===== البيانات الافتراضية (تُكتب أول مرة فقط) =====
DEFAULT_DATA = {
    "corners": [
        {
            "id": "observatory",
            "title": "ركن مرصد التهديدات السيبرانية",
            "authors": ["الأمين نايف دواغره", "عمر السيد خليل", "فهد العتيبي"],
            "short": "منصة توعية تفاعلية عن الأمن السيبراني، تعمل بالكامل محلياً بدون إنترنت.",
            "full": "• اسم المشروع: مرصد التهديدات السيبرانية.\n"
                    "• هو موقع تعليمي تفاعلي يهدف إلى نشر الوعي بالأمن السيبراني بأسلوب مبسّط يناسب الجميع.\n"
                    "• يعمل بالكامل على الجهاز المحلي بدون إنترنت — لا تُرسل أي بيانات لأي خدمة خارجية.\n"
                    "• أقسامه الاثنا عشر: لوحة المعلومات، خرائط التهديدات، الإحصائيات، مكتبة التهديدات، مختبر التصيد، "
                    "الهندسة الاجتماعية OSINT، الاختبارات، التوعية، قسم «جرّب بنفسك»، اركان AI، عن الموقع، والمصادر.\n"
                    "• قسم «جرّب بنفسك» يحتوي ثلاث أدوات تفاعلية: فحص الروابط المشبوهة، فحص قوة كلمة المرور، "
                    "وجمع معلومات النطاق — كلها تعمل داخل المتصفح بدون إرسال أي بيانات.\n"
                    "• خريطة التهديدات تعرض بيانات C2 حقيقية من مصدر ThreatFox.\n"
                    "• المساعد الذكي «اركان» نموذج مبرمج محلياً على جهاز المضيف.\n"
                    "• أُنشئ بواسطة الطلاب: الأمين نايف دواغره، عمر السيد خليل، وفهد العتيبي.",
            "questions": [
                "ما هو مرصد التهديدات السيبرانية؟",
                "ما أقسام الموقع؟",
                "هل الموقع يحتاج إنترنت؟",
                "ما هي أداة «جرّب بنفسك»؟",
                "من نفّذ هذا الركن؟"
            ],
            "welcome": "",
            "pending": False,
            "img": ""
        },
        {
            "id": "data-classification",
            "title": "ركن تنسيق البيانات",
            "authors": ["موسى عيدان الزهراني", "يزيد ظافر القرني"],
            "short": "كيفية تصنيف البيانات ومفهوم التصنيف وأهدافه الخمسة.",
            "full": "• التعريف: تصنيف البيانات هو ترتيب وتصنيف البيانات إلى فئات أو مجموعات حسب أهميتها أو قيمتها "
                    "أو المتطلبات الأمنية والقانونية.\n"
                    "• أهداف تصنيف البيانات:\n"
                    "١- تعزيز الأمن السيبراني وحماية البيانات.\n"
                    "٢- الالتزام بالأنظمة والقوانين.\n"
                    "٣- إدارة التكاليف وتحسين الاستهلاك.\n"
                    "٤- تحسين الكفاءة والإنتاجية.\n"
                    "٥- الاستجابة السريعة للحوادث والأزمات.\n"
                    "• أُنشئ بواسطة الطلاب: موسى عيدان الزهراني، ويزيد ظافر القرني.",
            "questions": [
                "ما هو تصنيف البيانات؟",
                "ما هي أهداف تصنيف البيانات؟",
                "لماذا نصنّف البيانات؟",
                "من نفّذ هذا الركن؟"
            ],
            "welcome": "",
            "pending": False,
            "img": ""
        },
        {
            "id": "threats",
            "title": "ركن التهديدات السيبرانية",
            "authors": ["فيصل عبدالرحمن", "حمد القحطاني"],
            "short": "تجربة حية تُظهر خطر الشبكات المفتوحة وكيف تُسرق بياناتك.",
            "full": "• فكرة الركن: عرض لشبكة إنترنت مفتوحة — مثل شبكات المولات والمقاهي التي تكون بدون رمز حماية.\n"
                    "• التعبير عن خطورتها من خلال تجربة عملية: يتصل شخص بالشبكة المفتوحة، "
                    "ثم يسجل حساباته فيها، فتظهر لصاحب الشبكة بياناته كاملة التي سجّلها.\n"
                    "• الهدف: إيصال رسالة توعوية بأن أي شبكة عامة بدون تشفير تجعل بياناتك مكشوفة لأي شخص على نفس الشبكة.\n"
                    "• أُنشئ بواسطة الطلاب: فيصل عبدالرحمن، وحمد القحطاني.",
            "questions": [
                "ما فكرة ركن التهديدات السيبرانية؟",
                "ما خطر الشبكات المفتوحة؟",
                "كيف أحمي نفسي على شبكة عامة؟",
                "من نفّذ هذا الركن؟"
            ],
            "welcome": "",
            "pending": False,
            "img": ""
        },
        {"id": "c4", "title": "الركن الرابع", "authors": [], "short": "قيد الإعداد.", "full": "",
         "questions": [], "welcome": "", "pending": True, "img": ""},
        {"id": "c5", "title": "الركن الخامس", "authors": [], "short": "قيد الإعداد.", "full": "",
         "questions": [], "welcome": "", "pending": True, "img": ""},
        {"id": "c6", "title": "الركن السادس", "authors": [], "short": "قيد الإعداد.", "full": "",
         "questions": [], "welcome": "", "pending": True, "img": ""}
    ],
    "about": {
        "body": "اركان AI هو مساعد ذكاء اصطناعي مبرمج محلياً على جهاز المضيف. "
                "المشروع يهدف إلى توفير مساعد ذكي باللغة العربية يعمل بدون إنترنت، يحترم خصوصية المستخدم "
                "(كل المحادثات تبقى على الجهاز)، ويصلح للاستخدام في الفصول والمعارض والأندية التقنية. "
                "زوّار نفس الشبكة يستطيعون الوصول إليه عبر الشبكة المحلية.",
        "privacy": "هذا المساعد لا يرسل أي بيانات لأي خدمة خارجية. كل الأسئلة والردود تُعالَج على جهاز المضيف فقط. "
                   "محتوى صفحة «عن الموقع» والصور تُحفظ محلياً ولا تُشارَك مع أي طرف."
    }
}

_data_lock = threading.Lock()
_stats_lock = threading.Lock()

DEFAULT_STATS = {
    "visits": 0,
    "questions": 0,
    "per_corner": {},
    "top_questions": {},
    "log": [],           # [{name, q, corner, at}] — سجل تفصيلي (آخر 300)
    "visitors": {},      # {name: count} — الزوار المسجّلون
    "started": time.strftime("%Y-%m-%d %H:%M:%S")
}
LOG_MAX = 300


def load_data():
    """يقرأ data.json — يرجع الافتراضي لو مو موجود (وينشئه)."""
    with _data_lock:
        try:
            with open(DATA_FILE, encoding="utf-8") as f:
                d = json.load(f)
            # توافق: لو النسخة القديمة ناقصة حقول
            if "corners" not in d:
                d["corners"] = DEFAULT_DATA["corners"]
            if "about" not in d:
                d["about"] = DEFAULT_DATA["about"]
            d.setdefault("savedAt", 0)
            return d
        except Exception:
            pass
    # ملاحظة: الكتابة خارج القفل — save_data يمسك القفل بنفسه،
    # ومسكه وهو ممسوك يعني deadlock وتجميد السيرفر بالكامل
    save_data(DEFAULT_DATA)
    return json.loads(json.dumps(DEFAULT_DATA))


def save_data(data):
    with _data_lock:
        tmp = DATA_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, DATA_FILE)   # كتابة ذرّية — ما ينكسر لو انقطع


def load_stats():
    with _stats_lock:
        try:
            with open(STATS_FILE, encoding="utf-8") as f:
                s = json.load(f)
            for k, v in DEFAULT_STATS.items():
                s.setdefault(k, v)
            return s
        except Exception:
            pass
    save_stats(DEFAULT_STATS)
    return json.loads(json.dumps(DEFAULT_STATS))


def save_stats(stats):
    with _stats_lock:
        tmp = STATS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(stats, f, ensure_ascii=False, indent=1)
        os.replace(tmp, STATS_FILE)


def bump_stat(kind, key=None, name=None, corner=None):
    """يزيد عدّاد: visit / question / corner — مع اسم الزائر والركن للسجل."""
    try:
        s = load_stats()
        s.setdefault("log", [])
        s.setdefault("visitors", {})
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        if kind == "visit":
            s["visits"] += 1
        elif kind == "question":
            s["questions"] += 1
            if key:
                # نطبع السؤال حتى ما يتكرر بنفس المعنى، ونحفظ أكثر 30
                k = key.strip()[:80]
                s["top_questions"][k] = s["top_questions"].get(k, 0) + 1
                if len(s["top_questions"]) > 30:
                    # احذف الأقل تكراراً
                    least = sorted(s["top_questions"], key=lambda x: s["top_questions"][x])[0]
                    s["top_questions"].pop(least, None)
            # السجل التفصيلي: الاسم + السؤال + الركن + الوقت
            if name:
                cur = s["visitors"].get(name)
                base = cur.get("count", 0) if isinstance(cur, dict) else (cur or 0)
                s["visitors"][name] = {"count": base + 1,
                                       "first": cur.get("first", now) if isinstance(cur, dict) else now,
                                       "last": now}
            s["log"].append({"name": name or "زائر", "q": (key or "")[:120],
                             "corner": corner or "", "at": now})
            if len(s["log"]) > LOG_MAX:
                s["log"] = s["log"][-LOG_MAX:]
        elif kind == "corner" and key:
            s["per_corner"][key] = s["per_corner"].get(key, 0) + 1
        save_stats(s)
    except Exception:
        pass


def reset_stats():
    """يمسح كل الإحصائيات ويبدأ من جديد."""
    fresh = json.loads(json.dumps(DEFAULT_STATS))
    fresh["started"] = time.strftime("%Y-%m-%d %H:%M:%S")
    save_stats(fresh)
    return fresh


# =====================================================================
#  نظام الدور (الطابور) — عدد الأجهزة اللي تجاوب بنفس الوقت
# =====================================================================
MAX_CONCURRENT = 3          # 3 أجهزة تجاوب معاً، الرابع ينتظر دوره
QUEUE = []                  # [{id, joined, active, last_seen}]
_queue_lock = threading.Lock()
QUEUE_TIMEOUT = 45          # ثانية بدون نبضة وهو بالانتظار → يُلغى دوره
ACTIVE_TIMEOUT = 240        # ثانية للرد الجاري قبل الإلغاء القسري (احتياط)


def _sweep_queue_locked(now):
    """يلغي أدوار اللي انغلق متصفحهم (ما نبضوا بالوقت المحدد)."""
    alive = []
    for e in QUEUE:
        limit = ACTIVE_TIMEOUT if e["active"] else QUEUE_TIMEOUT
        if now - e["last_seen"] <= limit:
            alive.append(e)
    QUEUE[:] = alive


def _promote_queue_locked():
    """يرقّي أقدم المنتظرين لأي مكان فاضي (حتى MAX_CONCURRENT)."""
    n_active = sum(1 for e in QUEUE if e["active"])
    for e in QUEUE:                       # QUEUE مرتّب بترتيب الدخول
        if n_active >= MAX_CONCURRENT:
            break
        if not e["active"]:
            e["active"] = True
            n_active += 1


def _queue_snapshot_locked():
    active = [e for e in QUEUE if e["active"]]
    waiting = [e for e in QUEUE if not e["active"]]
    return active, waiting


def queue_join(client_id):
    """يدخل الطابور. يرجع هل دوره الآن أم لا + رقمه لو منتظر."""
    now = time.time()
    with _queue_lock:
        _sweep_queue_locked(now)
        e = next((x for x in QUEUE if x["id"] == client_id), None)
        if not e:
            e = {"id": client_id, "joined": now, "active": False, "last_seen": now}
            QUEUE.append(e)
        e["last_seen"] = now
        _promote_queue_locked()
        active, waiting = _queue_snapshot_locked()
        if e["active"]:
            return {"active": True, "position": 0,
                    "active_count": len(active), "waiting": len(waiting), "max": MAX_CONCURRENT}
        pos = waiting.index(e) + 1 if e in waiting else len(waiting) + 1
        return {"active": False, "position": pos,
                "active_count": len(active), "waiting": len(waiting), "max": MAX_CONCURRENT}


def queue_status(client_id):
    """حالة الدور + نبضة حياة (تحدّث آخر ظهور)."""
    now = time.time()
    with _queue_lock:
        _sweep_queue_locked(now)
        e = next((x for x in QUEUE if x["id"] == client_id), None)
        if not e:
            return {"active": False, "known": False,
                    "active_count": sum(1 for x in QUEUE if x["active"]),
                    "waiting": len([x for x in QUEUE if not x["active"]]), "max": MAX_CONCURRENT}
        e["last_seen"] = now
        _promote_queue_locked()
        active, waiting = _queue_snapshot_locked()
        if e["active"]:
            return {"active": True, "known": True, "position": 0,
                    "active_count": len(active), "waiting": len(waiting), "max": MAX_CONCURRENT}
        pos = waiting.index(e) + 1 if e in waiting else len(waiting) + 1
        return {"active": False, "known": True, "position": pos,
                "active_count": len(active), "waiting": len(waiting), "max": MAX_CONCURRENT}


def queue_release(client_id):
    """ينهي الدور ويرقّي أول منتظر فوراً."""
    now = time.time()
    with _queue_lock:
        e = next((x for x in QUEUE if x["id"] == client_id), None)
        if e:
            QUEUE.remove(e)
        _promote_queue_locked()
        active, waiting = _queue_snapshot_locked()
        return {"ok": True, "active_count": len(active), "waiting": len(waiting)}


def queue_heartbeat(client_id):
    now = time.time()
    with _queue_lock:
        e = next((x for x in QUEUE if x["id"] == client_id), None)
        if e:
            e["last_seen"] = now
        return {"ok": bool(e)}

class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        # CORS: يسمح لأي جهاز على الشبكة بالاتصال
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    # ---------- NVIDIA NIM API (سحابي) ----------
    def _nvidia_chat(self, body):
        """يستقبل رسائل بصيغة Ollama ويحوّلها لـ NVIDIA NIM، يبثّ الرد بصيغة Ollama."""
        try:
            data = json.loads(body)
            # استخراج الرسائل من صيغة Ollama
            messages = data.get("messages", [])
            if not messages and data.get("prompt"):
                messages = [{"role": "user", "content": data["prompt"]}]
            # خيارات Ollama → OpenAI
            opts = data.get("options", {}) or {}
            nv_req = {
                "model": NVIDIA_MODEL,
                "messages": messages,
                "temperature": opts.get("temperature", 0.5),
                "top_p": opts.get("top_p", 0.9),
                "max_tokens": opts.get("num_predict", 300),
                "stream": True
            }
            nv_req.update(NVIDIA_EXTRA)
            nv_body = json.dumps(nv_req).encode("utf-8")
            req = urllib.request.Request(NVIDIA_URL, data=nv_body, method="POST")
            req.add_header("Authorization", "Bearer " + NVIDIA_API_KEY)
            req.add_header("Content-Type", "application/json")
            req.add_header("Accept", "text/event-stream")
            resp = urllib.request.urlopen(req, timeout=15)
            # بثّ الرد بصيغة Ollama NDJSON حتى الواجهة تفهمه
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            buf = b""
            while True:
                chunk = resp.read(512)
                if not chunk:
                    break
                buf += chunk
                # NVIDIA يرسل SSE: "data: {...}\n\n"
                while b"\n\n" in buf:
                    line, buf = buf.split(b"\n\n", 1)
                    line = line.strip()
                    if not line.startswith(b"data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == b"[DONE]":
                        # إشعار انتهاء البث
                        done = json.dumps({"done": True}).encode("utf-8")
                        self.wfile.write(done + b"\n")
                        self.wfile.flush()
                        continue
                    try:
                        obj = json.loads(payload)
                        choice = obj.get("choices", [{}])[0]
                        msg_obj = choice.get("delta", {}) or {}
                        content = msg_obj.get("content", "") or ""
                        # احتياط: لو رجع reasoning بدون content (النموذج فكّر)، تجاهله
                        if not content and msg_obj.get("reasoning_content"):
                            continue
                        if content:
                            # تحويل لصيغة Ollama
                            out = json.dumps({"message": {"role": "assistant", "content": content}}).encode("utf-8")
                            self.wfile.write(out + b"\n")
                            self.wfile.flush()
                    except Exception:
                        pass
            resp.close()
            # إنهاء نهائي
            try:
                end = json.dumps({"done": True, "done_reason": "stop"}).encode("utf-8")
                self.wfile.write(end + b"\n")
                self.wfile.flush()
            except Exception:
                pass
        except Exception as e:
            # fallback لـ Ollama المحلي عند فشل NVIDIA
            try:
                self._ollama_chat(body)
            except Exception as e2:
                try:
                    err = json.dumps({"error": "NVIDIA: " + str(e) + " | Ollama: " + str(e2)}).encode("utf-8")
                    self.send_response(502)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(err)
                except Exception:
                    pass

    # ---------- Ollama fallback (عند فشل NVIDIA) ----------
    def _ollama_chat(self, body):
        """بديل: يمرّر الطلب مباشرة لـ Ollama المحلي ويبث الرد بصيغة NDJSON."""
        try:
            req = urllib.request.Request(OLLAMA + "/api/chat", data=body, method="POST")
            req.add_header("Content-Type", "application/json")
            resp = urllib.request.urlopen(req, timeout=120)
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            while True:
                line = resp.readline()
                if not line:
                    break
                self.wfile.write(line)
                self.wfile.flush()
            resp.close()
        except Exception as e:
            raise RuntimeError("Ollama error: " + str(e))

    # ---------- ElevenLabs: نص عربي → صوت ----------
    def _tts_api(self):
        """يستقبل {text} ويولّد MP3 عربي من ElevenLabs، يُحفظ بالكاش ويُعاد رابطه.

        voice: "cybo" (سايبو — الافتراضي) أو "fraud" (صوت الاحتيال في معركة الذكاء).
        """
        try:
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except Exception:
            self._json({"error": "bad json"}, 400)
            return
        text = (payload.get("text") or "").strip()
        if not text:
            self._json({"error": "no text"}, 400)
            return
        if len(text) > 1500:
            text = text[:1500]
        # ===== اختيار الصوت =====
        # "cybo"  = سايبو (الافتراضي)  |  "fraud" = صوت الاحتيال (معركة الذكاء)
        voice = (payload.get("voice") or "cybo").strip().lower()
        if voice not in ("cybo", "fraud"):
            voice = "cybo"
        voice_url = ELEVENLABS_URL_FRAUD if voice == "fraud" else ELEVENLABS_URL
        try:
            os.makedirs(TTS_DIR, exist_ok=True)
            # الكاش يشمل اسم الصوت حتى ما يتخانق صوتا سايبو والاحتيال
            key = hashlib.md5((voice + "::" + text).encode("utf-8")).hexdigest()
            fname = key + ".mp3"
            fpath = os.path.join(TTS_DIR, fname)
            if not os.path.exists(fpath) or os.path.getsize(fpath) < 200:
                body = json.dumps({
                    "text": text,
                    "model_id": ELEVENLABS_MODEL,
                    "voice_settings": {
                        "stability": 0.5,
                        "similarity_boost": 0.75,
                        "style": 0.0,
                        "use_speaker_boost": True
                    }
                }).encode("utf-8")
                req = urllib.request.Request(voice_url, data=body, method="POST")
                req.add_header("xi-api-key", ELEVENLABS_API_KEY)
                req.add_header("Content-Type", "application/json")
                req.add_header("Accept", "audio/mpeg")
                resp = urllib.request.urlopen(req, timeout=60)
                audio = resp.read()
                if not audio or len(audio) < 200:
                    raise RuntimeError("ElevenLabs returned empty audio")
                tmp = fpath + ".tmp"
                with open(tmp, "wb") as f:
                    f.write(audio)
                os.replace(tmp, fpath)
                # تنظيف الملفات الأقدم من 6 ساعات
                try:
                    now = time.time()
                    for old in os.listdir(TTS_DIR):
                        p = os.path.join(TTS_DIR, old)
                        if os.path.isfile(p) and now - os.path.getmtime(p) > 6 * 3600:
                            os.remove(p)
                except Exception:
                    pass
            self._json({"ok": True, "url": "/arkan/tts/" + fname})
        except Exception as e:
            self._json({"error": "ElevenLabs: " + str(e)}, 502)

    # ---------- ElevenLabs: صوت → نص (تحويل الكلام إلى نص) ----------
    def _stt_api(self):
        """يستقبل ملف صوتي خام في جسم الطلب (Content-Type الأصلي مثل audio/webm)
        ويحوّله إلى نص عربي عبر ElevenLabs (scribe_v1)، ثم يعيد {"text": ...}.

        السبب: بعض المتصفحات على شبكة محلية (http وليس https) ترفض Web Speech API
        لأنه يحتاج "سياق آمن" — فهذا المسار بديل احتياطي يخدم من السيرفر.
        """
        ctype = self.headers.get("Content-Type", "").split(";")[0].strip().lower()
        if not ctype.startswith("audio/"):
            self._json({"error": "expected audio/* body"}, 415)
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
        except Exception:
            length = 0
        if length <= 0:
            self._json({"error": "no audio"}, 400)
            return
        if length > 10 * 1024 * 1024:
            self._json({"error": "audio too large"}, 413)
            return
        audio = self.rfile.read(length)
        if not audio:
            self._json({"error": "no audio"}, 400)
            return
        try:
            # ElevenLabs يحتاج ملفاً باسم لامتداد صحيح — نبني multipart يدوياً
            ext = {"audio/webm": "webm", "audio/ogg": "ogg", "audio/mpeg": "mp3",
                   "audio/mp3": "mp3", "audio/mp4": "mp4", "audio/wav": "wav",
                   "audio/x-wav": "wav", "audio/aac": "aac"}.get(ctype, "webm")
            boundary = "----arkanstt" + hashlib.md5(audio[:64] + str(time.time()).encode()).hexdigest()
            body = b"".join([
                ("--" + boundary + "\r\n").encode(),
                ('Content-Disposition: form-data; name="model_id"\r\n\r\n' + ELEVENLABS_STT_MODEL + "\r\n").encode(),
                ("--" + boundary + "\r\n").encode(),
                ('Content-Disposition: form-data; name="file"; filename="voice.' + ext + '"\r\n').encode(),
                ("Content-Type: " + ctype + "\r\n\r\n").encode(),
                audio,
                ("\r\n--" + boundary + "--\r\n").encode(),
            ])
            req = urllib.request.Request(ELEVENLABS_STT_URL, data=body, method="POST")
            req.add_header("xi-api-key", ELEVENLABS_API_KEY)
            req.add_header("Content-Type", "multipart/form-data; boundary=" + boundary)
            resp = urllib.request.urlopen(req, timeout=90)
            data = json.loads(resp.read().decode("utf-8") or "{}")
            text = (data.get("text") or "").strip()
            if not text:
                self._json({"error": "no speech detected"}, 422)
                return
            self._json({"ok": True, "text": text, "language_code": data.get("language_code") or ""})
        except Exception as e:
            self._json({"error": "STT: " + str(e)}, 502)

    # ---------- رفع ملف صوتي لملخص ركن (يقبل base64) ----------
    def _upload_audio_api(self):
        """يستقبل {cornerId, data: base64, ext: 'webm'|'mp3'|...} ويحفظه في arkan-ai/audio/."""
        import base64
        payload = self._read_payload()
        corner_id = (payload.get("cornerId") or "").strip()
        data_b64 = (payload.get("data") or "").strip()
        ext = (payload.get("ext") or "webm").strip().lower()
        if ext not in ("webm", "ogg", "mp3", "m4a", "wav"):
            ext = "webm"
        if not corner_id or not data_b64:
            self._json({"error": "cornerId and data required"}, 400)
            return
        try:
            # اسم آمن: corner-<id>.<ext>
            safe_id = "".join(c for c in corner_id if c.isalnum() or c in "-_")[:40]
            fname = "corner-" + safe_id + "." + ext
            fpath = os.path.join(BASE_DIR, "arkan-ai", "audio", fname)
            os.makedirs(os.path.dirname(fpath), exist_ok=True)
            # فك base64 (يدعم data:audio/webm;base64,...)
            if "," in data_b64:
                data_b64 = data_b64.split(",", 1)[1]
            audio_bytes = base64.b64decode(data_b64)
            if len(audio_bytes) < 100:
                self._json({"error": "audio too small"}, 400)
                return
            tmp = fpath + ".tmp"
            with open(tmp, "wb") as f:
                f.write(audio_bytes)
            os.replace(tmp, fpath)
            # حدّث data.json → audioSummary
            d = load_data()
            for c in d.get("corners", []):
                if c.get("id") == corner_id:
                    c["audioSummary"] = "/arkan/audio/" + fname
                    break
            d["savedAt"] = time.time()
            save_data(d)
            self._json({"ok": True, "url": "/arkan/audio/" + fname})
        except Exception as e:
            self._json({"error": "upload failed: " + str(e)}, 500)

    def _delete_audio_api(self):
        """يحذف ملف الصوت من ركن: {cornerId}."""
        payload = self._read_payload()
        corner_id = (payload.get("cornerId") or "").strip()
        if not corner_id:
            self._json({"error": "cornerId required"}, 400)
            return
        try:
            d = load_data()
            url = ""
            for c in d.get("corners", []):
                if c.get("id") == corner_id:
                    url = c.get("audioSummary") or ""
                    c["audioSummary"] = ""
                    break
            d["savedAt"] = time.time()
            save_data(d)
            # احذف الملف من القرص لو 存在
            if url:
                fname = url.rsplit("/", 1)[-1]
                fpath = os.path.join(BASE_DIR, "arkan-ai", "audio", fname)
                if os.path.exists(fpath):
                    os.remove(fpath)
            self._json({"ok": True})
        except Exception as e:
            self._json({"error": str(e)}, 500)

    # ---------- رفع ملف صوتي من الزوار (تسجيل مباشر) ----------
    def _upload_visitor_audio(self):
        """يستقبل {cornerId, data: base64, ext} ويحفظه في arkan-ai/audio/."""
        import base64
        payload = self._read_payload()
        corner_id = (payload.get("cornerId") or "").strip()
        data_b64 = (payload.get("data") or "").strip()
        ext = (payload.get("ext") or "webm").strip().lower()
        if ext not in ("webm", "ogg", "mp3", "m4a", "wav"):
            ext = "webm"
        if not corner_id or not data_b64:
            self._json({"error": "cornerId and data required"}, 400)
            return
        try:
            safe_id = "".join(c for c in corner_id if c.isalnum() or c in "-_")[:40]
            fname = "visitor-" + safe_id + "-" + str(int(time.time())) + "." + ext
            fpath = os.path.join(BASE_DIR, "arkan-ai", "audio", fname)
            os.makedirs(os.path.dirname(fpath), exist_ok=True)
            if "," in data_b64:
                data_b64 = data_b64.split(",", 1)[1]
            audio_bytes = base64.b64decode(data_b64)
            if len(audio_bytes) < 100:
                self._json({"error": "audio too small"}, 400)
                return
            if len(audio_bytes) > 10 * 1024 * 1024:  # 10MB max
                self._json({"error": "audio too large"}, 413)
                return
            tmp = fpath + ".tmp"
            with open(tmp, "wb") as f:
                f.write(audio_bytes)
            os.replace(tmp, fpath)
            # حدّث data.json → audioSummary
            d = load_data()
            for c in d.get("corners", []):
                if c.get("id") == corner_id:
                    c["audioSummary"] = "/arkan/audio/" + fname
                    break
            d["savedAt"] = time.time()
            save_data(d)
            self._json({"ok": True, "url": "/arkan/audio/" + fname})
        except Exception as e:
            self._json({"error": "upload failed: " + str(e)}, 500)

    # ---------- تمرير الطلبات إلى Ollama ----------
    def _proxy(self, body=None, method="GET"):
        # /api/chat → NVIDIA NIM API (سحابي سريع) مع fallback لـ Ollama المحلي
        if self.path == "/api/chat" and body:
            self._nvidia_chat(body)
            return
        req = urllib.request.Request(OLLAMA + self.path, data=body, method=method)
        req.add_header("Content-Type", "application/json")
        try:
            resp = urllib.request.urlopen(req, timeout=600)
            # دعم البث (streaming): Ollama يرسل أسطر NDJSON
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            try:
                while True:
                    line = resp.readline()
                    if not line:
                        break
                    self.wfile.write(line)
                    self.wfile.flush()
            except Exception:
                pass
            finally:
                resp.close()
        except Exception as e:
            # الخطأ يُرسل فقط إذا لم نبدأ الإرسال بعد
            try:
                err = json.dumps({"error": str(e)}).encode("utf-8")
                self.send_response(502)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(err)
            except Exception:
                pass

    def do_POST(self):
        if self.path.startswith("/api/"):
            # تحكم Ollama المحلي
            if self.path == "/api/ollama/start":
                self._ollama_control("start")
                return
            if self.path == "/api/ollama/stop":
                self._ollama_control("stop")
                return
            # ===== رفع ملف صوتي لملخص ركن =====
            if self.path == "/api/upload-audio":
                self._upload_audio_api()
                return
            # ===== حذف ملف صوتي من ركن =====
            if self.path == "/api/delete-audio":
                self._delete_audio_api()
                return
            # ===== رفع ملف صوتي من الزوار =====
            if self.path == "/api/upload-visitor-audio":
                self._upload_visitor_audio()
                return
            # ===== البيانات المشتركة (تعديلات الأدمن) =====
            if self.path == "/api/data":
                self._save_data_api()
                return
            # ===== نظام الدور (الطابور) =====
            if self.path == "/api/queue/join":
                self._queue_join_api()
                return
            if self.path == "/api/queue/status":
                self._queue_status_api()
                return
            if self.path == "/api/queue/release":
                self._queue_release_api()
                return
            if self.path == "/api/stats/bump":
                self._bump_api()
                return
            # ===== تسجيل اسم الزائر (مرة واحدة لكل زيارة) =====
            if self.path == "/api/stats/visitor":
                self._visitor_api()
                return
            # تصدير الإحصائيات (للأدمن) — يُعاد كنص CSV
            if self.path == "/api/stats/export":
                self._stats_export_api()
                return
            # حذف كل الإحصائيات (للأدمن)
            if self.path == "/api/stats/reset":
                self._stats_reset_api()
                return
            # ===== ElevenLabs: نص → صوت عربي =====
            if self.path == "/api/tts":
                self._tts_api()
                return
            # ===== تحويل الكلام إلى نص (بديل Web Speech الاحتياطي) =====
            if self.path == "/api/stt":
                self._stt_api()
                return
            length = int(self.headers.get("Content-Length", 0))
            self._proxy(body=self.rfile.read(length), method="POST")
            return
        self.send_error(404)

    # ---------- البيانات المشتركة ----------
    def _save_data_api(self):
        """يستقبل {corners:[...], about:{...}} من لوحة الإدارة ويحفظه."""
        try:
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            self._json({"error": "bad json"}, 400)
            return
        if not isinstance(payload, dict) or "corners" not in payload:
            self._json({"error": "invalid payload"}, 400)
            return
        cur = load_data()
        # الأحدث يفوز: لو النسخة المحلية أحدث من اللي على السيرفر لا نكتب فوقها
        inc = payload.get("savedAt") or 0
        cur_at = cur.get("savedAt") or 0
        if inc < cur_at and "corners" in cur:
            self._json({"ok": True, "skipped": "stale"})
            return
        cur["corners"] = payload["corners"]
        if "about" in payload:
            cur["about"] = payload["about"]
        cur["savedAt"] = inc or time.time()
        save_data(cur)
        self._json({"ok": True})

    def _bump_api(self):
        """يزيد عدّاد: {kind:'visit'|'question'|'corner', key, name, corner}"""
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            payload = json.loads(body) if body.strip() else {}
        except Exception:
            payload = {}
        kind = payload.get("kind", "")
        if kind == "visit":
            bump_stat("visit")
        elif kind == "question":
            bump_stat("question", payload.get("key"), payload.get("name"), payload.get("corner"))
        elif kind == "corner":
            bump_stat("corner", payload.get("corner"))
        self._json({"ok": True})

    def _visitor_api(self):
        """يسجّل اسم الزائر: {name} — يُضاف لقائمة الزوار مع وقت أول دخول."""
        payload = self._read_payload()
        name = (payload.get("name") or "").strip()
        if not name:
            self._json({"error": "empty name"}, 400)
            return
        try:
            name = name[:40]
            s = load_stats()
            s.setdefault("visitors", {})
            if name not in s["visitors"]:
                s["visitors"][name] = {"count": 0, "first": time.strftime("%Y-%m-%d %H:%M:%S"),
                                       "last": time.strftime("%Y-%m-%d %H:%M:%S")}
            v = s["visitors"][name]
            v["count"] = (v.get("count") or 0) + 1
            v["last"] = time.strftime("%Y-%m-%d %H:%M:%S")
            # تكافؤ مع النسخة القديمة: {name: number} → dict
            save_stats(s)
            self._json({"ok": True, "visitors": len(s["visitors"])})
        except Exception as e:
            self._json({"error": str(e)}, 500)

    def _stats_export_api(self):
        """يصدّر السجل التفصيلي كملف CSV (للأدمن)."""
        import io, csv
        s = load_stats()
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["الاسم", "السؤال", "الركن", "الوقت"])
        for row in (s.get("log") or []):
            w.writerow([row.get("name", ""), row.get("q", ""), row.get("corner", ""), row.get("at", "")])
        # زوار مسجّلون
        w.writerow([])
        w.writerow(["الزوار المسجّلون", "عدد الدخول", "أول دخول", "آخر دخول"])
        for nm, v in (s.get("visitors") or {}).items():
            if isinstance(v, dict):
                w.writerow([nm, v.get("count", ""), v.get("first", ""), v.get("last", "")])
            else:
                w.writerow([nm, v, "", ""])
        data = ("\ufeff" + buf.getvalue()).encode("utf-8")   # BOM حتى Excel يقرأ العربي
        self.send_response(200)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition",
                         "attachment; filename=stats-%s.csv" % time.strftime("%Y%m%d-%H%M"))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _stats_reset_api(self):
        """يمسح كل الإحصائيات (للأدمن فقط)."""
        self._json(reset_stats())

    # ---------- نظام الدور (الطابور) ----------
    def _read_payload(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            return json.loads(body) if body.strip() else {}
        except Exception:
            return {}

    def _client_key(self):
        """معرّف الجهاز: ترويسة X-Cybo-Id أولاً (الأدق)، ثم الكوكي، ثم الـIP."""
        hid = self.headers.get("X-Cybo-Id")
        if hid:
            return hid, None
        raw = self.headers.get("Cookie") or ""
        for part in raw.split(";"):
            part = part.strip()
            if part.startswith("cybo-id="):
                return part[len("cybo-id="):], None
        return "ip-" + self.client_address[0], "cybo-id=ip-%s; Path=/; Max-Age=86400" % self.client_address[0]

    def _json_cookie(self, obj, cookie=None, code=200):
        """يرسل JSON مع كوكيز اختياري — لازم يكون الترويسة قبل send_response."""
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(data)

    def _queue_join_api(self):
        cid, cookie = self._client_key()
        self._json_cookie(queue_join(cid), cookie)

    def _queue_status_api(self):
        cid, cookie = self._client_key()
        self._json_cookie(queue_status(cid), cookie)

    def _queue_release_api(self):
        cid, cookie = self._client_key()
        self._json_cookie(queue_release(cid), cookie)

    def _json(self, obj, code=200):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _ollama_control(self, action):
        # هذه الأوامر تعمل فقط من الجهاز المضيف
        client_ip = self.client_address[0]
        if client_ip not in ("127.0.0.1", "localhost", "::1"):
            self.send_response(403)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error": "host only"}')
            return
        import subprocess, time
        result = {"action": action}
        try:
            if action == "start":
                # تحقق أولاً: هل Ollama يعمل أصلاً؟
                already = False
                try:
                    r = urllib.request.urlopen("http://localhost:11434/api/version", timeout=3)
                    already = True
                except Exception:
                    already = False

                if not already:
                    # شغّل ollama serve في الخلفية وانتظر حتى يجهز
                    si = subprocess.STARTUPINFO()
                    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    subprocess.Popen(
                        ["ollama", "serve"],
                        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | 0x00000008,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        startupinfo=si
                    )
                    # انتظر حتى يصبح جاهزاً (حتى 20 ثانية)
                    for _ in range(20):
                        time.sleep(1)
                        try:
                            urllib.request.urlopen("http://localhost:11434/api/version", timeout=2)
                            break
                        except Exception:
                            pass
                result["ok"] = True
                result["already_running"] = already
            else:
                # إيقاف ollama serve وعمليات النموذج
                subprocess.run(["taskkill", "/F", "/IM", "ollama.exe"],
                               capture_output=True, timeout=10)
                subprocess.run(["taskkill", "/F", "/IM", "ollama app.exe"],
                               capture_output=True, timeout=10)
                subprocess.run(["taskkill", "/F", "/IM", "ollama_llama_server.exe"],
                               capture_output=True, timeout=10)
                result["ok"] = True
        except Exception as e:
            result["ok"] = False
            result["error"] = str(e)
        data = json.dumps(result).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(data)

    def _qrcode(self):
        """GET /api/qrcode?text=... → يرجع SVG باركود"""
        try:
            q = urllib.parse.urlparse(self.path).query
            text = urllib.parse.parse_qs(q).get("text", [""])[0]
            if not text:
                self.send_error(400, "text required")
                return
            if not HAS_QR:
                self.send_error(501, "segno not installed")
                return
            import io
            buf = io.BytesIO()
            segno.make(text, error="m").save(buf, kind="svg", scale=6, dark="#0b1733", light="#ffffff")
            svg = buf.getvalue()
            self.send_response(200)
            self.send_header("Content-Type", "image/svg+xml; charset=utf-8")
            self.send_header("Content-Length", str(len(svg)))
            self.send_header("Cache-Control", "public, max-age=3600")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(svg)
        except Exception as e:
            try:
                self.send_error(500, str(e))
            except Exception:
                pass

    def do_GET(self):
        if self.path.startswith("/api/"):
            # ===== باركود QR =====
            if self.path.startswith("/api/qrcode"):
                self._qrcode()
                return
            # ===== البيانات المشتركة والإحصائيات (قبل تمرير Ollama) =====
            if self.path == "/api/data":
                self._json(load_data())
                return
            if self.path == "/api/stats":
                self._json(load_stats())
                return
            # /api/tags يُعاد كما هو (JSON عادي) — لا يحتاج بث
            try:
                req = urllib.request.Request(OLLAMA + self.path, method="GET")
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = resp.read()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(data)
            except Exception as e:
                err = json.dumps({"error": str(e)}).encode("utf-8")
                self.send_response(502)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(err)
            return
        # فك ترميز المسار (العربي في الروابط يصل مُرمّزاً %XX)
        raw_path = urllib.parse.unquote(self.path.split("?")[0])
        # توجيه المسارات للمجلد الصحيح
        if raw_path == "/arkan" or raw_path == "/arkan/":
            raw_path = "/arkan/index.html"

        # ===== التحكم بالدخول =====
        client_ip = self.client_address[0]
        is_local = client_ip in ("127.0.0.1", "localhost", "::1")
        wants_arkan = raw_path.startswith("/arkan")

        if is_local:
            # الجهاز المضيف: كل شيء مسموح
            pass
        else:
            # زائر من الشبكة: مسموح فقط بـ /arkan
            if not wants_arkan:
                body = ("<!DOCTYPE html><html lang=ar dir=rtl><head><meta charset=utf-8>"
                        "<title>غير مسموح</title></head><body style=\"font-family:sans-serif;"
                        "background:#060d1f;color:#e8f0ff;display:grid;place-items:center;"
                        "height:100vh;text-align:center;margin:0\">"
                        "<div><h1 style=\"color:#ef4444\">⛔ الدخول غير مسموح</h1>"
                        "<p>هذا القسم خاص بالمضيف فقط.</p>"
                        "<p>اذهب إلى <a href=/arkan style=color:#22d3ee>اركان AI</a></p></div></body></html>")
                data = body.encode("utf-8")
                self.send_response(403)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return

        # ===== تسجيل الزيارة تلقائياً عند فتح اركان =====
        if wants_arkan and self.path.split("?")[0] in ("/arkan", "/arkan/", "/arkan/index.html"):
            bump_stat("visit")

        # تحديد المجلد الأساسي حسب المسار
        if wants_arkan:
            base = SITES["/arkan"]
            rel = raw_path[len("/arkan"):].lstrip("/")
            if not rel:
                rel = "index.html"
        else:
            base = SITES["/"]
            rel = raw_path.lstrip("/") or "index.html"
        full = os.path.normpath(os.path.join(base, rel))
        if not full.startswith(os.path.normpath(base)):
            self.send_error(403)
            return
        if os.path.isdir(full):
            full = os.path.join(full, "index.html")
        if not os.path.exists(full):
            self.send_error(404, "Not Found: " + rel)
            return
        # إرسال الملف مع النوع الصحيح
        ctype = self.guess_type(full)
        with open(full, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        pass  # صامت

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "localhost"

if __name__ == "__main__":
    socketserver.TCPServer.allow_reuse_address = True
    # ThreadingTCPServer: كل طلب في thread منفصل — حتى لا يجمّد السيرفر
    # طلب الشات الطويل بقية الطلبات (تحميل صفحات، فحص الحالة)
    class ThreadedServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
        daemon_threads = True
        allow_reuse_address = True

    with ThreadedServer(("0.0.0.0", PORT), Handler) as httpd:
        ip = get_local_ip()
        print("=" * 60)
        print("  سيرفر أمين — يعمل الآن")
        print("=" * 60)
        print()
        print("  على هذا الجهاز:")
        print("     الموقع الرئيسي : http://localhost:%d" % PORT)
        print("     اركان AI       : http://localhost:%d/arkan" % PORT)
        print()
        print("  على أجهزة نفس الشبكة (موبايل / لابتوب):")
        print("     الموقع الرئيسي : http://%s:%d" % (ip, PORT))
        print("     اركان AI       : http://%s:%d/arkan" % (ip, PORT))
        print()
        print("  وسيط Ollama : /api/* -> " + OLLAMA)
        print("  للإيقاف     : Ctrl+C")
        print("=" * 60)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nتم إيقاف السيرفر.")
