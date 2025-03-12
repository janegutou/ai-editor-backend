from flask import Flask, jsonify, request, send_file
from flask_cors import CORS
from langchain_openai.chat_models.base import BaseChatOpenAI
from langchain_groq import ChatGroq
import re
import json
import uuid
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import RGBColor, Pt

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
    data = request.json
    user_prompt = data.get("prompt", "generate text").strip()
    generate_mode = data.get("selected_mode", "continue").strip()
    context_text = data.get("context_text").strip()

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


document_storage = {} # temporary storage for document content


@app.route('/save_document', methods=['POST'])
def save_document():
    data = request.get_json()
    content = data.get("content")
    user_id = data.get("user_id")

    # 存储内容
    if not user_id:
        print("No user_id provided, not saving document")
        return jsonify({"error": "Missing user_id"}), 400
    
    document_storage[user_id] = content
    print(f"Document [{content}] saved for user {user_id}")

    return jsonify({
        "user_id": user_id,
        "message": "Content saved successfully"
    })


@app.route('/get_document', methods=['GET'])
def get_document():
    user_id = request.args.get('user_id')    

    # 生成 user_id
    if not user_id:
        user_id = str(uuid.uuid4())
        print(f"No user_id provided, generating a random one {user_id}")

    content = document_storage.get(user_id, "")
    print(f"Retrieved document [{content}] for user {user_id}")

    return jsonify({
        "user_id": user_id,
        "content": content
    })


@app.route('/export_document', methods=['GET'])
def export_document():
    user_id = request.args.get('userId')
    if not user_id:
        return jsonify({"error": "Missing userId"}), 400

    #print(document_storage)
    content = document_storage.get(user_id, "")
    print(f"Exporting document [{content}] for user {user_id}")

    try:
        lexical_content = json.loads(content)
    except Exception as e:
        return jsonify({"error": "Invalid JSON content"}), 400
    

    # ✅ 生成 Word 文档
    word_file_path = f"documents/{user_id}.docx"
    document = generate_word_from_lexical_content(lexical_content)
    document.save(word_file_path)

    return send_file(word_file_path, as_attachment=True, download_name=f"user_{user_id}.docx")

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
