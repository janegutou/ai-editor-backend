import os
from dotenv import load_dotenv
from supabase import create_client 
import jwt
from flask import request

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)



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
