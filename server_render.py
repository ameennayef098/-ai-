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

def load_env():
    """يقرأ .env المحلي للمفاتيح (احتياط عند التشغيل اليدوي).
    على Render تُقرأ المفاتيح من Environment Variables مباشرة.
    ملف .env موجود في .gitignore — لا يُرفع أبداً إلى GitHub.
    ملاحظة: لا يمسح أي متغير موجود مسبقاً في البيئة (setdefault) ولا يكتب قيماً فارغة."""
    path = os.path.join(BASE_DIR, ".env")
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip()
                if k and v:
                    os.environ.setdefault(k, v)
    except Exception:
        pass

load_env()

SITE_DIR = BASE_DIR

# ===== NVIDIA NIM API =====
NVIDIA_API_KEY = os.environ.get("NVIDIA_API_KEY", "")
NVIDIA_MODEL = "nvidia/nemotron-3.5-bolt-e4b"   # الأسرع + عربي نقي (تم قياسه: 1.0-1.3s للرد كاملاً)
NVIDIA_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
NVIDIA_EXTRA = {"chat_template_kwargs": {"enable_thinking": False}}
# قائمة البدائل: لو الموديل الأساسي غير متاح على المفتاح (404) نجرب التالي تلقائياً
NVIDIA_FALLBACKS = [
    "nvidia/nemotron-3-ultra-550b-a55b",          # ردود أطول وأغنى (مصطلحات مثل Smishing/2FA)
    "nvidia/nemotron-3.5-lightning-30b-a3b",      # بديل سريع
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
    "openai/gpt-oss-20b",
]

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
            # يدعم صيغتين: {message, history} أو {messages}
            if "messages" in body:
                messages = body["messages"]
            else:
                msg = body.get("message", "")
                history = body.get("history", [])
                messages = [{"role": "system", "content": "أنت سايبو، مساعد ذكي للأمن السيبراني. أجب بالعربية وبشكل مختصر."}]
                for h in history[-5:]:
                    messages.append({"role": "user" if h.get("role") == "user" else "assistant", "content": h.get("content", "")})
                messages.append({"role": "user", "content": msg})
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            for chunk in self._nvidia_chat_stream(messages):
                data = chunk.encode("utf-8")
                self.wfile.write(("%X\r\n" % len(data)).encode() + data + b"\r\n")
                self.wfile.flush()
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
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

    def _nvidia_chat_stream(self, messages):
        """يرسل لـ NVIDIA NIM بـ streaming ويعيد NDJSON (Ollama format).
        يجرّب الموديل الأساسي ثم البدائل تلقائياً حتى يرد واحد منها."""
        if not NVIDIA_API_KEY:
            yield json.dumps({"message": {"content": "عذراً، الذكاء الاصطناعي غير مفعل."}}) + "\n"
            return
        try:
            used_model, resp = _nvidia_chat_impl(messages, stream=True)
            for line in resp:
                line = line.decode("utf-8").strip()
                if line.startswith("data: "):
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                        choices = obj.get("choices", [])
                        if not choices:
                            continue
                        delta = choices[0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            yield json.dumps({"message": {"content": content}}) + "\n"
                    except (json.JSONDecodeError, IndexError, KeyError):
                        pass
            resp.close()
        except Exception as e:
            yield json.dumps({"message": {"content": f"عذراً، حدث خطأ: {str(e)[:100]}"}}) + "\n"

    def _nvidia_chat(self, msg, history):
        """نسخة غير streaming (للتوافق مع الـ frontend القديم)"""
        messages = [{"role": "system", "content": "أنت سايبو، مساعد ذكي للأمن السيبراني. أجب بالعربية وبشكل مختصر."}]
        for h in history[-5:]:
            messages.append({"role": "user" if h.get("role") == "user" else "assistant", "content": h.get("content", "")})
        messages.append({"role": "user", "content": msg})
        try:
            used_model, resp = _nvidia_chat_impl(messages, stream=False)
            result = json.loads(resp.read())
            resp.close()
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

def _nvidia_models():
    """قائمة الموديلات بترتيب الأفضلية: الأساسي ثم البدائل (بدون تكرار)."""
    seen = []
    for mdl in [NVIDIA_MODEL] + list(NVIDIA_FALLBACKS):
        if mdl and mdl not in seen:
            seen.append(mdl)
    return seen


def _nvidia_chat_impl(messages, stream=True, temperature=None, top_p=None, max_tokens=None):
    """يرسل الرسائل لأول موديل متاح (الأساسي ثم البدائل).
    يعيد (اسم الموديل، كائن الا�اجابة)، أو يثير استثناءً لو فشلت كلها."""
    last_err = None
    for model in _nvidia_models():
        payload = {"model": model, "messages": messages, "stream": stream}
        if temperature is not None:
            payload["temperature"] = temperature
        if top_p is not None:
            payload["top_p"] = top_p
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        payload.update(NVIDIA_EXTRA)
        try:
            req = urllib.request.Request(NVIDIA_URL, data=json.dumps(payload).encode("utf-8"), method="POST")
            req.add_header("Authorization", "Bearer " + NVIDIA_API_KEY)
            req.add_header("Content-Type", "application/json")
            req.add_header("Accept", "text/event-stream")
            resp = urllib.request.urlopen(req, timeout=60)
            return model, resp
        except Exception as e:
            last_err = e
            continue
    raise RuntimeError("NVIDIA models failed: " + str(last_err))



class ThreadedServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

if __name__ == "__main__":
    os.makedirs(TTS_DIR, exist_ok=True)
    server = ThreadedServer(("0.0.0.0", PORT), Handler)
    print(f"سايبو يعمل على http://localhost:{PORT}")
    server.serve_forever()
