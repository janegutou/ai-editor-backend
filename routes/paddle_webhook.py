from flask import Blueprint, request, jsonify
from db import supabase
from datetime import datetime
import json

PRICE_CREDIT_MAP = {  # 价格ID 对应 credit 单价的 映射
    "pri_01jqwy9mp2aw1vmnq68yc9zvp0": 1000,  # 单次购买$5时，credit 单价为 1/1000，即 一美元能买1000积分
    "pri_01jqwy2gavsm89a15sezkaet24": 1050,  # 单次购买$10时，credit 单价为 1/1050（打折扣了，价格稍低），即 一美元能买1050积分
    "pri_01jqwy8yntga8hrcyw3rrv384x": 1100,  # 单次购买$20时，credit 单价为 1/1100（进一步打折），即 一美元能买1100积分
}

paddle_bp = Blueprint("paddle", __name__)

@paddle_bp.route("/webhook/paddle", methods=['POST'])
def handle_paddle_webhook():
    # 接受Paddle支付回调，处理付款成功
    # 写入 transaction 表 （supabase db)
    # 更新 users 表 （supabase db) 里的 tokens 字段 （增加）
    
    data = request.json
    event = data.get("event_type")
    print(f"Paddle webhook received data: {data}")

    if event == "transaction.paid":

        user_id = data.get("data").get("custom_data")['user_id'] # get user_id from custom_data field

        amount = float(data.get("data").get("payments")[0]['amount'])/100  # get 支付金额 in USD
        
        paddle_id = data.get("data").get("id")  # get paddle transaction id

        price_id = data.get("data").get("items")[0]["price_id"]  # get price_id
        price_tag = data.get("data").get("items")[0]["price"]["name"]  # get price_name
        quantity = data.get("data").get("items")[0]["quantity"]  # get purchased quantity

        added_tokens = int(PRICE_CREDIT_MAP[price_id] * amount)  # 充值金额 乘以 特定比例；每个 price_id 对应一个比例

        # 验证用户, 如存在则提取 当前 tokens 余额
        response = supabase.table("users").select("auth_id", "tokens").eq("auth_id", user_id).execute()
        if not response.data:
            return jsonify({"error": "User not found"}), 40
        current_tokens = response.data[0]["tokens"]      


        # 交易写入 transaction 表
        response = supabase.table("transactions").insert([
            {"auth_id": user_id, "amount": amount, "token_amount": added_tokens, "paddle_transaction_id": paddle_id, "status": "completed", "type": "top-up", "price_tag": price_tag, "quantity": quantity}
        ]).execute()


        # 更新 users 表 tokens 余额
        response = supabase.table("users").update({
            "tokens": int(current_tokens + added_tokens)
        }).eq("auth_id", user_id).execute()

    else:
        print(f"Unknown Paddle webhook event: {event}")

    return jsonify({"success": True})
