import firebase_admin
from firebase_admin import credentials, auth, firestore
import streamlit as st
from typing import Optional, Dict, Any

class AuthError(Exception):
    """Custom authentication error class"""
    pass

def initialize_firebase():
    """Initialize Firebase app if not already initialized"""
    if not firebase_admin._apps:
        try:
            if st.secrets.has_key("firebase"):
                firebase_config = {
                    "type": st.secrets["firebase"]["type"],
                    "project_id": st.secrets["firebase"]["project_id"],
                    "private_key_id": st.secrets["firebase"]["private_key_id"],
                    "private_key": st.secrets["firebase"]["private_key"].replace('\\n', '\n'),
                    "client_email": st.secrets["firebase"]["client_email"],
                    "client_id": st.secrets["firebase"]["client_id"],
                    "auth_uri": st.secrets["firebase"]["auth_uri"],
                    "token_uri": st.secrets["firebase"]["token_uri"],
                    "auth_provider_x509_cert_url": st.secrets["firebase"]["auth_provider_x509_cert_url"],
                    "client_x509_cert_url": st.secrets["firebase"]["client_x509_cert_url"]
                }
                cred = credentials.Certificate(firebase_config)
            else:
                cred = credentials.Certificate("ai-doc-assistant-e2136-30ca48038308.json")
            
            firebase_admin.initialize_app(cred)
        except Exception as e:
            st.error(f"Firebase initialization failed: {str(e)}")
            raise AuthError("Failed to initialize Firebase")

initialize_firebase()

def get_firestore_db():
    """Get Firestore database instance"""
    return firestore.client()

def firebase_signup(email: str, password: str, username: str) -> auth.UserRecord:
    """Register new user with Firebase Auth and Firestore"""
    try:
        if not all([email, password, username]):
            raise AuthError("All fields are required")
        if len(password) < 6:
            raise AuthError("Password must be at least 6 characters")
        
        user = auth.create_user(
            email=email,
            password=password,
            display_name=username
        )
        
        db = get_firestore_db()
        user_data = {
            "uid": user.uid,
            "email": email,
            "username": username,
            "created_at": firestore.SERVER_TIMESTAMP,
            "last_login": firestore.SERVER_TIMESTAMP,
            "doc_count": 0
        }
        
        db.collection("users").document(user.uid).set(user_data)
        
        return user
        
    except auth.EmailAlreadyExistsError:
        raise AuthError("Email already in use")
    except auth.WeakPasswordError:
        raise AuthError("Password should be at least 6 characters")
    except Exception as e:
        raise AuthError(f"Registration failed: {str(e)}")

def firebase_login(email: str, password: str) -> auth.UserRecord:
    """Authenticate user with Firebase"""
    try:
        if not email or not password:
            raise AuthError("Email and password are required")
            
        user = auth.get_user_by_email(email)
        
        db = get_firestore_db()
        user_ref = db.collection("users").document(user.uid).get()
        if not user_ref.exists:
            raise AuthError("User account not properly registered")
            
        db.collection("users").document(user.uid).update({
            "last_login": firestore.SERVER_TIMESTAMP
        })
        
        return user
        
    except auth.UserNotFoundError:
        raise AuthError("Invalid email or password")
    except Exception as e:
        raise AuthError(f"Login error: {str(e)}")

def is_authenticated() -> bool:
    """Check if user is authenticated"""
    return 'user' in st.session_state and isinstance(st.session_state.user, auth.UserRecord)

def get_current_user() -> auth.UserRecord:
    """Get current authenticated user"""
    return st.session_state.user

def logout_user():
    """Clear user session"""
    if 'user' in st.session_state:
        del st.session_state.user
    if 'enhanced_text' in st.session_state:
        del st.session_state.enhanced_text
    if 'last_doc_id' in st.session_state:
        del st.session_state.last_doc_id
    st.rerun() 