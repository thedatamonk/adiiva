from dotenv import load_dotenv
import os
import time
from jose import JWTError, jwt
from typing import Optional
from loguru import logger
load_dotenv()

SECRET_KEY = os.environ["JWT_SECRET"]
ALGORITHM = "HS256"
TOKEN_EXPIRY_SECONDS = 3600

def create_token(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "iat": int(time.time()),
        "exp": int(time.time()) + TOKEN_EXPIRY_SECONDS,
    }

    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def verify_token(token: str) -> Optional[str]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get("sub")   # return user_id if authentication successful
    except JWTError as e:
        logger.warning(f"JWT verification failed: {e}")
        return None



    
