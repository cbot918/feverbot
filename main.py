import os
import threading
from functools import wraps
from typing import Optional
from flask import Flask, Blueprint, request, abort, jsonify, Response
from flask_cors import CORS
from dotenv import load_dotenv
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    ReplyMessageRequest,
    PushMessageRequest,
    TextMessage,
    FlexMessage,
    FlexBubble,
    FlexBox,
    FlexText,
    FlexButton,
    FlexBubbleStyles,
    FlexBlockStyle,
    MessageAction,
)
from linebot.v3.webhooks import MemberJoinedEvent, MessageEvent, TextMessageContent
import admin_config
import fever_bot

# 讀取環境變數 .env 內的值
load_dotenv()

LINE_CHANNEL_ACCESS_TOKEN=os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
LINE_CHANNEL_SECRET = os.environ["LINE_CHANNEL_SECRET"]

configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)


app = Flask(__name__)

# CORS only for the admin API — LINE callback stays untouched.
CORS(
    app,
    resources={r"/admin/api/*": {"origins": os.environ.get("ADMIN_CORS_ORIGIN", "http://localhost:5173")}},
    supports_credentials=True,
)

# Icebreaker style: A / B / C (set in .env as ICEBREAKER_STYLE)
# 破冰預設 A模式
STYLE = os.environ.get("ICEBREAKER_STYLE", "A").upper()

# ── Icebreaker button → text responses ───────────────────────────────────────
BUTTON_RESPONSES = {
    # Style A
    "🛒 我賣什麼": (
        "跟大家分享你目前在賣什麼產品或服務吧 👀\n"
        "（一句話就好，老師會幫你拆銷售切入點）"
    ),
    "🏆 驕傲的一筆成交": (
        "Share 最近最有成就感的成交故事 🎉\n"
        "金額大小不重要，能成交都是本事！"
    ),
    "🚀 最想學的銷售絕招": (
        "最想突破哪個環節？\n"
        "開發 / 建立信任 / 處理拒絕 / 追單 / 定價？\n"
        "告訴我們，老師會優先排這個主題～"
    ),
    # Style B
    "🎯 顧問型": (
        "顧問型 🎯\n"
        "擅長傾聽、診斷需求，最強在「讓客戶覺得被理解」。\n"
        "進階方向：練提問框架，把痛點問深一層。"
    ),
    "⚡ 戰士型": (
        "戰士型 ⚡\n"
        "敢開口、敢推進，最強在「不怕被拒絕」。\n"
        "進階方向：學會踩煞車，先建立信任再推坑。"
    ),
    "🤝 朋友型": (
        "朋友型 🤝\n"
        "親和力滿分，最強在「長線經營」。\n"
        "進階方向：練 ask for sale，別怕讓朋友變客戶。"
    ),
    # Style C
    "📍 你在哪裡": (
        "目前在哪個城市呀？📍\n"
        "搞不好群裡有同城夥伴可以面交（咳，面對面交流）"
    ),
    "🍽️ 今天吃什麼": "今天吃了什麼？🍽️ 配張圖更香",
    "😊 不為人知的興趣": "Share 一個朋友都不知道的興趣 😏 保證不告訴你朋友",
}

# ── Flex card helpers ─────────────────────────────────────────────────────────
def _make_bubble(header_color: str, header_text: str, body_text: str, buttons: list) -> FlexBubble:
    return FlexBubble(
        styles=FlexBubbleStyles(header=FlexBlockStyle(background_color=header_color)),
        header=FlexBox(
            layout="vertical",
            contents=[FlexText(text=header_text, weight="bold", size="xl", color="#ffffff")],
        ),
        body=FlexBox(
            layout="vertical",
            spacing="md",
            contents=[FlexText(text=body_text, wrap=True, size="md")],
        ),
        footer=FlexBox(layout="vertical", spacing="sm", contents=buttons),
    )

def build_card_a(display_name: str) -> FlexMessage:
    buttons = [
        FlexButton(action=MessageAction(label="🛒 我賣什麼", text="🛒 我賣什麼"), style="primary", color="#06C755"),
        FlexButton(action=MessageAction(label="🏆 驕傲的一筆成交", text="🏆 驕傲的一筆成交"), style="secondary"),
        FlexButton(action=MessageAction(label="🚀 最想學的銷售絕招", text="🚀 最想學的銷售絕招"), style="secondary"),
    ]
    bubble = _make_bubble(
        "#06C755", "🎯 歡迎新銷售夥伴！",
        f"嗨 {display_name}！👋\n\n在這個群組，我們一起練銷售、拆案例。\n先讓大家認識你 ✨\n請任選一題開場：",
        buttons,
    )
    return FlexMessage(alt_text=f"歡迎 {display_name} 加入！請選一題破冰 🎯", contents=bubble)

def build_card_b(display_name: str) -> FlexMessage:
    buttons = [
        FlexButton(action=MessageAction(label="🎯 顧問型", text="🎯 顧問型"), style="primary", color="#8B5CF6"),
        FlexButton(action=MessageAction(label="⚡ 戰士型", text="⚡ 戰士型"), style="secondary"),
        FlexButton(action=MessageAction(label="🤝 朋友型", text="🤝 朋友型"), style="secondary"),
    ]
    bubble = _make_bubble(
        "#8B5CF6", "🧬 你是哪一型銷售？",
        f"歡迎 {display_name}！\n30 秒快測，看你天生屬於哪一型 ⤵",
        buttons,
    )
    return FlexMessage(alt_text=f"歡迎 {display_name}！快測你的銷售人格 🧬", contents=bubble)

def build_card_c(display_name: str) -> FlexMessage:
    buttons = [
        FlexButton(action=MessageAction(label="📍 你在哪裡", text="📍 你在哪裡"), style="primary", color="#F59E0B"),
        FlexButton(action=MessageAction(label="🍽️ 今天吃什麼", text="🍽️ 今天吃什麼"), style="secondary"),
        FlexButton(action=MessageAction(label="😊 不為人知的興趣", text="😊 不為人知的興趣"), style="secondary"),
    ]
    bubble = _make_bubble(
        "#F59E0B", "☕ 先來杯咖啡聊聊吧",
        f"嗨 {display_name}！\n三個輕鬆問題，不聊銷售也可以 👇",
        buttons,
    )
    return FlexMessage(alt_text=f"歡迎 {display_name}！先來聊聊吧 ☕", contents=bubble)


CARD_BUILDERS = {"A": build_card_a, "B": build_card_b, "C": build_card_c}

# ── Fever-bot background worker ───────────────────────────────────────────────
def _process_answer(session: fever_bot.CoachingSession, answer_text: str) -> None:
    """Run in a background thread: advance the session and push the reply to the group."""
    key = (session.group_id, session.user_id)
    try:
        reply_text, is_final = fever_bot.advance(session, answer_text)
    except Exception as e:
        print(f"[fever_bot.advance error] {e}")
        reply_text = "抱歉，系統忙線中，請稍後再輸入一次 🙏"
        is_final = False  # Leave session alive so the user can retry

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        try:
            line_bot_api.push_message(
                PushMessageRequest(to=session.group_id, messages=[TextMessage(text=reply_text)])
            )
        except Exception as e:
            print(f"[push_message error] {e}")

    if is_final:
        fever_bot.store.end(key)


# ── Webhook endpoint ──────────────────────────────────────────────────────────
@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers["X-Line-Signature"]
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"


# ── Member join → icebreaker card ─────────────────────────────────────────────
@handler.add(MemberJoinedEvent)
def handle_member_joined(event):
    group_id = event.source.group_id
    build_card = CARD_BUILDERS.get(STYLE, build_card_a)
    messages = []

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)

        for member in event.joined.members:
            if member.type != "user":
                continue
            try:
                profile = line_bot_api.get_group_member_profile(group_id, member.user_id)
                display_name = profile.display_name
            except Exception:
                display_name = "新成員"
            messages.append(build_card(display_name))

        if messages:
            try:
                line_bot_api.reply_message(
                    ReplyMessageRequest(reply_token=event.reply_token, messages=messages[:5])
                )
            except Exception as e:
                print(f"[icebreaker reply error] {e}")


# ── Group text messages ───────────────────────────────────────────────────────

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    if event.source.type != "group":
        return

    user_id = event.source.user_id
    group_id = event.source.group_id
    text = event.message.text.strip()
    key: fever_bot.SessionKey = (group_id, user_id)

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)

        # ── 1. Start / restart coaching session ───────────────
        if "開始輔導" in text:
            try:
                profile = line_bot_api.get_group_member_profile(group_id, user_id)
                name = profile.display_name
            except Exception:
                name = "同學"

            fever_bot.store.end(key)  # clear any existing session first
            session = fever_bot.store.start(key, group_id, user_id, name)
            first_q = fever_bot.pick_first_question()
            session.questions.append(first_q)

            welcome = admin_config.get_welcome_message().replace("{name}", name)
            try:
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(
                            text=f"{welcome}\n\n第1題：\n{first_q}"
                        )],
                    )
                )
            except Exception as e:
                print(f"[fever_start reply error] {e}")
            return

        # ── 2. Cancel / end coaching session ──────────────────
        if text in ("取消", "結束輔導") and fever_bot.store.get(key) is not None:
            fever_bot.store.end(key)
            try:
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text="輔導已取消，隨時輸入「開始輔導」重新開始 👋")],
                    )
                )
            except Exception as e:
                print(f"[fever_cancel reply error] {e}")
            return

        # ── 3. Active session — answer received ───────────────
        session = fever_bot.store.get(key)
        if session is not None:
            # Spawn background thread; webhook returns 200 immediately
            t = threading.Thread(target=_process_answer, args=(session, text), daemon=True)
            t.start()
            return

        # ── 4. Icebreaker button responses ────────────────────
        if text in BUTTON_RESPONSES:
            try:
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=BUTTON_RESPONSES[text])],
                    )
                )
            except Exception as e:
                print(f"[button reply error] {e}")
            return

        # ── 5. @mention echo ──────────────────────────────────
        mention = event.message.mention
        if not mention:
            return

        bot_mentioned = any(
            m.type == "user" and m.is_self for m in mention.mentionees
        )
        if not bot_mentioned:
            return

        chars = list(text)
        for m in sorted(mention.mentionees, key=lambda x: x.index, reverse=True):
            del chars[m.index : m.index + m.length]
        echo_text = "".join(chars).strip() or "你叫我？😄"

        try:
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=echo_text)],
                )
            )
        except Exception as e:
            print(f"[mention echo error] {e}")


# ── Admin API (Basic Auth) ────────────────────────────────────────────────────

admin_bp = Blueprint("admin", __name__, url_prefix="/admin/api")


def _check_basic_auth(auth) -> bool:
    expected_user = os.environ.get("ADMIN_USERNAME")
    expected_pass = os.environ.get("ADMIN_PASSWORD")
    if not expected_user or not expected_pass:
        return False
    return bool(auth) and auth.username == expected_user and auth.password == expected_pass


def _auth_challenge() -> Response:
    return Response(
        "Authentication required.",
        status=401,
        headers={"WWW-Authenticate": 'Basic realm="Fever Bot Admin"'},
    )


def require_basic_auth(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not _check_basic_auth(request.authorization):
            return _auth_challenge()
        return fn(*args, **kwargs)
    return wrapper


@admin_bp.route("/config", methods=["GET"])
@require_basic_auth
def get_admin_config():
    return jsonify(admin_config.get_config())


@admin_bp.route("/config", methods=["PUT"])
@require_basic_auth
def update_admin_config():
    patch = request.get_json(silent=True)
    if not isinstance(patch, dict):
        return jsonify({"error": "request body must be a JSON object"}), 400
    try:
        updated = admin_config.update_config(patch)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(updated)


app.register_blueprint(admin_bp)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=False)
