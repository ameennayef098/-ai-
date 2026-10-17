# ============================================================================
# سيرفر أمين — نسخة Render (مبسطة)
# ----------------------------------------------------------------------------
# يخدم موقع سايبو من المسار الجذري
# التشغيل:  python server.py     ثم افتح http://localhost:8080/
# ============================================================================
import http.server, socketserver, json, urllib.request, urllib.parse, os, threading, time, hashlib

try:
    import segno
    HAS_QR = True
except Exception:
    HAS_QR = False

PORT = int(os.environ.get("PORT", 8080))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SITE_DIR = BASE_DIR

# ===== NVIDIA NIM API =====
NVIDIA_API_KEY = os.environ.get("NVIDIA_API_KEY", "")
NVIDIA_MODEL = "nvidia/nemotron-3-super-120b-a12b"
NVIDIA_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
NVIDIA_EXTRA = {"chat_template_kwargs": {"enable_thinking": False}}

# ===== ElevenLabs API =====
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE = "JBFqnCBsd6RMkjVDRZzb"
ELEVENLABS_VOICE_FRAUD = "pNInz6obpgDQGcFmaJgB"
ELEVENLABS_MODEL = "eleven_multilingual_v2"
ELEVENLABS_URL = "https://api.elevenlabs.io/v1/text-to-speech/" + ELEVENLABS_VOICE
ELEVENLABS_URL_FRAUD = "https://api.elevenlabs.io/v1/text-to-speech/" + ELEVENLABS_VOICE_FRAUD
ELEVENLABS_STT_MODEL = "scribe_v1"
ELEVENLABS_STT_URL = "https://api.elevenlabs.io/v1/speech-to-text"
TTS_DIR = os.path.join(BASE_DIR, "tts")
DATA_FILE = os.path.join(BASE_DIR, "data.json")
STATS_FILE = os.path.join(BASE_DIR, "stats.json")

DEFAULT_DATA = {
    "corners": [
        {"id": "observatory", "title": "ركن مرصد التهديدات السيبرانية", "authors": ["الأمين نايف دواغره", "عمر السيد خليل", "فهد العتيبي"], "short": "منصة توعية تفاعلية عن الأمن السيبراني، تعمل بالكامل محلياً بدون إنترنت.", "full": "مرصد التهديدات السيبراني — موقع تعليمي تفاعلي لنشر الوعي بالأمن السيبراني.", "img": "/posters/poster-policy.png", "code": "مرصد"},
        {"id": "data-classification", "title": "ركن تصنيف البيانات", "authors": ["موسى عيدان الزهراني", "يزيد ظافر القرني"], "short": "كيفية تصنيف البيانات ومفهوم التصنيف وأهدافه الخمسة.", "full": "ركن تصنيف البيانات يعلم الزوار أهمية تصنيف البيانات وكيفية حمايتها.", "img": "/posters/poster-data.png", "code": "بيانات"},
        {"id": "threats", "title": "ركن التهديدات السيبرانية", "authors": ["فيصل عبدالرحمن", "حمد القحطاني"], "short": "تجربة حية تُظهر خطر الشبكات المفتوحة وكيف تُسرق بياناتك.", "full": "ركن التهديدات السيبرانية يعرض أحدث التهديدات وطرق الحماية منها.", "img": "/posters/poster-threats.png", "code": "تهديدات"},
        {"id": "calls", "title": "ركن مكالمات الاحتيال", "authors": ["بدر كريري", "عبد العزيز السرحاني"], "short": "عرض تقديمي ومحاكاة تفاعلية لمكالمة احتيال — اختر ردك وشاهد ردّة فعل المحتال.", "full": "ركن مكالمات الاحتيال يعلم الزوار كيفية التعرف على المكالمات المشبوهة.", "img": "/posters/poster-calls.png", "code": "مكالمات"},
        {"id": "sms", "title": "ركن رسائل الاحتيال النصية", "authors": ["ياسر عثمان الصومالي", "عبدالعزيز فواز الرميزان"], "short": "عرض تقديمي ثم تجربة لمحاولة اختراق عبر الرسائل النصية، مع اختبار خفيف في النهاية.", "full": "ركن رسائل الاحتيال النصية يعلم الزوار كيفية التعرف على الرسائل المشبوهة.", "img": "/posters/poster-sms.png", "code": "رسائل"},
        {"id": "c6", "title": "ركن أمان الأجهزة الذكية", "authors": [], "short": "قيد الإعداد.", "full": "", "pending": True, "img": "/posters/poster-devices.png", "code": ""}
    ],
    "about": "سايبو — موقع تفاعلي للأمن السيبراني",
    "savedAt": 1791999056442
}

def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return DEFAULT_DATA

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_stats():
    if os.path.exists(STATS_FILE):
        try:
            with open(STATS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {"visitors": 0, "questions": 0}

def save_stats(stats):
    with open(STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

def bump_stat(key):
    stats = load_stats()
    stats[key] = stats.get(key, 0) + 1
    save_stats(stats)

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=SITE_DIR, **kwargs)

    def log_message(self, format, *args):
        pass

    def _json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/api/"):
            self._handle_api()
            return
        super().do_GET()

    def do_POST(self):
        if self.path.startswith("/api/"):
            self._handle_api()
            return
        self.send_error(404)

    def _handle_api(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/api/data":
            self._json(load_data())
            return

        if path == "/api/tags":
            self._json({"models": []})
            return

        if path == "/api/stats":
            self._json(load_stats())
            return

        if path == "/api/stats/bump":
            bump_stat("visit")
            self._json({"ok": True})
            return

        if path == "/api/chat":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            msg = body.get("message", "")
            history = body.get("history", [])
            reply = self._nvidia_chat(msg, history)
            self._json({"reply": reply})
            return

        if path == "/api/tts":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            text = body.get("text", "")
            voice = body.get("voice", "cybo")
            audio_url = self._tts(text, voice)
            self._json({"url": audio_url})
            return

        if path == "/api/stt":
            length = int(self.headers.get("Content-Length", 0))
            audio_data = self.rfile.read(length)
            text = self._stt(audio_data)
            self._json({"text": text})
            return

        if path == "/api/qrcode" and HAS_QR:
            params = urllib.parse.parse_qs(parsed.query)
            text = params.get("text", [""])[0]
            import io
            buf = io.BytesIO()
            segno.make(text).save(buf, kind="svg", scale=5)
            buf.seek(0)
            self.send_response(200)
            self.send_header("Content-Type", "image/svg+xml")
            self.end_headers()
            self.wfile.write(buf.read())
            return

        self._json({"error": "not found"}, 404)

    def _nvidia_chat(self, msg, history):
        if not NVIDIA_API_KEY:
            return "عذراً، الذكاء الاصطناعي غير مفعل."
        messages = [{"role": "system", "content": "أنت سايبو، مساعد ذكي للأمن السيبراني. أجب بالعربية وبشكل مختصر."}]
        for h in history[-5:]:
            messages.append({"role": "user" if h.get("role") == "user" else "assistant", "content": h.get("content", "")})
        messages.append({"role": "user", "content": msg})
        payload = {"model": NVIDIA_MODEL, "messages": messages, **NVIDIA_EXTRA}
        req = urllib.request.Request(NVIDIA_URL, data=json.dumps(payload).encode("utf-8"), method="POST")
        req.add_header("Authorization", "Bearer " + NVIDIA_API_KEY)
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read())
                return result["choices"][0]["message"]["content"]
        except Exception as e:
            return f"عذراً، حدث خطأ: {str(e)[:100]}"

    def _tts(self, text, voice):
        if not ELEVENLABS_API_KEY:
            return ""
        voice_id = ELEVENLABS_VOICE if voice == "cybo" else ELEVENLABS_VOICE_FRAUD
        url = ELEVENLABS_URL if voice == "cybo" else ELEVENLABS_URL_FRAUD
        payload = {"text": text, "model_id": ELEVENLABS_MODEL}
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), method="POST")
        req.add_header("xi-api-key", ELEVENLABS_API_KEY)
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "audio/mpeg")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                audio = resp.read()
            fname = hashlib.md5((text + voice).encode()).hexdigest() + ".mp3"
            os.makedirs(TTS_DIR, exist_ok=True)
            with open(os.path.join(TTS_DIR, fname), "wb") as f:
                f.write(audio)
            return "/tts/" + fname
        except:
            return ""

    def _stt(self, audio_data):
        if not ELEVENLABS_API_KEY:
            return ""
        boundary = "----WebKitFormBoundary" + hashlib.md5(str(time.time()).encode()).hexdigest()
        body = b"--" + boundary.encode() + b"\r\n"
        body += b'Content-Disposition: form-data; name="file"; filename="audio.webm"\r\n'
        body += b"Content-Type: audio/webm\r\n\r\n"
        body += audio_data + b"\r\n"
        body += b"--" + boundary.encode() + b"\r\n"
        body += b'Content-Disposition: form-data; name="model_id"\r\n\r\n'
        body += ELEVENLABS_STT_MODEL.encode() + b"\r\n"
        body += b"--" + boundary.encode() + b"--\r\n"
        req = urllib.request.Request(ELEVENLABS_STT_URL, data=body, method="POST")
        req.add_header("xi-api-key", ELEVENLABS_API_KEY)
        req.add_header("Content-Type", "multipart/form-data; boundary=" + boundary)
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                result = json.loads(resp.read())
                return result.get("text", "")
        except:
            return ""

class ThreadedServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

if __name__ == "__main__":
    os.makedirs(TTS_DIR, exist_ok=True)
    server = ThreadedServer(("0.0.0.0", PORT), Handler)
    print(f"سايبو يعمل على http://localhost:{PORT}")
    server.serve_forever()
