from flask import Flask, jsonify, request, send_file, g
from flask_cors import CORS
from langchain_openai.chat_models.base import BaseChatOpenAI
from langchain_groq import ChatGroq
import re
import json
import uuid
import os
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import RGBColor, Pt
from supabase import create_client 
import jwt
from dotenv import load_dotenv
load_dotenv()

import config

LLM_MODEL = config.LLM_MODEL

if LLM_MODEL == "qroq":
    llm = ChatGroq(model="llama3-8b-8192")

if LLM_MODEL == "deepseek":
    llm = BaseChatOpenAI(
        model='deepseek-chat', 
        openai_api_base='https://api.deepseek.com',
        max_tokens=5000,
    )

app = Flask(__name__)
CORS(app)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# 设置最大生成次数和字数
MAX_GENERATIONS_PER_DAY = 10
MAX_WORDS_PER_GEN = 500


def get_user_from_token():
    token = request.headers.get("Authorization")
    if not token:
        return None
    token = token.split(" ")[1]
    
    try:
        # Decode the JWT to get the user ID
        decoded_token = jwt.decode(token, SUPABASE_JWT_SECRET, algorithms=['HS256'], audience='authenticated')
        user_id = decoded_token['sub']  # The user ID is in the 'sub' claim
        print(f"Decoded token for user {user_id}")
        return user_id
    
    except jwt.ExpiredSignatureError:
        print("Token has expired")
        return None
    except jwt.InvalidTokenError as e:
        print("Invalid token error:", e)
        return None
    

@app.before_request # register a request handler
def before_request():
    if request.endpoint in ['public_endpoint', 'login_endpoint', 'ping']: # skip authentication for public endpoints
        return
    
    user_id = get_user_from_token()

    if user_id:
        g.user_id = user_id
    else:
        g.user_id = None


def extract_context_data(context_text, window=1000):

    # 查找选中的文本并获取位置
    #print("context_text:", context_text)
    selected_match = re.search(r"\[\[SELECTED\]\](.*?)\[\[/SELECTED\]\]", context_text, re.DOTALL)
    #print("selected_match:", selected_match)
    cursor_match = re.search(r"\[\[CURSOR\]\]", context_text)
    #print("cursor_match:", cursor_match)

    selected_text = ""

    if selected_match:
        selected_text = selected_match.group(1) 
        selected_start = selected_match.start(0)
        selected_end = selected_match.end(0)

    elif cursor_match:
        selected_start = cursor_match.start()
        selected_end = cursor_match.end()

    else:
        selected_start = None
        selected_end = None

    before_text = context_text[:selected_start][-window:] if selected_start else ""
    after_text = context_text[selected_end:][:window] if selected_end else ""
    #print("before_text:", before_text)
    #print("after_text:", after_text)
    return selected_text, before_text, after_text

def construct_prompt(mode, custom_prompt, context_text):

    selected_text, before_text, after_text = extract_context_data(context_text)
    
    # TODO: tuning on the prompt for language alignment (with context language, if not specifically required), and generate text should be flowing right in the middle of the context.

    prompt = "You are a professional writing assistant.\n"
    
    if mode == "expand":
        prompt += "Your task is to expand the selected text or selected position with rich details, clear examples, and logical elaboration.\nConsider the surrounding context for better coherence, and align with context language."

    elif mode == "continue":
        prompt += "Your task is to continue writing from the selected text or selected position, to explore other related aspects of the content, ensuring diversity of thought and perspective. \nAvoid repeating the existing text or aspects already covered in the context. \nAlign with context language.\n"
    
    if before_text:
        prompt += f"\n# Context Before the Selection:\n{before_text}\n"

    if selected_text:
        prompt += f"\n# Selected Text:\n{selected_text}\n"
    else:
        prompt += f"\n# Selected Position\n"
    
    if after_text:
        prompt += f"\n# Context After the Selection:\n{after_text}"

    prompt += f"\n\nGenerate the text naturally and fluently. {custom_prompt}"
    prompt += f"\nReturn only the continuation text without any introductory or concluding sentence."

    return prompt


@app.route('/ping', methods=['GET'])
def ping():
    return jsonify({"message": "pong"})


@app.route('/generate', methods=['POST'])
def generate():
    # 验证用户是否登录
    if not g.user_id:
        return jsonify({"error": "User not authenticated"}), 401
    user_id = g.user_id

    data = request.json
    user_prompt = data.get("prompt", "generate text").strip()
    generate_mode = data.get("selected_mode", "continue").strip()
    context_text = data.get("context_text").strip()

    
    # check subscription status TODO:
    subscription_tier = supabase.table("users").select("subscription_tier").eq("auth_id", user_id).execute().data[0]["subscription_tier"]



    # 构建 prompt
    final_prompt = construct_prompt(generate_mode, user_prompt, context_text)
    print("final_prompt:", final_prompt)

    try:
        response = llm.invoke(final_prompt)
        print("response:", response)
        text = response.content
        #text = f"AI Response for prompt: {final_prompt}" # placeholder response
        return jsonify({"generated_text": text})
    except Exception as e:
        return jsonify({"error": str(e)}), 500



@app.route("/ensure_user", methods=["POST"])
def ensure_user():
    if not g.user_id:
        return jsonify({"error": "User not authenticated"}), 401
    user_id = g.user_id

    # 查询 users 表
    existing_user = supabase.table("users").select("*").eq("auth_id", user_id).execute()

    if not existing_user.data:  # 如果 users 表里没有该用户
        supabase.table("users").insert([
            {"auth_id": user_id, "role": "user", "subscription_tier": "free"}
        ]).execute()

    return jsonify({"status": "ok"})



#document_storage = {} # temporary storage for document content


@app.route('/save_document', methods=['POST'])
def save_document():
    data = request.get_json()
    content = data.get("content")
    #print(f"content: {content}")
    #print(f"content type: {type(content)}")

    if not g.user_id:
        return jsonify({"error": "User not authenticated"}), 401
    user_id = g.user_id
    #print(f"Saving document for user {user_id}")

    response = supabase.table("documents").upsert([
        {"user_id": user_id, "content": content}
    ]).execute()
    #document_storage[user_id] = content

    if response.data:
        #print(f"Document [{content}] saved for user {user_id}")
        return jsonify({"message": "Content saved successfully"})
    
    return jsonify({"error": response.error['message']}), 500


@app.route('/get_document', methods=['GET'])
def get_document():
    
    if not g.user_id:
        return jsonify({"error": "User not authenticated"}), 401
    user_id = g.user_id

    response = supabase.table("documents").select("content").eq("user_id", user_id).execute()

    if not response.data:
        return jsonify({"error": response.error['message']}), 500
    
    content = response.data[0]

    #content = document_storage.get(user_id, "")
    print(f"Retrieved document [{content[:100]}] for user {user_id}")

    return jsonify({"content": content})


@app.route('/export_document', methods=['GET'])
def export_document():
    if not g.user_id:
        return jsonify({"error": "User not authenticated"}), 401
    user_id = g.user_id
    response = supabase.table("documents").select("content").eq("user_id", user_id).execute()

    if not response.data:
        return jsonify({"error": response.error['message']}), 500
    
    content = response.data[0]
    #content = document_storage.get(user_id, "")

    print(f"Exporting document [{content[:100]}] for user {user_id}")

    try:
        lexical_content = json.loads(content)
    except Exception as e:
        return jsonify({"error": "Invalid JSON content"}), 400
    

    # ✅ 生成 Word 文档
    word_file_path = f"documents/{user_id}.docx"
    document = generate_word_from_lexical_content(lexical_content)
    document.save(word_file_path)

    return send_file(word_file_path, as_attachment=True, download_name=f"user_{user_id}.docx")



# ==== Word 文档生成器 ==== # TODO: move to a separate file

def generate_word_from_lexical_content(lexical_content):
    document = Document()

    # 设置全局默认字体
    set_default_font(document)

    # 确保 lexical_content 是字典格式并且包含根节点
    if isinstance(lexical_content, dict) and "root" in lexical_content:
        for node in lexical_content["root"]["children"]:
            if node["type"] == "paragraph":
                para = document.add_paragraph()
                add_text_from_node(para, node)
            elif node["type"] == "heading":
                # 标题处理（例如 h1 转换为 Heading 1）
                para = document.add_paragraph(style='Heading 1' if node.get("tag") == "h1" else 'Heading 2')
                add_text_from_node(para, node)
            elif node["type"] == "unordered-list":
                # 无序列表处理
                add_list_from_node(document, node, unordered=True)
            elif node["type"] == "ordered-list":
                # 有序列表处理
                add_list_from_node(document, node, unordered=False)
    else:
        raise ValueError("Invalid lexical content format")

    return document

def set_default_font(document):
    # 设置全局字体样式（中文宋体，英文 Calibri）
    style = document.styles['Normal']
    font = style.font
    font.name = 'Calibri'
    font.size = Pt(12)
    
    # 对中文进行单独设置
    font_element = style.element
    r_pr = font_element.get_or_add_rPr()
    
    # 设置中文字体为宋体
    chinese_font = OxmlElement('w:rFonts')
    chinese_font.set(qn('w:ascii'), 'Calibri')
    chinese_font.set(qn('w:eastAsia'), 'SimSun')  # 中文设置为宋体
    r_pr.append(chinese_font)

def add_text_from_node(paragraph, node):
    # 对每个段落或文本节点处理文本内容和格式
    for child in node["children"]:
        text = child["text"]
        run = paragraph.add_run(text)
        
        # 应用文本样式
        if child.get("format") == 1:  # 粗体
            run.bold = True
        if child.get("format") == 2:  # 斜体
            run.italic = True
        if child.get("format") == 4:  # 下划线
            run.underline = True
        if child.get("format") == 5:  # 删除线
            run.strike = True

def add_list_from_node(document, node, unordered=True):
    # 添加列表
    for child in node["children"]:
        if unordered:
            para = document.add_paragraph(style='List Bullet')
        else:
            para = document.add_paragraph(style='List Number')
        add_text_from_node(para, child)



if __name__ == '__main__':
    app.run(debug=True)
