import os
from dotenv import load_dotenv

# === Load Environment Variables ===
if not os.path.exists(".env"):
    print("⚠️ File .env tidak ditemukan. Silakan salin '.env.example' menjadi '.env' dan isi token Anda sebelum menjalankan bot.")
    exit(1)

load_dotenv()  # Memuat variabel dari file .env

import telebot
import re
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from telebot.apihelper import ApiTelegramException
import requests
import json
import os

# --- PENGATURAN UTAMA ---
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
OPENROUTER_API_KEY = os.environ.get('OPENROUTER_API_KEY')
BLACKBOX_API_KEY = os.environ.get('BLACKBOX_API_KEY')
OPENROUTER_WORKER_URL = "https://proxy-openrouter.menieemoon.workers.dev"
BLACKBOX_WORKER_URL = "https://proxy-blackbox.menieemoon.workers.dev"
WORKER_SAVE_URL = "https://ai-response-handler.menieemoon.workers.dev/save_response"

HISTORY_LIMIT = 7
MAX_TOKENS = 9000
TELEGRAM_MAX_MESSAGE_LENGTH = 4075

AI_MODELS = [
    {'id': 'x-ai/grok-4-fast:free', 'name': 'Grok 4 Fast', 'provider': 'openrouter'},
    {'id': 'blackboxai/openai/gpt-4.1-nano', 'name': 'GPT-4.1 Nano', 'provider': 'blackbox'},
    {'id': 'blackboxai/openai/gpt-4o-mini', 'name': 'GPT-4o', 'provider': 'blackbox'},
    {'id': 'blackboxai/x-ai/grok-3-mini', 'name': 'Grok 3 M', 'provider': 'blackbox'},
    {'id': 'blackboxai/deepseek/deepseek-r1-0528-qwen3-8b', 'name': 'DeepSeek R1 0528', 'provider': 'blackbox'},
    {'id': 'blackboxai/google/gemini-2.5-flash-lite-preview-06-17', 'name': 'Gemini 2.5 Flash Pre', 'provider': 'blackbox'},
    {'id': 'blackboxai/agentica-org/deepcoder-14b-preview:free', 'name': 'DeepCoder', 'provider': 'blackbox'},
]

# Prompt dasar untuk AI utama
SYSTEM_PROMPT = """
Anda adalah asisten AI yang ramah dan sangat membantu. Selalu berkomunikasi dalam Bahasa Indonesia.
Gunakan format HTML yang didukung Telegram untuk membuat jawaban Anda mudah dibaca.
Tag yang DIIZINKAN HANYA: <b>, <i>, <u>, <s>, <a>, <code>, dan <pre>.
- Untuk tebal, gunakan <b>...</b>.
- Untuk blok kode, gunakan <pre><code>...</code></pre>.
PERINGATAN KERAS: JANGAN PERNAH menggunakan tag HTML lain seperti <ul>, <ol>, <li>, <div>, <p>, <br>, <h1>, <h2>, atau simbol Markdown seperti ```, ** . Pastikan semua konten hanya menggunakan tag yang diizinkan.
"""

# Prompt untuk AI filter (khusus fallback)
FILTER_PROMPT = """
Anda adalah filter HTML untuk Telegram. Ubah teks apa pun (termasuk HTML salah atau Markdown) menjadi HTML yang bersih dan valid untuk Telegram. Gunakan HANYA tag yang didukung: <b> untuk tebal, <i> untuk miring, <code> untuk kode inline, <pre> untuk blok kode dan daftar, <a href=\"URL\"> untuk tautan, dan <blockquote expandable> untuk kutipan. Untuk header, gunakan <b>; untuk daftar, gunakan <pre> dengan tanda daftar (misalnya, - atau *); untuk kode inline, gunakan <code>; untuk blok kode, gunakan <pre> dengan konten penuh. JANGAN sertakan tag seperti <ul>, <ol>, <li>, <div>, <p>, <br>, <h1>, <h2>, atau blok kode wrapping (misalnya, ```html). Contoh: *teks* menjadi <i>teks</i>, ```kode``` menjadi <pre>kode</pre>. SELALU hapus Markdown (```), dan JANGAN berikan komentar tambahan, hanya berikan apa yang kamu terima.
"""

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
chat_history = {}
current_model = {}

def create_model_menu():
    markup = InlineKeyboardMarkup(row_width=1)
    for model in AI_MODELS:
        button = InlineKeyboardButton(f"{model['name']}", callback_data=f"model:{model['id']}")
        markup.add(button)
    markup.add(InlineKeyboardButton("❌ Batal", callback_data="cancel"))
    return markup

def create_link_button(url: str):
    """Buat tombol interaktif untuk link Worker."""
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🔗 Lihat Jawaban Lengkap", url=url))
    return markup

def upload_to_worker(content: str, message_id: int, user_id: int, chat_id: int):
    """Upload jawaban ke Worker dan kirim sebagai dokumen."""
    try:
        unique_id = f"{user_id}_{message_id}"
        payload = json.dumps({"content": content, "id": unique_id})
        response = requests.post(
            WORKER_SAVE_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        response.raise_for_status()
        data = response.json()
        url = data.get("url")
        print(f"📦 Worker upload success for user_id: {user_id} (chat_id: {chat_id}): URL={url}")

        file_name = f"{unique_id}.txt"
        with open(file_name, 'w', encoding='utf-8') as f:
            f.write(content)
        with open(file_name, 'rb') as f:
            bot.send_document(chat_id, f, caption=f"Jawaban AI sebagai cadangan (ID: {unique_id})")
        os.remove(file_name)

        return url
    except Exception as e:
        print(f"❌ Worker upload failed for user_id: {user_id} (chat_id: {chat_id}): {e}")
        return None

def get_ai_response(chat_id, user_message, model_id, history, user_identifier, is_filter=False):
    model_info = next((m for m in AI_MODELS if m['id'] == model_id), None)
    if not model_info:
        return None, "model_not_found"

    provider = model_info.get('provider')
    if provider == 'openrouter':
        url = f"{OPENROUTER_WORKER_URL.rstrip('/')}/chat/completions"
        api_key = OPENROUTER_API_KEY
    elif provider == 'blackbox':
        url = f"{BLACKBOX_WORKER_URL.rstrip('/')}/chat/completions"
        api_key = BLACKBOX_API_KEY
    else:
        return None, "provider_not_configured"

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    messages = [{"role": "system", "content": FILTER_PROMPT if is_filter else SYSTEM_PROMPT}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_message})
    
    payload = {"model": model_id, "messages": messages, "max_tokens": MAX_TOKENS}
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=60)
        response.raise_for_status()
        data = response.json()
        ai_message_obj = data['choices'][0]['message']
        total_tokens = data.get('usage', {}).get('total_tokens', 0)
        print(f"💬 Chat from {user_identifier} (chat_id: {chat_id}): Model {model_id} - Tokens: {total_tokens}")
        return ai_message_obj, total_tokens
    except requests.exceptions.RequestException as e:
        print(f"🚨 EXCEPTION for {user_identifier} (chat_id: {chat_id}): {e}")
        if e.response and e.response.status_code == 429:
            return None, "limit"
        return None, "connection_error"
    except (KeyError, IndexError):
        return None, "parsing_error"

def send_with_fallback(chat_id, main_content, reply_to_message_id, user_identifier, message, original_content):
    """Kirim jawaban dengan fallback ke worker jika gagal."""
    # Dapatkan nama model untuk footer
    model_id = current_model.get(chat_id, AI_MODELS[0]['id'])
    model_name = next((m['name'] for m in AI_MODELS if m['id'] == model_id), 'Unknown')
    footer = f"\n\n---\n<i>Model: {model_name}</i>"

    # Langkah 1: Periksa panjang karakter
    if len(main_content) > TELEGRAM_MAX_MESSAGE_LENGTH:
        print(f"Debug: Length exceeds {TELEGRAM_MAX_MESSAGE_LENGTH}, uploading to Worker")
        url = upload_to_worker(original_content, reply_to_message_id, message.from_user.id, chat_id)
        if url:
            print(f"🔗 URL generated: {url}")
            bot.reply_to(message, "Jawaban terlalu panjang. Klik di bawah untuk melihat." + footer, reply_markup=create_link_button(url), parse_mode='HTML')
            return True
        else:
            bot.reply_to(message, "Maaf, gagal mengunggah jawaban ke server." + footer, parse_mode='HTML')
            return False

    # Langkah 2: Periksa keberadaan Markdown atau tag HTML tidak valid
    if "```" in main_content or "<ul" in main_content.lower() or "<ol" in main_content.lower() or "<li" in main_content.lower() or "<div" in main_content.lower() or "<p" in main_content.lower():
        print(f"Debug: Detected invalid HTML or Markdown, applying AI filter")
        filter_model = 'blackboxai/google/gemini-2.5-flash-lite-preview-06-17'
        filtered_response, _ = get_ai_response(chat_id, main_content, filter_model, [], user_identifier, is_filter=True)
        if filtered_response:
            final_text = filtered_response.get('content', '') + footer
            print(f"Debug: Filter AI succeeded, sending: {final_text}")
            try:
                bot.send_message(chat_id, final_text, parse_mode='HTML', reply_to_message_id=reply_to_message_id)
                print(f"✅ [{user_identifier}] SUCCESS: Pesan terkirim setelah filter AI")
                return True
            except ApiTelegramException as e:
                print(f"⚠️ [{user_identifier}] GAGAL setelah filter AI: {e}")
                url = upload_to_worker(original_content, reply_to_message_id, message.from_user.id, chat_id)
                if url:
                    print(f"🔗 URL generated: {url}")
                    bot.reply_to(message, "Jawaban tidak dapat difilter. Klik di bawah untuk melihat." + footer, reply_markup=create_link_button(url), parse_mode='HTML')
                    return True
                else:
                    bot.reply_to(message, "Maaf, gagal mengunggah jawaban ke server." + footer, parse_mode='HTML')
                    return False
        else:
            print(f"Debug: Filter AI failed, uploading to Worker")
            url = upload_to_worker(original_content, reply_to_message_id, message.from_user.id, chat_id)
            if url:
                print(f"🔗 URL generated: {url}")
                bot.reply_to(message, "Jawaban tidak dapat difilter. Klik di bawah untuk melihat." + footer, reply_markup=create_link_button(url), parse_mode='HTML')
                return True
            else:
                bot.reply_to(message, "Maaf, gagal mengunggah jawaban ke server." + footer, parse_mode='HTML')
                return False

    # Langkah 3: Filter baru - Konversi **
    final_text = main_content
    if "**" in main_content:
        print(f"Debug: Detected **, converting to <b>")
        final_text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', main_content)
        print(f"Debug: Text after ** conversion: {final_text}")

    # Tambahkan footer
    final_text += footer

    # Langkah 4: Pengiriman langsung
    try:
        print(f"Debug: Attempting direct send: {final_text}")
        bot.send_message(chat_id, final_text, parse_mode='HTML', reply_to_message_id=reply_to_message_id)
        print(f"✅ [{user_identifier}] SUCCESS: Pesan terkirim dengan HTML asli")
        return True
    except ApiTelegramException as e:
        print(f"⚠️ [{user_identifier}] GAGAL Percobaan 1: {e}")
        print(f"Debug: Direct send failed, applying AI filter")
        filter_model = 'blackboxai/google/gemini-2.5-flash-lite-preview-06-17'
        filtered_response, _ = get_ai_response(chat_id, main_content, filter_model, [], user_identifier, is_filter=True)
        if filtered_response:
            final_text = filtered_response.get('content', '') + footer
            print(f"Debug: Filter AI succeeded, sending: {final_text}")
            try:
                bot.send_message(chat_id, final_text, parse_mode='HTML', reply_to_message_id=reply_to_message_id)
                print(f"✅ [{user_identifier}] SUCCESS: Pesan terkirim setelah filter AI")
                return True
            except ApiTelegramException as e:
                print(f"⚠️ [{user_identifier}] GAGAL setelah filter AI: {e}")
                url = upload_to_worker(original_content, reply_to_message_id, message.from_user.id, chat_id)
                if url:
                    print(f"🔗 URL generated: {url}")
                    bot.reply_to(message, "Jawaban tidak dapat difilter. Klik di bawah untuk melihat." + footer, reply_markup=create_link_button(url), parse_mode='HTML')
                    return True
                else:
                    bot.reply_to(message, "Maaf, gagal mengunggah jawaban ke server." + footer, parse_mode='HTML')
                    return False
        else:
            print(f"Debug: Filter AI failed, uploading to Worker")
            url = upload_to_worker(original_content, reply_to_message_id, message.from_user.id, chat_id)
            if url:
                print(f"🔗 URL generated: {url}")
                bot.reply_to(message, "Jawaban tidak dapat difilter. Klik di bawah untuk melihat." + footer, reply_markup=create_link_button(url), parse_mode='HTML')
                return True
            else:
                bot.reply_to(message, "Maaf, gagal mengunggah jawaban ke server." + footer, parse_mode='HTML')
                return False

@bot.message_handler(commands=['start'])
def start_handler(message):
    chat_id = message.chat.id
    chat_history[chat_id] = []
    current_model[chat_id] = AI_MODELS[0]['id']
    welcome_text = f"Hai {message.from_user.first_name}! Pilih model AI untuk memulai."
    bot.send_message(message.chat.id, welcome_text, reply_markup=create_model_menu())

@bot.message_handler(commands=['info'])
def info_handler(message):
    chat_id = message.chat.id
    model_name = next((m['name'] for m in AI_MODELS if m['id'] == current_model.get(chat_id)), 'Tidak diset')
    info_text = f"""<b>🤖 Info Bot</b>
- <b>Model Aktif:</b> <code>{model_name}</code>
- <b>Riwayat:</b> {HISTORY_LIMIT} pesan terakhir digunakan sebagai konteks.
- <b>Perintah:</b>
  <code>/start</code> - Memulai & pilih model
  <code>/info</code> - Menampilkan info ini
  <code>/switch</code> - Ganti model
  <code>/clear</code> - Membersihkan riwayat
"""
    bot.send_message(message.chat.id, info_text, parse_mode='HTML')

@bot.message_handler(commands=['switch'])
def switch_handler(message):
    switch_text = "Silakan pilih model AI yang baru.\n\n⚠️ <b>Peringatan</b>: Mengganti model akan mereset riwayat."
    bot.send_message(message.chat.id, switch_text, reply_markup=create_model_menu(), parse_mode="HTML")

@bot.message_handler(commands=['clear'])
def clear_handler(message):
    chat_id = message.chat.id
    chat_history[chat_id] = []
    bot.send_message(message.chat.id, "✅ Riwayat percakapan telah dibersihkan.")

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    bot.answer_callback_query(call.id)
    chat_id = call.message.chat.id
    data = call.data
    if data == "cancel":
        bot.delete_message(chat_id, call.message.message_id)
        return
    if data.startswith("model:"):
        model_id = data.split(":", 1)[1]
        current_model[chat_id] = model_id
        chat_history[chat_id] = []
        model_name = next((m['name'] for m in AI_MODELS if m['id'] == model_id), model_id)
        bot.edit_message_text(f"✅ Model diganti ke <b>{model_name}</b>.\nRiwayat direset. Silakan mulai topik baru.", chat_id, call.message.message_id, parse_mode='HTML')

@bot.message_handler(func=lambda message: message.text.startswith('/'))
def handle_unknown_command(message):
    bot.send_message(message.chat.id, "Perintah tidak dikenali. Gunakan /info untuk bantuan.")

@bot.message_handler(func=lambda message: True)
def message_handler(message):
    chat_id = message.chat.id
    message_id = message.message_id
    user_id = message.from_user.id
    user_text = message.text
    user_identifier = message.from_user.username or message.from_user.first_name

    if chat_id not in chat_history:
        chat_history[chat_id] = []
    if chat_id not in current_model:
        current_model[chat_id] = AI_MODELS[0]['id']

    # Kirim pesan menunggu segera
    waiting_msg = bot.send_message(chat_id, "<i>Sedang diproses...</i>", parse_mode='HTML')

    try:
        model_id = current_model[chat_id]
        history_context = chat_history[chat_id][-(HISTORY_LIMIT * 2):]
        ai_message_obj, result = get_ai_response(chat_id, user_text, model_id, history_context, user_identifier)

        if ai_message_obj:
            main_content = ai_message_obj.get('content', '')
            success = send_with_fallback(chat_id, main_content, message_id, user_identifier, message, main_content)
            bot.delete_message(chat_id, waiting_msg.message_id)  # Hapus pesan menunggu setelah jawaban siap
            if success:
                chat_history[chat_id].append({'role': 'user', 'content': user_text})
                chat_history[chat_id].append({'role': 'assistant', 'content': main_content})
        else:
            error_messages = {
                "model_not_found": "Model AI tidak ditemukan.",
                "provider_not_configured": "Provider AI tidak dikonfigurasi.",
                "limit": "Silahkan ganti Model AI.",
                "connection_error": "Gagal terhubung ke server AI.",
                "parsing_error": "Gagal memproses respons dari server AI.",
                "server_error": "Server AI bermasalah."
            }
            bot.delete_message(chat_id, waiting_msg.message_id)
            bot.reply_to(message, f"Maaf, terjadi masalah: {error_messages.get(result, 'Tidak diketahui')}. Silakan coba lagi atau hubungi owner.", parse_mode='HTML')
    except Exception as e:
        print(f"🚨 EXCEPTION in message_handler for {user_identifier} (chat_id: {chat_id}): {e}")
        bot.delete_message(chat_id, waiting_msg.message_id)
        bot.reply_to(message, "Maaf, terjadi kesalahan tak terduga. Silakan coba lagi atau hubungi owner.", parse_mode='HTML')

if __name__ == "__main__":
    print("🤖 Bot DUAL API (PythonAnywhere + CF Worker) mulai berjalan...")
    print("🎯 Strategi Fallback: Filter Panjang → Filter Markdown/Tag Tidak Valid (AI Filter) → HTML Asli → Filter AI → Worker")
    bot.polling(none_stop=True)
