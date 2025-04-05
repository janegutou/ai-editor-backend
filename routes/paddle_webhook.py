from flask import Blueprint, request, jsonify
from db import supabase
from datetime import datetime
import json

PRICE_TOKEN_MAP = {
    "pri_01jqwy9mp2aw1vmnq68yc9zvp0": 100}


paddle_bp = Blueprint("paddle", __name__)

@paddle_bp.route("/webhook/paddle", methods=['POST'])
def handle_paddle_webhook():
    # 接受Paddle支付回调，处理付款成功
    # 写入 transaction 表 （supabase db)
    # 更新 users 表 （supabase db) 里的 tokens 字段 （增加）

    data = request.form.to_dict()
    alert = data.get("alert_name")
    print(f"Paddle webhook received data: {data}")

    if alert == "payment_succeeded":

        user_id = data.get("passthrough")
        amount = float(data.get("sale_gross", 0))  # 支付金额
        paddle_tx_id = data.get("order_id")

        # 验证用户, 如存在则提取 当前 tokens 余额
        response = supabase.table("users").select("auth_id", "tokens").eq("auth_id", user_id).execute()
        if not response.data:
            return jsonify({"error": "User not found"}), 40
        current_tokens = response.data[0]["tokens"]      


        # 交易写入 transaction 表
        response = supabase.table("transactions").insert([
            {"auth_id": user_id, "amount": amount, "paddle_tx_id": paddle_tx_id, "status": "completed", "type": "top-up"}
        ]).execute()


        # 更新 users 表 tokens 余额
        added_tokens = amount  # TODO: 根据不同模型定价，计算实际增加的 tokens 数量
        response = supabase.table("users").update({
            "tokens": int(current_tokens + added_tokens)
        }).eq("auth_id", user_id).execute()

    else:
        print(f"Unknown Paddle webhook alert: {alert}")

    return jsonify({"success": True})
