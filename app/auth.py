from datetime import datetime, timedelta
from jose import jwt

SECRET = "supersecret"

def create_token(data):
    return jwt.encode(data, SECRET, algorithm="HS256")

def verify_token(token):
    return jwt.decode(token, SECRET, algorithms=["HS256"])